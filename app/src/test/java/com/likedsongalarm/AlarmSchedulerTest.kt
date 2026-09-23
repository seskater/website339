package com.likedsongalarm

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.DayOfWeek
import java.time.ZoneId
import java.time.ZonedDateTime

class AlarmSchedulerTest {
    private val zone = ZoneId.of("America/New_York")
    private val weekdays = setOf(
        DayOfWeek.MONDAY, DayOfWeek.TUESDAY, DayOfWeek.WEDNESDAY, DayOfWeek.THURSDAY, DayOfWeek.FRIDAY,
    )

    private fun at(y: Int, m: Int, d: Int, h: Int, min: Int) = ZonedDateTime.of(y, m, d, h, min, 0, 0, zone)

    @Test
    fun laterTodayWhenTimeHasNotPassed() {
        val s = AlarmSettings(hour = 7, minute = 0, enabled = true, days = weekdays)
        // Wednesday 2026-09-23, 06:00
        assertEquals(at(2026, 9, 23, 7, 0), AlarmScheduler.nextTrigger(s, at(2026, 9, 23, 6, 0)))
    }

    @Test
    fun tomorrowWhenTimeHasPassed() {
        val s = AlarmSettings(hour = 7, minute = 0, enabled = true, days = weekdays)
        assertEquals(at(2026, 9, 24, 7, 0), AlarmScheduler.nextTrigger(s, at(2026, 9, 23, 7, 0)))
    }

    @Test
    fun skipsWeekend() {
        val s = AlarmSettings(hour = 7, minute = 0, enabled = true, days = weekdays)
        // Friday 2026-09-25 08:00 -> Monday 2026-09-28
        assertEquals(at(2026, 9, 28, 7, 0), AlarmScheduler.nextTrigger(s, at(2026, 9, 25, 8, 0)))
    }

    @Test
    fun noDaysMeansEveryDay() {
        val s = AlarmSettings(hour = 9, minute = 30, enabled = true, days = emptySet())
        // Saturday
        assertEquals(at(2026, 9, 26, 9, 30), AlarmScheduler.nextTrigger(s, at(2026, 9, 26, 8, 0)))
    }

    @Test
    fun sameDayNextWeekWhenOnlyThatDay() {
        val s = AlarmSettings(hour = 7, minute = 0, enabled = true, days = setOf(DayOfWeek.WEDNESDAY))
        assertEquals(at(2026, 9, 30, 7, 0), AlarmScheduler.nextTrigger(s, at(2026, 9, 23, 7, 1)))
    }

    @Test
    fun disabledHasNoTrigger() {
        assertNull(AlarmScheduler.nextTrigger(AlarmSettings(enabled = false), at(2026, 9, 23, 6, 0)))
    }

    @Test
    fun springForwardGapStillRings() {
        // 2027-03-14 02:30 doesn't exist in New York; java.time shifts it to 03:30.
        val s = AlarmSettings(hour = 2, minute = 30, enabled = true, days = emptySet())
        val next = AlarmScheduler.nextTrigger(s, at(2027, 3, 14, 1, 0))!!
        assertEquals(3, next.hour)
        assertEquals(14, next.dayOfMonth)
    }
}
