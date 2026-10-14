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
import android.os.SystemClock
import app.reachy.companion.data.ASK_BELOW_SECONDS
import app.reachy.companion.data.ShortVerdict
import app.reachy.companion.data.discardedShortRecordingMessage
import app.reachy.companion.data.shortRecordingVerdict
import android.os.PowerManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.PreparedMeeting
import app.reachy.companion.data.Prefs
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.RecordingGate
import app.reachy.companion.data.RecordingPlan
import app.reachy.companion.data.decodePlan
import app.reachy.companion.data.encodePlan
import app.reachy.companion.data.recordingGate
import app.reachy.companion.data.recordingTitle
import app.reachy.companion.data.scheduledText
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
    /** The calendar meeting being recorded, when the recording was started from a meeting reminder. It follows the clip until the upload, so a restart does not lose it. */
    var plan by mutableStateOf<RecordingPlan?>(null); internal set
    /** Bumped after each successful upload so the Meetings list reloads. */
    var uploadedCount by mutableIntStateOf(0); internal set

    fun start(context: Context, prepared: PreparedMeeting? = null) {
        error = null
        val intent = Intent(context, RecordingService::class.java).setAction(RecordingService.START)
        if (prepared != null) intent.putExtra(RecordingService.PLAN_KEY, prepared.key).putExtra(RecordingService.PLAN_TITLE, prepared.title).putExtra(RecordingService.PLAN_START, prepared.startMs)
        ContextCompat.startForegroundService(context, intent)
    }

    /** A clip stopped after 10 to 30 seconds, held back from the upload until the owner says whether it was a mistake. */
    class HeldClip(val clip: File, val seconds: Long)
    var held by mutableStateOf<HeldClip?>(null); internal set

    fun heldDir(context: Context) = File(context.filesDir, "held-meetings").apply { mkdirs() }
    private fun secondsFile(clip: File) = File(clip.parentFile, clip.name + ".secs")

    /** Remembers a held clip's length beside it, so the question can be asked again after the app was closed. */
    internal fun hold(clip: File, seconds: Long) { runCatching { secondsFile(clip).writeText(seconds.toString()) }; held = HeldClip(clip, seconds) }

    /** Picks up a clip that was held when the app last closed. */
    fun loadHeld(context: Context) {
        if (held != null) return
        val clip = heldDir(context).listFiles().orEmpty().filter { it.name.endsWith(".m4a") }.minByOrNull { it.name } ?: return
        held = HeldClip(clip, runCatching { secondsFile(clip).readText().trim().toLong() }.getOrDefault(ASK_BELOW_SECONDS - 1))
    }

    /** "Yes, it was a mistake": the clip and its notes are deleted and nothing is uploaded. */
    fun discardHeld() {
        val h = held ?: return
        held = null
        h.clip.delete(); secondsFile(h.clip).delete(); planFile(h.clip).delete()
    }

    /** "No, keep it": the clip joins the normal queue and the service uploads it exactly as a longer recording. */
    fun uploadHeld(context: Context) {
        val h = held ?: return
        held = null
        val target = File(pendingDir(context), h.clip.name)
        if (!h.clip.renameTo(target)) return
        val plan = planFile(h.clip)
        if (plan.exists()) plan.renameTo(planFile(target))
        secondsFile(h.clip).delete()
        ContextCompat.startForegroundService(context, Intent(context, RecordingService::class.java).setAction(RecordingService.UPLOAD))
    }

    fun stop(context: Context) {
        context.startService(Intent(context, RecordingService::class.java).setAction(RecordingService.STOP))
    }

    fun pendingDir(context: Context) = File(context.filesDir, "pending-meetings").apply { mkdirs() }

    /** The note kept beside a clip while it waits to upload. */
    fun planFile(clip: File) = File(clip.parentFile, clip.name + ".meeting.json")

    /** Calendar occurrences that have a recording on this phone waiting to upload. */
    fun pendingKeys(context: Context): Set<String> =
        pendingDir(context).listFiles().orEmpty().filter { it.name.endsWith(".meeting.json") }.mapNotNull { decodePlan(runCatching { it.readText() }.getOrDefault(""))?.key }.toSet()

    /** Whether a recording for this meeting may start now: not while one is running, not when one was already recorded or is waiting to upload. */
    fun gate(context: Context, prepared: PreparedMeeting): RecordingGate =
        recordingGate(prepared, MeetingReminderScheduler.recordedMeetings(context), pendingKeys(context), recording, plan?.key)
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
    private var startedElapsed = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        recorder = MeetingRecorder(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            START -> begin(intent.getStringExtra(PLAN_KEY)?.let { RecordingPlan(it, intent.getStringExtra(PLAN_TITLE), intent.getLongExtra(PLAN_START, 0L)) })
            STOP -> finish()
            UPLOAD -> upload()
            else -> if (!RecordingController.recording) stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun begin(plan: RecordingPlan?) {
        if (RecordingController.recording) return
        // A second tap or a second notification for a meeting that is already recorded, or waiting to upload, must not make a second recording.
        if (plan != null && RecordingController.gate(this, PreparedMeeting(plan.key, plan.title, plan.startMs)) != RecordingGate.Ready) { stopSelf(); return }
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
        startedElapsed = SystemClock.elapsedRealtime()
        RecordingController.plan = plan
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
        val seconds = (SystemClock.elapsedRealtime() - startedElapsed) / 1000
        when (shortRecordingVerdict(seconds)) {
            ShortVerdict.Discard -> {
                clip.delete(); RecordingController.plan = null
                RecordingController.error = discardedShortRecordingMessage(seconds)
                leaveForeground(); stopSelf(); return
            }
            ShortVerdict.Ask -> {
                // Held in its own folder, not pending-meetings, so no retry can upload it before the owner has answered.
                val held = File(RecordingController.heldDir(this), clip.name)
                if (!clip.renameTo(held)) { clip.copyTo(held, overwrite = true); clip.delete() }
                keepPlan(held)
                RecordingController.hold(held, seconds)
                leaveForeground(); notifyHeld(seconds); stopSelf(); return
            }
            ShortVerdict.Keep -> {}
        }
        val pending = File(RecordingController.pendingDir(this), clip.name)
        if (!clip.renameTo(pending)) { clip.copyTo(pending, overwrite = true); clip.delete() }
        keepPlan(pending)
        upload()
    }

    /** Uploads whatever waits in pending-meetings, in the foreground so the work is not cut short. */
    private fun upload() {
        enterForeground("Uploading meeting…", stoppable = false)
        RecordingController.uploading = true
        scope.launch {
            val failure = uploadPending(applicationContext)
            RecordingController.uploading = false
            RecordingController.error = failure?.let { "Upload failed ($it). The recording is kept on this phone and will retry from the Meetings tab." }
            leaveForeground(); stopSelf()
        }
    }

    /** Stopped from the notification with the app away: the question waits in the app, so say so. */
    private fun notifyHeld(seconds: Long) {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("Reachy")
            .setContentText("Recording was only $seconds seconds. Open Reachy to keep or delete it.").setContentIntent(open).setAutoCancel(true).build()
        runCatching { getSystemService(NotificationManager::class.java).notify(HELD_NOTIFICATION_ID, n) }
    }

    override fun onDestroy() {
        // Killed or swiped away mid-recording: keep what was captured rather than losing it.
        if (RecordingController.recording) {
            RecordingController.recording = false
            recorder.stop()?.let { val kept = File(RecordingController.pendingDir(this), it.name); it.renameTo(kept); keepPlan(kept) }
        }
        releaseWakeLock()
        scope.cancel()
        super.onDestroy()
    }

    /** Writes the calendar meeting beside the clip (so the title and identity survive until the upload) and clears it from the live state. */
    private fun keepPlan(clip: File) {
        RecordingController.plan?.let { runCatching { RecordingController.planFile(clip).writeText(encodePlan(it)) } }
        RecordingController.plan = null
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
        const val UPLOAD = "app.reachy.companion.RECORD_UPLOAD_HELD"
        const val PLAN_KEY = "plan_key"
        const val PLAN_TITLE = "plan_title"
        const val PLAN_START = "plan_start"
        private const val CHANNEL = "recording"
        private const val NOTIFICATION_ID = 7
        private const val HELD_NOTIFICATION_ID = 8
    }
}

