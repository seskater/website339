package com.likedsongalarm

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject
import kotlin.random.Random

data class Track(val id: String, val uri: String, val name: String, val artists: String)

data class Profile(val name: String, val isPremium: Boolean)

class SpotifyApiException(message: String, val status: Int) : Exception(message)

/** The few Spotify Web API calls the alarm needs. */
object SpotifyApi {
    private const val BASE = "https://api.spotify.com/v1"

    private suspend fun get(context: Context, path: String): JSONObject = withContext(Dispatchers.IO) {
        var forceRefresh = false
        repeat(4) { attempt ->
            val token = SpotifyAuth.accessToken(context, forceRefresh)
            val res = Http.request(BASE + path, headers = mapOf("Authorization" to "Bearer $token"))
            when {
                res.code in 200..299 -> return@withContext JSONObject(res.body.ifBlank { "{}" })
                res.code == 429 -> delay((res.retryAfterSeconds ?: 1L) * 1000)
                res.code == 401 && attempt == 0 -> forceRefresh = true
                else -> {
                    val message = runCatching { JSONObject(res.body).getJSONObject("error").getString("message") }
                        .getOrNull() ?: "Spotify error ${res.code}"
                    throw SpotifyApiException(message, res.code)
                }
            }
        }
        throw SpotifyApiException("Spotify is busy. Try again in a moment.", 429)
    }

    suspend fun profile(context: Context): Profile {
        val me = get(context, "/me")
        return Profile(
            name = me.optString("display_name").ifBlank { me.optString("id") },
            isPremium = me.optString("product", "premium") == "premium",
        )
    }

    suspend fun likedSongCount(context: Context): Int = get(context, "/me/tracks?limit=1").getInt("total")

    /**
     * Random songs from Liked Songs. Jumps to random offsets instead of downloading the
     * whole library, so it stays fast with thousands of likes. Recent wake-up songs go last.
     */
    suspend fun randomLikedTracks(context: Context, count: Int): List<Track> = coroutineScope {
        val total = likedSongCount(context)
        if (total == 0) throw Exception("Your Liked Songs list is empty.")

        val want = minOf(count, total)
        val offsets = mutableSetOf<Int>()
        val attempts = minOf(total, want + 4) // spares for local files / unavailable songs
        while (offsets.size < attempts) offsets += Random.nextInt(total)

        val tracks = offsets.map { offset ->
            async {
                runCatching {
                    val item = get(context, "/me/tracks?limit=1&offset=$offset&market=from_token")
                        .getJSONArray("items").getJSONObject(0).getJSONObject("track")
                    if (item.optBoolean("is_local") || !item.optBoolean("is_playable", true)) {
                        null
                    } else {
                        val artists = item.getJSONArray("artists")
                        Track(
                            id = item.getString("id"),
                            uri = item.getString("uri"),
                            name = item.getString("name"),
                            artists = (0 until artists.length()).joinToString(", ") {
                                artists.getJSONObject(it).getString("name")
                            },
                        )
                    }
                }.getOrNull()
            }
        }.awaitAll().filterNotNull()

        if (tracks.isEmpty()) throw Exception("Couldn't find a playable liked song.")
        val recent = Prefs(context).recentTrackIds.toSet()
        tracks.sortedBy { it.id in recent }.take(want)
    }
}
