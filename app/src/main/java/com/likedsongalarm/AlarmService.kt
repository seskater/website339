package com.likedsongalarm

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.spotify.android.appremote.api.SpotifyAppRemote
import com.spotify.protocol.client.Subscription
import com.spotify.protocol.types.PlayerState
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull

/** What the ringing screen shows. Null in [AlarmService.ringState] means not ringing. */
data class RingState(
    val title: String,
    val subtitle: String,
    val art: Bitmap? = null,
    val note: String? = null,
)

/**
 * Foreground service that rings: picks random liked songs, plays them through the
 * Spotify app with a volume fade-in, and falls back to the phone's alarm sound when
 * Spotify can't play.
 */
class AlarmService : Service() {

    companion object {
        const val ACTION_RING = "com.likedsongalarm.RING"
        const val ACTION_TEST = "com.likedsongalarm.TEST"
        const val ACTION_SNOOZE = "com.likedsongalarm.SNOOZE"
        const val ACTION_DISMISS = "com.likedsongalarm.DISMISS"
        const val ACTION_NEXT_SONG = "com.likedsongalarm.NEXT_SONG"

        private const val TAG = "AlarmService"
        private const val CHANNEL_ID = "alarm"
        private const val NOTIFICATION_ID = 1
        private const val SONGS_PER_ALARM = 8
        private const val WATCHDOG_MS = 20_000L        // alarm sound if Spotify is silent by then
        private const val AUTO_STOP_MS = 30 * 60_000L  // give up after 30 minutes

        private val _ringState = MutableStateFlow<RingState?>(null)
        val ringState: StateFlow<RingState?> = _ringState

        fun intent(context: Context, action: String): Intent =
            Intent(context, AlarmService::class.java).setAction(action)
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val audio by lazy { getSystemService(AudioManager::class.java) }

    private var remote: SpotifyAppRemote? = null
    private var playerSubscription: Subscription<PlayerState>? = null
    private var queue: List<Track> = emptyList()
    private var queueIndex = 0
    private var currentUri: String? = null
    private var sawCurrentPlaying = false
    private var lastArtUri: String? = null

    private var fallbackPlayer: MediaPlayer? = null
    private var originalMusicVolume: Int? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var playJob: Job? = null
    private var fadeJob: Job? = null
    private var watchdogJob: Job? = null
    private var autoStopJob: Job? = null
    private var stopping = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_RING, ACTION_TEST -> startRinging(showScreen = intent.action == ACTION_TEST)
            ACTION_SNOOZE -> snooze()
            ACTION_DISMISS -> stopRinging()
            ACTION_NEXT_SONG -> if (_ringState.value != null) playNewRandomSongs()
            else -> if (_ringState.value == null) stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        cleanUp()
        scope.cancel()
        super.onDestroy()
    }

    // --- Ringing ---------------------------------------------------------------------------

    private fun startRinging(showScreen: Boolean) {
        if (_ringState.value != null) return
        stopping = false
        _ringState.value = RingState("Good morning", "Picking a song from your likes…")
        ServiceCompat.startForeground(
            this, NOTIFICATION_ID, buildNotification(),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK,
        )
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "LikedSongAlarm:ringing")
            .apply { acquire(AUTO_STOP_MS + 60_000) }