/** Uploads every clip waiting in pending-meetings; returns the first failure message, or null when all went up. */
suspend fun uploadPending(context: Context): String? {
    val prefs = Prefs(context)
    if (prefs.baseUrl.isBlank()) return "not signed in"
    val api = ReachyApi(prefs.baseUrl, PersistentCookieJar({ prefs.cookies }, { prefs.cookies = it }))
    for (clip in RecordingController.pendingDir(context).listFiles().orEmpty().filter { it.name.endsWith(".m4a") }.sortedBy { it.name }) {
        val stamp = clip.name.removePrefix("recording-").removeSuffix(".m4a").toLongOrNull() ?: clip.lastModified()
        val plan = RecordingController.planFile(clip).takeIf { it.exists() }?.let { decodePlan(runCatching { it.readText() }.getOrDefault("")) }
        val title = plan?.let { recordingTitle(PreparedMeeting(it.key, it.title, it.startMs)) } ?: ("Meeting " + SimpleDateFormat("d MMM HH:mm", Locale.getDefault()).format(Date(stamp)))
        try {
            val meeting = api.uploadMeeting(title, clip)
            clip.delete()
            RecordingController.planFile(clip).delete()
            if (plan != null) {
                // The calendar's title is the owner's, so it is set as theirs (an automatic title does not replace it); the time goes in the description. Best effort: the upload already succeeded.
                runCatching { api.renameMeeting(meeting.id, title, scheduledText(plan.startMs)) }
                MeetingReminderScheduler.noteRecorded(context, plan.key, meeting.id)
            }
            RecordingController.uploadedCount++
        } catch (e: Exception) {
            return e.message ?: "network error"
        }
    }
    return null
}
