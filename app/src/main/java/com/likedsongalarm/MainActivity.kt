package com.likedsongalarm

import android.Manifest
import android.app.NotificationManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.format.DateFormat
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.lifecycleScope
import com.spotify.android.appremote.api.SpotifyAppRemote
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.time.DayOfWeek
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {

    /** Bumped whenever login state changes outside Compose (the login redirect). */
    private val loginVersion = MutableStateFlow(0)
    private val loginError = MutableStateFlow<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleLoginRedirect(intent)
        setContent {
            AlarmTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    App(this, loginVersion, loginError)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleLoginRedirect(intent)
    }

    private fun handleLoginRedirect(intent: Intent?) {
        val uri = intent?.data ?: return
        if (uri.scheme != "likedsongalarm") return
        setIntent(Intent(this, MainActivity::class.java))
        lifecycleScope.launch {
            try {
                SpotifyAuth.handleRedirect(this@MainActivity, uri)
                linkSpotifyApp(this@MainActivity)
            } catch (e: Exception) {
                loginError.value = e.message
            }
            loginVersion.value += 1
        }
    }
}

/**
 * Asks the Spotify app to let us control playback. Must run from an Activity once;
 * after that the alarm service can connect silently.
 */
suspend fun linkSpotifyApp(activity: ComponentActivity): String? {
    val prefs = Prefs(activity)
    val clientId = prefs.clientId ?: return "Connect Spotify first."
    if (!SpotifyRemote.isSpotifyInstalled(activity)) return "Install the Spotify app, then link it here."
    return try {
        val remote = SpotifyRemote.connect(activity, clientId, showAuthView = true)
        SpotifyAppRemote.disconnect(remote)
        prefs.remoteLinked = true
        null
    } catch (e: Exception) {
        prefs.remoteLinked = false
        "Couldn't link the Spotify app: ${e.message ?: e.javaClass.simpleName}. " +
            "Check the package name and SHA-1 fingerprint in your Spotify app settings."
    }
}

@Composable
private fun App(
    activity: MainActivity,
    loginVersion: MutableStateFlow<Int>,
    loginError: MutableStateFlow<String?>,
) {
    val version by loginVersion.collectAsState()
    val error by loginError.collectAsState()
    val context = LocalContext.current
    LaunchedEffect(error) {
        error?.let {
            Toast.makeText(context, it, Toast.LENGTH_LONG).show()
            loginError.value = null
        }
    }

    val loggedIn = remember(version) { Prefs(activity).token != null }
    Column(
        Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(Modifier.widthIn(max = 560.dp).fillMaxWidth()) {
            if (loggedIn) {
                AlarmScreen(activity, version, onLoggedOut = { loginVersion.value += 1 })
            } else {
                SetupScreen(activity)
            }
        }
    }
}

// --- Setup ---------------------------------------------------------------------------------

