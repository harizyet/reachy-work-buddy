package app.reachy.companion

import android.content.Context
import app.reachy.companion.data.ScheduleView
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

/** The last schedule the hub gave this phone and when the phone got it, so the Calendar screen has something to show offline. App-private, not backed up, removed on sign-out. */
@Serializable
data class CachedSchedule(val view: ScheduleView, val checkedAtMs: Long)

object CalendarCache {
    private val json = Json { ignoreUnknownKeys = true }
    private fun file(context: Context) = File(context.filesDir, "calendar-schedule.json")

    @Synchronized fun read(context: Context): CachedSchedule? = runCatching { json.decodeFromString<CachedSchedule>(file(context).readText()) }.getOrNull()

    @Synchronized fun write(context: Context, cached: CachedSchedule) {
        val target = file(context)
        val temp = File(target.parentFile, target.name + ".tmp")
        runCatching { temp.writeText(json.encodeToString(cached)); if (!temp.renameTo(target)) { target.writeText(temp.readText()); temp.delete() } }
    }

    @Synchronized fun clear(context: Context) { file(context).delete() }
}
