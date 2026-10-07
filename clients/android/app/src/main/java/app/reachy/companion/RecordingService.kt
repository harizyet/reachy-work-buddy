package app.reachy.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.Prefs
import app.reachy.companion.data.ReachyApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** UI-visible recording state. The service owns the recorder; screens only observe this. */
object RecordingController {
    var recording by mutableStateOf(false); internal set
    var startedAt by mutableStateOf(0L); internal set
    var uploading by mutableStateOf(false); internal set
    var error by mutableStateOf<String?>(null)
    /** Bumped after each successful upload so the Meetings list reloads. */
    var uploadedCount by mutableIntStateOf(0); internal set

    fun start(context: Context) {
        error = null
        ContextCompat.startForegroundService(context, Intent(context, RecordingService::class.java).setAction(RecordingService.START))
    }

    fun stop(context: Context) {
        context.startService(Intent(context, RecordingService::class.java).setAction(RecordingService.STOP))
    }

    fun pendingDir(context: Context) = File(context.filesDir, "pending-meetings").apply { mkdirs() }
}

/**
 * Records in a foreground service (microphone type) with a partial wake lock, so the clip keeps
 * running when the screen turns off or another app is in front. A finished clip is uploaded
 * here; if the upload fails it stays in pending-meetings and is retried from the Meetings tab.
 */
class RecordingService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var recorder: MeetingRecorder
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        recorder = MeetingRecorder(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            START -> begin()
            STOP -> finish()
            else -> if (!RecordingController.recording) stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun begin() {
        if (RecordingController.recording) return
        enterForeground("Recording meeting", stoppable = true)
        try {
            recorder.start()
        } catch (e: Exception) {
            RecordingController.error = "Could not start recording"
            leaveForeground(); stopSelf(); return
        }
        wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "reachy:recording").apply { acquire(4 * 60 * 60 * 1000L) }
        RecordingController.startedAt = System.currentTimeMillis()
        RecordingController.recording = true
    }

    private fun finish() {
        if (!RecordingController.recording) { stopSelf(); return }
        RecordingController.recording = false
        releaseWakeLock()
        val clip = recorder.stop()
        if (clip == null) {
            RecordingController.error = "Nothing was recorded"
            leaveForeground(); stopSelf(); return
        }
        val pending = File(RecordingController.pendingDir(this), clip.name)
        if (!clip.renameTo(pending)) { clip.copyTo(pending, overwrite = true); clip.delete() }
        enterForeground("Uploading meeting…", stoppable = false)
        RecordingController.uploading = true
        scope.launch {
            val failure = uploadPending(applicationContext)
            RecordingController.uploading = false
            RecordingController.error = failure?.let { "Upload failed ($it). The recording is kept on this phone and will retry from the Meetings tab." }
            leaveForeground(); stopSelf()
        }
    }

    override fun onDestroy() {
        // Killed or swiped away mid-recording: keep what was captured rather than losing it.
        if (RecordingController.recording) {
            RecordingController.recording = false
            recorder.stop()?.let { it.renameTo(File(RecordingController.pendingDir(this), it.name)) }
        }
        releaseWakeLock()
        scope.cancel()
        super.onDestroy()
    }

    private fun releaseWakeLock() { wakeLock?.takeIf { it.isHeld }?.release(); wakeLock = null }

    private fun leaveForeground() { stopForeground(STOP_FOREGROUND_REMOVE) }

    private fun enterForeground(text: String, stoppable: Boolean) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Meeting recording", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)
        val builder = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Reachy").setContentText(text)
            .setOngoing(true).setOnlyAlertOnce(true).setContentIntent(open)
            .setCategory(Notification.CATEGORY_SERVICE)
        if (stoppable) builder.addAction(
            0, "Stop and save",
            PendingIntent.getService(this, 1, Intent(this, RecordingService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE),
        )
        val notification = builder.build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        else startForeground(NOTIFICATION_ID, notification)
    }

    companion object {
        const val START = "app.reachy.companion.RECORD_START"
        const val STOP = "app.reachy.companion.RECORD_STOP"
        private const val CHANNEL = "recording"
        private const val NOTIFICATION_ID = 7
    }
}

/** Uploads every clip waiting in pending-meetings; returns the first failure message, or null when all went up. */
suspend fun uploadPending(context: Context): String? {
    val prefs = Prefs(context)
    if (prefs.baseUrl.isBlank()) return "not signed in"
    val api = ReachyApi(prefs.baseUrl, PersistentCookieJar({ prefs.cookies }, { prefs.cookies = it }))
    for (clip in RecordingController.pendingDir(context).listFiles().orEmpty().sortedBy { it.name }) {
        val stamp = clip.name.removePrefix("recording-").removeSuffix(".m4a").toLongOrNull() ?: clip.lastModified()
        val title = "Meeting " + SimpleDateFormat("d MMM HH:mm", Locale.getDefault()).format(Date(stamp))
        try {
            api.uploadMeeting(title, clip)
            clip.delete()
            RecordingController.uploadedCount++
        } catch (e: Exception) {
            return e.message ?: "network error"
        }
    }
    return null
}
