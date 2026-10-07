package app.reachy.companion.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.time.OffsetDateTime
import java.time.ZoneId

/** An alarm as the hub returns it. [repeat] lists weekdays, 0 = Monday … 6 = Sunday; empty rings once. */
@Serializable
data class Alarm(
    val id: String,
    val label: String,
    @SerialName("due_at") val dueAt: String,
    @SerialName("station_id") val stationId: String? = null,
    val status: String = "scheduled",
    val enabled: Boolean = true,
    val repeat: List<Int> = emptyList(),
    val volume: Int = 100,
    val delivery: String? = null,
    @SerialName("fired_at") val firedAt: String? = null,
)

@Serializable
data class Station(val id: String, val name: String)

private val DAY_NAMES = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
val SHORT_DAYS = DAY_NAMES

/** "Weekdays", "Weekends", "Every day", or the day names; empty for a one-time alarm. */
fun repeatText(days: Collection<Int>): String {
    val sorted = days.toSortedSet().toList()
    return when {
        sorted.isEmpty() -> ""
        sorted.size == 7 -> "Every day"
        sorted == listOf(0, 1, 2, 3, 4) -> "Weekdays"
        sorted == listOf(5, 6) -> "Weekends"
        else -> sorted.joinToString(", ") { DAY_NAMES[it] }
    }
}

/** The switch is on when the alarm is enabled and still waiting to ring. */
fun isOn(alarm: Alarm): Boolean = alarm.enabled && alarm.status == "scheduled"

data class ClockTime(val hour12: Int, val minute: Int, val pm: Boolean) {
    val text get() = "%d:%02d".format(hour12, minute)
    val suffix get() = if (pm) "PM" else "AM"
    /** "HH:MM", 24-hour, as the hub expects. */
    val wire get() = "%02d:%02d".format(hour12 % 12 + if (pm) 12 else 0, minute)
}

fun clockOf(hour24: Int, minute: Int) = ClockTime(if (hour24 % 12 == 0) 12 else hour24 % 12, minute, hour24 >= 12)

/** The alarm's time of day on this device. */
fun clockOf(alarm: Alarm, zone: ZoneId = ZoneId.systemDefault()): ClockTime {
    val local = OffsetDateTime.parse(alarm.dueAt).atZoneSameInstant(zone)
    return clockOf(local.hour, local.minute)
}

fun minuteOfDay(alarm: Alarm, zone: ZoneId = ZoneId.systemDefault()): Int {
    val local = OffsetDateTime.parse(alarm.dueAt).atZoneSameInstant(zone)
    return local.hour * 60 + local.minute
}

/** Live alarms ordered by time of day, like the Clock app; deleted ones are hidden. */
fun listedAlarms(alarms: List<Alarm>, zone: ZoneId = ZoneId.systemDefault()): List<Alarm> =
    alarms.filter { it.status != "cancelled" }.sortedBy { minuteOfDay(it, zone) }
