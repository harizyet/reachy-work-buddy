package app.reachy.companion

import android.content.Context
import app.reachy.companion.data.HomeSnapshot
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

/** The last Home the hub gave this phone and when, so Home has something to show offline and says so. App-private, not backed up, removed on sign-out. Nothing here is a credential. */
@Serializable
data class CachedHome(val view: HomeSnapshot, val checkedAtMs: Long)

object HomeCache {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private fun file(context: Context) = File(context.filesDir, "home-snapshot.json")

    @Synchronized fun read(context: Context): CachedHome? = runCatching { json.decodeFromString<CachedHome>(file(context).readText()) }.getOrNull()

    @Synchronized fun write(context: Context, cached: CachedHome) {
        val target = file(context)
        val temp = File(target.parentFile, target.name + ".tmp")
        runCatching { temp.writeText(json.encodeToString(cached)); if (!temp.renameTo(target)) { target.writeText(temp.readText()); temp.delete() } }
    }

    @Synchronized fun clear(context: Context) { file(context).delete() }
}