@Composable
private fun SetupScreen(activity: ComponentActivity) {
    val context = LocalContext.current
    var clientId by remember { mutableStateOf(Prefs(context).clientId.orEmpty()) }
    val sha1 = remember { signingSha1(context) }
    val spotifyInstalled = remember { SpotifyRemote.isSpotifyInstalled(context) }

    Text("Liked Song Alarm", fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(vertical = 8.dp))
    Card {
        Text("Wake up to your Liked Songs", style = MaterialTheme.typography.headlineSmall)
        Text(
            "At the time you pick, your phone plays a random song from your Spotify Liked Songs, " +
                "then more random likes until you get up.",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (!spotifyInstalled) {
            Warning("The Spotify app isn't installed. The alarm plays through it, so install it first.") {
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.spotify.music"))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            }
        }
        Step("1", "Open developer.spotify.com/dashboard and create an app. Tick Web API and Android.")
        Step("2", "Add this Redirect URI:")
        Copyable(SpotifyAuth.REDIRECT_URI)
        Step("3", "Under Android packages, add this package name and SHA-1 fingerprint:")
        Copyable(context.packageName)
        Copyable(sha1 ?: "Unavailable")
        Step("4", "Paste the app's Client ID:")
        OutlinedTextField(
            value = clientId,
            onValueChange = { clientId = it.trim() },
            label = { Text("Client ID") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = {
                if (!Regex("^[0-9a-fA-F]{32}$").matches(clientId)) {
                    Toast.makeText(context, "A Client ID is 32 letters and numbers.", Toast.LENGTH_LONG).show()
                } else {
                    SpotifyAuth.startLogin(activity, clientId)
                }
            },
            modifier = Modifier.fillMaxWidth().height(52.dp),
        ) { Text("Connect Spotify") }
        Text(
            "Needs Spotify Premium. Your login stays on this phone and is only sent to Spotify.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Step(number: String, text: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("$number.", fontWeight = FontWeight.SemiBold)
        Text(text)
    }
}

@Composable
private fun Copyable(value: String) {
    val context = LocalContext.current
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(MaterialTheme.colorScheme.surfaceContainerHigh)
            .padding(start = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(value, fontFamily = FontFamily.Monospace, fontSize = 13.sp, modifier = Modifier.weight(1f))
        TextButton(onClick = {
            context.getSystemService(ClipboardManager::class.java)
                .setPrimaryClip(ClipData.newPlainText("value", value))
            Toast.makeText(context, "Copied", Toast.LENGTH_SHORT).show()
        }) { Text("Copy") }
    }
}

// --- Alarm settings ------------------------------------------------------------------------

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AlarmScreen(activity: ComponentActivity, version: Int, onLoggedOut: () -> Unit) {
    val context = LocalContext.current
    val prefs = remember { Prefs(context) }
    val scope = rememberCoroutineScope()
    var settings by remember { mutableStateOf(prefs.settings) }
    var showTimePicker by remember { mutableStateOf(false) }
    var tick by remember { mutableIntStateOf(0) }
    var checks by remember { mutableStateOf(PermissionChecks.read(context)) }

    var account by remember { mutableStateOf("…") }
    var accountWarning by remember { mutableStateOf(false) }
    var likedCount by remember { mutableStateOf("…") }
    var remoteLinked by remember(version) { mutableStateOf(prefs.remoteLinked) }

    val notificationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        checks = PermissionChecks.read(context)
    }

    fun save(new: AlarmSettings) {
        if (!new.enabled) prefs.snoozeUntil = null
        settings = new
        prefs.settings = new
        AlarmScheduler.reschedule(context)
        tick++
    }

    LifecycleResumeEffect(Unit) {
        checks = PermissionChecks.read(context)
        settings = prefs.settings
        tick++
        onPauseOrDispose { }
    }
    LaunchedEffect(Unit) {
        while (true) { delay(30_000); tick++ }
    }
    LaunchedEffect(version) {
        try {
            val profile = SpotifyApi.profile(context)
            account = profile.name + if (profile.isPremium) "" else " (not Premium)"
            accountWarning = !profile.isPremium
            likedCount = "%,d".format(SpotifyApi.likedSongCount(context))
        } catch (e: NotLoggedInException) {
            Toast.makeText(context, e.message, Toast.LENGTH_LONG).show()
            onLoggedOut()
        } catch (e: Exception) {
            account = e.message ?: "Couldn't reach Spotify"
            accountWarning = true
        }
    }

    // Header
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("Liked Song Alarm", fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        TextButton(onClick = {
            save(settings.copy(enabled = false))
            SpotifyAuth.logout(context)
            onLoggedOut()
        }) { Text("Log out") }
    }

    // Big time + on/off
    val nextText = remember(tick, settings) { describeNext(context) }
    Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(
                formatTime(context, settings.hour, settings.minute),
                fontSize = 64.sp,
                fontWeight = FontWeight.Light,
                modifier = Modifier.clip(RoundedCornerShape(12.dp)).clickable { showTimePicker = true },
            )
            Text(
                nextText,
                color = if (nextText.startsWith("Off")) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.secondary,
                fontWeight = FontWeight.Medium,
            )
        }
        Switch(
            checked = settings.enabled,
            onCheckedChange = { on ->
                if (on && !checks.notifications && Build.VERSION.SDK_INT >= 33) {
                    notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                }
                save(settings.copy(enabled = on))
                if (on) {
                    AlarmScheduler.nextFireMillis(context)?.let {
                        Toast.makeText(context, "Alarm set. ${describeNext(context)}", Toast.LENGTH_SHORT).show()
                    }
                }
            },
        )
    }

    PermissionWarnings(checks, activity)

    Card {
        Label("Repeat on (none selected = every day)")
        val order = listOf(
            DayOfWeek.MONDAY, DayOfWeek.TUESDAY, DayOfWeek.WEDNESDAY, DayOfWeek.THURSDAY,
            DayOfWeek.FRIDAY, DayOfWeek.SATURDAY, DayOfWeek.SUNDAY,
        )
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            order.forEach { day ->
                val on = day in settings.days
                Box(
                    Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh)
                        .border(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = if (on) 0f else 1f), CircleShape)
                        .clickable {
                            save(settings.copy(days = if (on) settings.days - day else settings.days + day))
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        day.getDisplayName(java.time.format.TextStyle.NARROW, Locale.getDefault()),
                        fontWeight = FontWeight.SemiBold,
                        color = if (on) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }

        Spacer(Modifier.height(8.dp))
        Label("Volume  ${settings.volumePercent}%")
        var volume by remember(settings.volumePercent) { mutableStateOf(settings.volumePercent.toFloat()) }
        Slider(
            value = volume,
            onValueChange = { volume = it },
            onValueChangeFinished = { save(settings.copy(volumePercent = volume.toInt())) },
            valueRange = 10f..100f,
            steps = 17,
        )

        Label("Fade in")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(0 to "Off", 30 to "30 s", 60 to "1 min", 120 to "2 min", 300 to "5 min").forEach { (secs, label) ->
                FilterChip(
                    selected = settings.fadeSeconds == secs,
                    onClick = { save(settings.copy(fadeSeconds = secs)) },
                    label = { Text(label) },
                )
            }
        }

        Label("Snooze length")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(5, 9, 10, 15).forEach { mins ->
                FilterChip(
                    selected = settings.snoozeMinutes == mins,
                    onClick = { save(settings.copy(snoozeMinutes = mins)) },
                    label = { Text("$mins min") },
                )
            }
        }
    }

    Card {
        StatusRow("Account", account, accountWarning)
        StatusRow("Liked songs", likedCount)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Spotify app", color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
            if (remoteLinked) {
                Text("Linked")
            } else {
                TextButton(onClick = {
                    scope.launch {
                        linkSpotifyApp(activity)?.let { Toast.makeText(context, it, Toast.LENGTH_LONG).show() }
                        remoteLinked = prefs.remoteLinked
                    }
                }) { Text("Link Spotify app") }
            }
        }
    }

    FilledTonalButton(
        onClick = {
            if (!checks.notifications && Build.VERSION.SDK_INT >= 33) {
                notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
            ContextCompat.startForegroundService(context, AlarmService.intent(context, AlarmService.ACTION_TEST))
        },
        modifier = Modifier.fillMaxWidth().height(52.dp),
    ) { Text("Test alarm now") }

    Text(
        "Keep the Spotify app installed and logged in. If Spotify can't play, for example with no " +
            "internet, the alarm uses your phone's normal alarm sound.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(vertical = 12.dp),
    )

    if (showTimePicker) {
        TimeDialog(
            context = context,
            hour = settings.hour,
            minute = settings.minute,
            onDismiss = { showTimePicker = false },
            onConfirm = { h, m ->
                showTimePicker = false
                save(settings.copy(hour = h, minute = m, enabled = true))
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TimeDialog(
    context: Context,
    hour: Int,
    minute: Int,
    onDismiss: () -> Unit,
    onConfirm: (Int, Int) -> Unit,
) {
    val state = rememberTimePickerState(hour, minute, DateFormat.is24HourFormat(context))
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = { onConfirm(state.hour, state.minute) }) { Text("Set") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
        text = { TimePicker(state) },
    )
}

// --- Permissions -----------------------------------------------------------------------------

private data class PermissionChecks(val notifications: Boolean, val fullScreen: Boolean, val exactAlarms: Boolean) {
    companion object {
        fun read(context: Context) = PermissionChecks(
            notifications = NotificationManagerCompat.from(context).areNotificationsEnabled(),
            fullScreen = Build.VERSION.SDK_INT < 34 ||
                context.getSystemService(NotificationManager::class.java).canUseFullScreenIntent(),
            exactAlarms = AlarmScheduler.canScheduleExact(context),
        )
    }
}

@Composable
private fun PermissionWarnings(checks: PermissionChecks, activity: ComponentActivity) {
    val pkg = Uri.parse("package:${activity.packageName}")
    if (!checks.notifications) {
        Warning("Notifications are off. The alarm needs them to ring. Tap to allow.") {
            activity.startActivity(
                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName),
            )
        }
    }
    if (!checks.fullScreen && Build.VERSION.SDK_INT >= 34) {
        Warning("Allow full-screen alarms so the alarm screen shows when the phone is locked. Tap to fix.") {
            activity.startActivity(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, pkg))
        }
    }
    if (!checks.exactAlarms && Build.VERSION.SDK_INT >= 31) {
        Warning("Allow alarms & reminders so the alarm rings exactly on time. Tap to fix.") {
            activity.startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, pkg))
        }
    }
}

