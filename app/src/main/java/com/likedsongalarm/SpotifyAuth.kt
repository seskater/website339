package com.likedsongalarm

import android.content.Context
import android.net.Uri
import android.util.Base64
import androidx.browser.customtabs.CustomTabsIntent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.SecureRandom

class NotLoggedInException(message: String = "Not connected to Spotify.") : Exception(message)

/** Spotify Web API login using Authorization Code with PKCE (no client secret needed). */
object SpotifyAuth {
    const val REDIRECT_URI = "likedsongalarm://callback"
    private const val SCOPES =
        "user-library-read user-read-private user-read-email " +
            "user-read-playback-state user-modify-playback-state app-remote-control"

    private val refreshLock = Mutex()

    fun startLogin(context: Context, clientId: String) {
        val prefs = Prefs(context)
        val verifier = randomString(64)
        val state = randomString(16)
        prefs.clientId = clientId
        prefs.pkceVerifier = verifier
        prefs.oauthState = state

        val uri = Uri.parse("https://accounts.spotify.com/authorize").buildUpon()
            .appendQueryParameter("response_type", "code")
            .appendQueryParameter("client_id", clientId)
            .appendQueryParameter("scope", SCOPES)
            .appendQueryParameter("redirect_uri", REDIRECT_URI)
            .appendQueryParameter("code_challenge_method", "S256")
            .appendQueryParameter("code_challenge", challenge(verifier))
            .appendQueryParameter("state", state)
            .build()
        CustomTabsIntent.Builder().build().launchUrl(context, uri)
    }

    /** Finishes the login when Spotify redirects back to likedsongalarm://callback. */
    suspend fun handleRedirect(context: Context, uri: Uri) {
        val prefs = Prefs(context)
        uri.getQueryParameter("error")?.let { throw Exception("Spotify login was cancelled ($it).") }
        val code = uri.getQueryParameter("code") ?: throw Exception("Spotify didn't return a login code.")
        if (uri.getQueryParameter("state") != prefs.oauthState) throw Exception("Login check failed. Please try again.")

        requestToken(
            context,
            mapOf(
                "grant_type" to "authorization_code",
                "code" to code,
                "redirect_uri" to REDIRECT_URI,
                "client_id" to prefs.clientId.orEmpty(),
                "code_verifier" to prefs.pkceVerifier.orEmpty(),
            ),
        )
        prefs.pkceVerifier = null
        prefs.oauthState = null
    }

    /** Returns a valid access token, refreshing it when it's about to expire. */
    suspend fun accessToken(context: Context, forceRefresh: Boolean = false): String = refreshLock.withLock {
        val prefs = Prefs(context)
        val token = prefs.token ?: throw NotLoggedInException()
        if (!forceRefresh && System.currentTimeMillis() < token.expiresAt - 60_000) return token.access
        requestToken(
            context,
            mapOf(
                "grant_type" to "refresh_token",
                "refresh_token" to token.refresh,
                "client_id" to prefs.clientId.orEmpty(),
            ),
        ).access
    }

    fun logout(context: Context) {
        Prefs(context).apply {
            token = null
            remoteLinked = false
        }
    }

    private suspend fun requestToken(context: Context, form: Map<String, String>): Token = withContext(Dispatchers.IO) {
        val body = form.entries.joinToString("&") { (k, v) -> "$k=${URLEncoder.encode(v, "UTF-8")}" }
        val res = Http.request(
            "https://accounts.spotify.com/api/token",
            method = "POST",
            headers = mapOf("Content-Type" to "application/x-www-form-urlencoded"),
            body = body,
        )
        val json = runCatching { JSONObject(res.body) }.getOrDefault(JSONObject())
        if (res.code !in 200..299) {
            val message = json.optString("error_description").ifBlank { json.optString("error") }
                .ifBlank { "Spotify login failed (${res.code})" }
            if (json.optString("error") == "invalid_grant") {
                Prefs(context).token = null
                throw NotLoggedInException("Your Spotify login expired. Open the app and connect again.")
            }
            throw Exception(message)
        }
        val previous = Prefs(context).token
        Token(
            access = json.getString("access_token"),
            // Spotify may or may not rotate the refresh token.
            refresh = json.optString("refresh_token").ifBlank { previous?.refresh.orEmpty() },
            expiresAt = System.currentTimeMillis() + json.getLong("expires_in") * 1000,
        ).also { Prefs(context).token = it }
    }

    private fun randomString(length: Int): String {
        val chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        val random = SecureRandom()
        return (1..length).map { chars[random.nextInt(chars.length)] }.joinToString("")
    }

    private fun challenge(verifier: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray())
        return Base64.encodeToString(digest, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
    }
}
