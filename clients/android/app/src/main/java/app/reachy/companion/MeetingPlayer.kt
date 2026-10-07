package app.reachy.companion

import android.media.MediaPlayer
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.io.File

/**
 * Plays a meeting recording from a local copy (fetched once through the authenticated API), so a tapped
 * transcript line can start playback at its time. One meeting at a time; its copy is dropped on switching.
 */
class MeetingPlayer(private val dir: File, private val download: suspend (String, File) -> Unit) {
    var meetingId by mutableStateOf<String?>(null); private set
    var loading by mutableStateOf(false); private set
    var playing by mutableStateOf(false); private set
    var positionMs by mutableIntStateOf(0); private set
    var durationMs by mutableIntStateOf(0); private set
    var error by mutableStateOf<String?>(null)
    private var player: MediaPlayer? = null

    /** Starts at [seconds]; fetches the recording first when this meeting is not the loaded one. */
    suspend fun playFrom(id: String, seconds: Double) {
        if (meetingId != id || player == null) {
            if (!load(id)) return
        }
        val p = player ?: return
        p.seekTo((seconds * 1000).toInt().coerceAtLeast(0))
        p.start(); playing = true; positionMs = p.currentPosition
    }

    private suspend fun load(id: String): Boolean {
        release()
        loading = true; error = null
        return try {
            dir.mkdirs()
            val file = File(dir, "$id.audio")
            if (!file.exists()) { dir.listFiles()?.forEach { it.delete() }; download(id, file) }
            val p = MediaPlayer()
            p.setDataSource(file.absolutePath)
            p.setOnCompletionListener { playing = false }
            p.prepare()
            player = p; meetingId = id; durationMs = p.duration; true
        } catch (e: Exception) {
            error = "Could not play the recording: ${e.message ?: "unknown error"}"; false
        } finally { loading = false }
    }

    fun toggle() {
        val p = player ?: return
        if (p.isPlaying) { p.pause(); playing = false } else { p.start(); playing = true }
    }

    fun seekTo(ms: Int) { player?.seekTo(ms); positionMs = ms }

    /** Called by the UI while playing to keep the position and play state current. */
    fun refresh() {
        val p = player ?: return
        positionMs = p.currentPosition; playing = p.isPlaying
    }

    fun release() {
        player?.release(); player = null
        meetingId = null; playing = false; positionMs = 0; durationMs = 0
    }
}
