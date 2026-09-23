package com.likedsongalarm

import android.content.Context
import androidx.core.content.edit
import java.time.DayOfWeek

data class AlarmSettings(
    val hour: Int = 7,
    val minute: Int = 0,
    /** Empty means every day. */
    val days: Set<DayOfWeek> = setOf(
        DayOfWeek.MONDAY, DayOfWeek.TUESDAY, DayOfWeek.WEDNESDAY, DayOfWeek.THURSDAY, DayOfWeek.FRIDAY,
    ),
    val enabled: Boolean = false,
    /** Share of the phone's max media volume to ramp up to. */
    val volumePercent: Int = 70,
    val fadeSeconds: Int = 60,
    val snoozeMinutes: Int = 9,
)

data class Token(val access: String, val refresh: String, val expiresAt: Long)

/** Everything the app remembers, kept in private SharedPreferences. */
class Prefs(context: Context) {
    private val sp = context.applicationContext.getSharedPreferences("alarm", Context.MODE_PRIVATE)

    var settings: AlarmSettings
        get() {
            val d = AlarmSettings()
            return AlarmSettings(
                hour = sp.getInt("hour", d.hour),
                minute = sp.getInt("minute", d.minute),
                days = sp.getString("days", null)
                    ?.split(',')?.filter { it.isNotBlank() }?.map { DayOfWeek.of(it.toInt()) }?.toSet()
                    ?: d.days,
                enabled = sp.getBoolean("enabled", d.enabled),
                volumePercent = sp.getInt("volumePercent", d.volumePercent),
                fadeSeconds = sp.getInt("fadeSeconds", d.fadeSeconds),
                snoozeMinutes = sp.getInt("snoozeMinutes", d.snoozeMinutes),
            )
        }
        set(s) = sp.edit {
            putInt("hour", s.hour)
            putInt("minute", s.minute)
            putString("days", s.days.sortedBy { it.value }.joinToString(",") { it.value.toString() })
            putBoolean("enabled", s.enabled)
            putInt("volumePercent", s.volumePercent)
            putInt("fadeSeconds", s.fadeSeconds)
            putInt("snoozeMinutes", s.snoozeMinutes)
        }

    /** Wall-clock millis of a pending snooze, or null. */
    var snoozeUntil: Long?
        get() = sp.getLong("snoozeUntil", 0L).takeIf { it > 0 }
        set(v) = sp.edit { if (v == null) remove("snoozeUntil") else putLong("snoozeUntil", v) }

    var clientId: String?
        get() = sp.getString("clientId", null)
        set(v) = sp.edit { putString("clientId", v) }

    var token: Token?
        get() {
            val access = sp.getString("access", null) ?: return null
            return Token(access, sp.getString("refresh", "")!!, sp.getLong("expiresAt", 0))
        }
        set(t) = sp.edit {
            if (t == null) {
                remove("access"); remove("refresh"); remove("expiresAt")
            } else {
                putString("access", t.access); putString("refresh", t.refresh); putLong("expiresAt", t.expiresAt)
            }
        }

    var pkceVerifier: String?
        get() = sp.getString("verifier", null)
        set(v) = sp.edit { putString("verifier", v) }

    var oauthState: String?
        get() = sp.getString("oauthState", null)
        set(v) = sp.edit { putString("oauthState", v) }

    /** True once the Spotify app has approved App Remote control for this app. */
    var remoteLinked: Boolean
        get() = sp.getBoolean("remoteLinked", false)
        set(v) = sp.edit { putBoolean("remoteLinked", v) }

    /** Track IDs we woke up to recently, newest first. */
    var recentTrackIds: List<String>
        get() = sp.getString("recent", "")!!.split(',').filter { it.isNotBlank() }
        set(v) = sp.edit { putString("recent", v.joinToString(",")) }

    fun rememberWakeSong(id: String) {
        recentTrackIds = (listOf(id) + recentTrackIds.filter { it != id }).take(30)
    }
}
