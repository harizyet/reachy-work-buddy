package app.reachy.companion.data

import java.time.OffsetDateTime

/** What the phone should do about an alarm that has just come due. */
sealed interface Verdict {
    /** The hub has not finished with this ring yet. */
    data object Wait : Verdict
    /** Reachy handled it, or the owner switched it off, or it should stay silent (privacy mode, do not disturb). */
    data object Done : Verdict
    /** Reachy could not play it: ring on the phone. */
    data class Ring(val why: String) : Verdict
}

/** Deliveries that mean nobody heard the alarm from Reachy. Privacy mode and do-not-disturb or meeting are not here: they are kept quiet on purpose. */
fun reachyCouldNotPlay(delivery: String): String? = when {
    delivery.startsWith("telegram: robot unavailable") -> "Reachy is offline"
    delivery.startsWith("telegram: not played, nobody detected") -> "Reachy did not find anyone in the room"
    delivery.startsWith("failed") -> "Reachy could not play it"
    else -> null
}

/**
 * Decides from the hub's record of this alarm. [dueMillis] is when this ring was due; the hub stamps `fired_at` when it
 * picks the ring up and clears `delivery` then, so a stamp at or after the due time with a delivery is this ring's outcome.
 */
fun phoneVerdict(alarm: Alarm?, dueMillis: Long): Verdict {
    if (alarm == null || alarm.status == "cancelled") return Verdict.Done
    val fired = alarm.firedAt?.let { runCatching { OffsetDateTime.parse(it).toInstant().toEpochMilli() }.getOrNull() }
    val thisRing = fired != null && fired >= dueMillis - 60_000
    if (!thisRing) {
        // Not picked up by the hub yet. If the owner switched it off or moved it (on the web, say) this phone's copy is stale.
        return if (!alarm.enabled || dueMillis(alarm) != dueMillis) Verdict.Done else Verdict.Wait
    }
    val delivery = alarm.delivery ?: return Verdict.Wait
    return reachyCouldNotPlay(delivery)?.let { Verdict.Ring(it) } ?: Verdict.Done
}

fun dueMillis(alarm: Alarm): Long = OffsetDateTime.parse(alarm.dueAt).toInstant().toEpochMilli()