        // When the phone is locked, the full-screen notification opens the ringing screen.
        // A test run starts from the app, where we're allowed to open it directly.
        if (showScreen) {
            startActivity(Intent(this, AlarmActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        autoStopJob = scope.launch { delay(AUTO_STOP_MS); stopRinging() }
        playNewRandomSongs()
    }

    private fun playNewRandomSongs() {
        playJob?.cancel()
        watchdogJob?.cancel()
        stopFallbackSound()
        _ringState.update { it?.copy(note = null) }

        playJob = scope.launch {
            try {
                val prefs = Prefs(this@AlarmService)
                val clientId = prefs.clientId ?: throw NotLoggedInException()
                if (!SpotifyRemote.isSpotifyInstalled(this@AlarmService)) {
                    throw Exception("the Spotify app isn't installed")
                }

                val tracks = SpotifyApi.randomLikedTracks(this@AlarmService, SONGS_PER_ALARM)
                queue = tracks
                queueIndex = 0
                prefs.rememberWakeSong(tracks.first().id)
                showTrack(tracks.first())

                val r = remote?.takeIf { it.isConnected } ?: withTimeout(20_000) {
                    SpotifyRemote.connect(this@AlarmService, clientId, showAuthView = false)
                }.also { connected ->
                    remote = connected
                    subscribeToPlayer(connected)
                }

                startFadeIn(prefs.settings)
                // Make sure it plays on the phone, not a speaker Spotify was last connected to.
                runCatching { r.connectApi.connectSwitchToLocalDevice().awaitCall() }
                playTrack(r, tracks.first())
                startWatchdog(r)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w(TAG, "Spotify playback failed", e)
                playFallbackSound(e.message ?: e.javaClass.simpleName)
            }
        }
    }

    private suspend fun playTrack(r: SpotifyAppRemote, track: Track) {
        currentUri = track.uri
        sawCurrentPlaying = false
        r.playerApi.play(track.uri).awaitCall()
    }

    /**
     * When our song ends, Spotify either moves on to something else or stops. Either way,
     * keep the alarm going with the next random like until the user dismisses it.
     */
    private fun subscribeToPlayer(r: SpotifyAppRemote) {
        playerSubscription = r.playerApi.subscribeToPlayerState().setEventCallback { state ->
            val track = state.track ?: return@setEventCallback
            if (_ringState.value == null || stopping || playJob?.isActive == true) return@setEventCallback

            val isOurSong = track.uri == currentUri
            if (isOurSong && !state.isPaused) {
                sawCurrentPlaying = true
                _ringState.update {
                    it?.copy(title = track.name, subtitle = track.artists.joinToString(", ") { a -> a.name })
                }
                if (track.imageUri != null && track.imageUri.raw != lastArtUri) {
                    lastArtUri = track.imageUri.raw
                    r.imagesApi.getImage(track.imageUri).setResultCallback { bitmap ->
                        _ringState.update { it?.copy(art = bitmap) }
                    }
                }
            } else if (sawCurrentPlaying && (!isOurSong || state.isPaused)) {
                sawCurrentPlaying = false
                queueIndex += 1
                if (queueIndex < queue.size) {
                    val next = queue[queueIndex]
                    showTrack(next)
                    scope.launch {
                        runCatching { playTrack(r, next) }
                        startWatchdog(r)
                    }
                } else {
                    playNewRandomSongs()
                }
            }
        }
    }

    private fun showTrack(track: Track) {
        _ringState.update { it?.copy(title = track.name, subtitle = track.artists, art = null) }
        notify(buildNotification())
    }

    /** If Spotify is still silent after a while, sound the regular alarm so nobody oversleeps. */
    private fun startWatchdog(r: SpotifyAppRemote) {
        watchdogJob?.cancel()
        watchdogJob = scope.launch {
            delay(WATCHDOG_MS)
            val state: PlayerState? = withTimeoutOrNull(5_000) { runCatching { r.playerApi.playerState.awaitCall() }.getOrNull() }
            if (state == null || state.isPaused) playFallbackSound("Spotify didn't start playing")
        }
    }

    // --- Volume fade-in -------------------------------------------------------------------

    private fun startFadeIn(settings: AlarmSettings) {
        fadeJob?.cancel()
        val stream = AudioManager.STREAM_MUSIC
        if (originalMusicVolume == null) originalMusicVolume = audio.getStreamVolume(stream)
        val max = audio.getStreamMaxVolume(stream)
        val target = (max * settings.volumePercent / 100f).toInt().coerceIn(1, max)

        if (settings.fadeSeconds <= 0) {
            setMusicVolume(target)
            return
        }
        setMusicVolume(1)
        fadeJob = scope.launch {
            val stepMs = (settings.fadeSeconds * 1000L / target).coerceAtLeast(250)
            for (level in 1..target) {
                setMusicVolume(level)
                delay(stepMs)
            }
        }
    }

    private fun setMusicVolume(level: Int) {
        runCatching { audio.setStreamVolume(AudioManager.STREAM_MUSIC, level, 0) }
    }

    // --- Fallback alarm sound -------------------------------------------------------------

    private fun playFallbackSound(reason: String) {
        if (_ringState.value == null || stopping) return
        _ringState.update {
            it?.copy(
                title = if (queue.isEmpty()) "Wake up!" else it.title,
                note = "Couldn't play Spotify ($reason), so here's your alarm sound.",
            )
        }
        if (fallbackPlayer != null) return
        val uri = RingtoneManager.getActualDefaultRingtoneUri(this, RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        fallbackPlayer = runCatching {
            MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build(),
                )
                setDataSource(this@AlarmService, uri)
                isLooping = true
                prepare()
                start()
            }
        }.onFailure { Log.e(TAG, "Fallback alarm sound failed", it) }.getOrNull()
    }

    private fun stopFallbackSound() {
        fallbackPlayer?.run { runCatching { stop() }; release() }
        fallbackPlayer = null
    }

    // --- Snooze / stop --------------------------------------------------------------------

    private fun snooze() {
        if (_ringState.value == null) return stopSelf()
        val prefs = Prefs(this)
        prefs.snoozeUntil = System.currentTimeMillis() + prefs.settings.snoozeMinutes * 60_000L
        AlarmScheduler.reschedule(this)
        stopRinging()
    }

    private fun stopRinging() {
        if (stopping) return
        stopping = true
        _ringState.value = null
        playJob?.cancel()
        watchdogJob?.cancel()
        fadeJob?.cancel()
        autoStopJob?.cancel()
        stopFallbackSound()

        val r = remote
        scope.launch {
            // Pause before putting the volume back, so the song doesn't blare for a moment.
            if (r != null) withTimeoutOrNull(3_000) { runCatching { r.playerApi.pause().awaitCall() } }
            if (!stopping) return@launch // a new alarm started meanwhile
            cleanUp()
            ServiceCompat.stopForeground(this@AlarmService, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun cleanUp() {
        playerSubscription?.cancel()
        playerSubscription = null
        remote?.let { SpotifyAppRemote.disconnect(it) }
        remote = null
        currentUri = null
        lastArtUri = null
        queue = emptyList()
        stopFallbackSound()
        originalMusicVolume?.let { setMusicVolume(it) }
        originalMusicVolume = null
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
        _ringState.value = null
    }

    // --- Notification ---------------------------------------------------------------------

    private fun buildNotification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL_ID) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Alarm", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Shows the alarm while it's ringing"
                    setSound(null, null) // the music is the sound
                    lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                },
            )
        }
        val openScreen = PendingIntent.getActivity(
            this, 0,
            Intent(this, AlarmActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val state = _ringState.value
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_alarm)
            .setContentTitle("Wake up")
            .setContentText(state?.let { "${it.title} · ${it.subtitle}" } ?: "Alarm")
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openScreen)
            .setFullScreenIntent(openScreen, true)
            .addAction(0, "Snooze", serviceIntent(ACTION_SNOOZE, 1))
            .addAction(0, "I'm up", serviceIntent(ACTION_DISMISS, 2))
            .build()
    }

    private fun notify(notification: Notification) {
        if (_ringState.value == null) return
        runCatching { getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification) }
    }

    private fun serviceIntent(action: String, requestCode: Int): PendingIntent =
        PendingIntent.getService(
            this, requestCode, intent(this, action),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
}