// --- Small UI pieces -------------------------------------------------------------------------

@Composable
private fun Card(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 16.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.surfaceContainer)
            .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(16.dp))
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        content = content,
    )
}

@Composable
private fun Label(text: String) {
    Text(text, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun StatusRow(label: String, value: String, warn: Boolean = false) {
    Row {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
        Text(
            value,
            textAlign = TextAlign.End,
            color = if (warn) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun Warning(text: String, onClick: () -> Unit) {
    Text(
        text,
        color = MaterialTheme.colorScheme.onErrorContainer,
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.errorContainer)
            .clickable(onClick = onClick)
            .padding(14.dp),
    )
}

// --- Helpers -------------------------------------------------------------------------------

private fun formatTime(context: Context, hour: Int, minute: Int): String {
    val cal = java.util.Calendar.getInstance().apply {
        set(java.util.Calendar.HOUR_OF_DAY, hour)
        set(java.util.Calendar.MINUTE, minute)
    }
    return DateFormat.getTimeFormat(context).format(cal.time)
}

private fun describeNext(context: Context): String {
    val at = AlarmScheduler.nextFireMillis(context) ?: return "Off"
    val prefs = Prefs(context)
    val snoozed = prefs.snoozeUntil?.let { it == at } == true
    val mins = ((at - System.currentTimeMillis()) / 60_000).coerceAtLeast(0)
    val inText = if (mins >= 60) "${mins / 60} h ${mins % 60} min" else "$mins min"
    val day = SimpleDateFormat("EEEE", Locale.getDefault()).format(Date(at))
    val time = DateFormat.getTimeFormat(context).format(Date(at))
    return "${if (snoozed) "Snoozed until" else "Rings"} $day $time · in $inText"
}

/** SHA-1 of the certificate this APK is signed with; Spotify needs it to allow App Remote. */
private fun signingSha1(context: Context): String? = runCatching {
    val pm = context.packageManager
    val signatures = if (Build.VERSION.SDK_INT >= 28) {
        pm.getPackageInfo(context.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
            .signingInfo?.apkContentsSigners
    } else {
        @Suppress("DEPRECATION")
        pm.getPackageInfo(context.packageName, PackageManager.GET_SIGNATURES).signatures
    }
    val cert = signatures?.firstOrNull()?.toByteArray() ?: return null
    MessageDigest.getInstance("SHA-1").digest(cert).joinToString(":") { "%02X".format(it) }
}.getOrNull()
