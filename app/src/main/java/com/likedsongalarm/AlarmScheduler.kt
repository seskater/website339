package com.likedsongalarm

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.content.ContextCompat
import java.time.ZonedDateTime

/** Keeps exactly one system alarm pointed at the next ring (snooze or scheduled). */
object AlarmScheduler {

    fun nextTrigger(settings: AlarmSettings, from: ZonedDateTime = ZonedDateTime.now()): ZonedDateTime? {
        if (!settings.enabled) return null
        for (i in 0..7) {
            val date = from.toLocalDate().plusDays(i.toLong())
            if (settings.days.isNotEmpty() && date.dayOfWeek !in settings.days) continue
            val at = date.atTime(settings.hour, settings.minute).atZone(from.zone)
            if (at.isAfter(from)) return at
        }
        return null
    }

    /** Millis of the next time the alarm will ring, or null if nothing is scheduled. */
    fun nextFireMillis(context: Context): Long? {
        val prefs = Prefs(context)
        val now = System.currentTimeMillis()
        val snooze = prefs.snoozeUntil?.takeIf { it > now }
        val scheduled = nextTrigger(prefs.settings)?.toInstant()?.toEpochMilli()
        return listOfNotNull(snooze, scheduled).minOrNull()
    }

    fun canScheduleExact(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            context.getSystemService(AlarmManager::class.java).canScheduleExactAlarms()

    fun reschedule(context: Context) {
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        val operation = PendingIntent.getBroadcast(
            context, 0, Intent(context, AlarmReceiver::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val at = nextFireMillis(context)
        if (at == null) {
            alarmManager.cancel(operation)
            return
        }
        if (!canScheduleExact(context)) {
            // Degraded: may be a few minutes late. The app shows a warning with a fix.
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, operation)
            return
        }
        val showApp = PendingIntent.getActivity(
            context, 1, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        // setAlarmClock wakes the phone from Doze on time and shows the alarm icon in the status bar.
        alarmManager.setAlarmClock(AlarmManager.AlarmClockInfo(at, showApp), operation)
    }
}

/** Fired by AlarmManager at alarm time. */
class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val prefs = Prefs(context)
        // This firing uses up a snooze that was due now.
        prefs.snoozeUntil?.let { if (it <= System.currentTimeMillis() + 60_000) prefs.snoozeUntil = null }
        AlarmScheduler.reschedule(context)
        ContextCompat.startForegroundService(context, AlarmService.intent(context, AlarmService.ACTION_RING))
    }
}

/** Alarms are cleared on reboot, and exact times shift with clock/time zone changes. */
class RescheduleReceiver : BroadcastReceiver() {
    private val actions = setOf(
        Intent.ACTION_BOOT_COMPLETED,
        Intent.ACTION_MY_PACKAGE_REPLACED,
        Intent.ACTION_TIME_CHANGED,
        Intent.ACTION_TIMEZONE_CHANGED,
        AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED,
    )

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action in actions) AlarmScheduler.reschedule(context)
    }
}
