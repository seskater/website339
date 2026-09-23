package com.likedsongalarm

import android.content.Context
import com.spotify.android.appremote.api.ConnectionParams
import com.spotify.android.appremote.api.Connector
import com.spotify.android.appremote.api.SpotifyAppRemote
import com.spotify.protocol.client.CallResult
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Coroutine wrappers around the Spotify App Remote SDK, which drives the installed Spotify app. */
object SpotifyRemote {

    fun isSpotifyInstalled(context: Context): Boolean = SpotifyAppRemote.isSpotifyInstalled(context)

    /**
     * Connects to the Spotify app. Pass [showAuthView] = true from an Activity the first time,
     * so Spotify can ask the user to allow this app to control playback.
     */
    suspend fun connect(context: Context, clientId: String, showAuthView: Boolean): SpotifyAppRemote =
        suspendCancellableCoroutine { cont ->
            val params = ConnectionParams.Builder(clientId)
                .setRedirectUri(SpotifyAuth.REDIRECT_URI)
                .showAuthView(showAuthView)
                .build()
            SpotifyAppRemote.connect(context, params, object : Connector.ConnectionListener {
                override fun onConnected(remote: SpotifyAppRemote) {
                    if (cont.isActive) cont.resume(remote) else SpotifyAppRemote.disconnect(remote)
                }

                override fun onFailure(error: Throwable) {
                    if (cont.isActive) cont.resumeWithException(error)
                }
            })
        }
}

suspend fun <T> CallResult<T>.awaitCall(): T = suspendCancellableCoroutine { cont ->
    setResultCallback { if (cont.isActive) cont.resume(it) }
    setErrorCallback { if (cont.isActive) cont.resumeWithException(it) }
    cont.invokeOnCancellation { cancel() }
}
