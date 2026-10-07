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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import app.reachy.companion.data.DeepReviewJob
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.Prefs
import app.reachy.companion.data.ReachyApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** What the UI sees of a deep review: the job as last polled. The service owns the polling. */
object DeepReviewController {
    var job by mutableStateOf<DeepReviewJob?>(null); internal set

    /** True while Reachy's standard model is unloaded or reloading. */
    val reachyUnavailable get() = job?.let { !it.finished || it.reachyUnavailable } == true

    fun follow(context: Context, id: String) {
        ContextCompat.startForegroundService(
            context, Intent(context, DeepReviewService::class.java).putExtra(DeepReviewService.JOB_ID, id),
        )
    }
}

fun apiFor(context: Context): ReachyApi? {
    val prefs = Prefs(context)
    if (prefs.baseUrl.isBlank()) return null
    return ReachyApi(prefs.baseUrl, PersistentCookieJar({ prefs.cookies }, { prefs.cookies = it }))
}

/**
 * Follows a deep review until Reachy is back (or needs attention), so the "Reachy is available again" notification
 * arrives even if the app is in the background. Polls the hub; a flaky connection (for example Tailscale dropping)
 * just retries.
 */
class DeepReviewService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var running: String? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val id = intent?.getStringExtra(JOB_ID)
        if (id == null || id == running) return START_NOT_STICKY
        running = id
        enterForeground("Deep processing in progress. Reachy is unavailable.")
        scope.launch { follow(id) }
        return START_NOT_STICKY
    }

    private suspend fun follow(id: String) {
        val api = apiFor(this)
        var failures = 0
        while (api != null && failures < 450) { // about 30 minutes of trying
            try {
                val job = api.deepJob(id)
                DeepReviewController.job = job
                failures = 0
                if (job.finished) { announce(job); break }
                updateOngoing(job)
            } catch (e: Exception) { failures++ }
            delay(4000)
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun announce(job: DeepReviewJob) {
        val title = job.meetingTitle.ifBlank { "your meeting" }
        val what = when (job.task) { "summary" -> "deep summary"; "minutes" -> "deep minutes"; else -> "deep review" }
        val (heading, text) = when {
            !job.reachyOnline -> "Reachy needs attention" to "The standard model could not be reloaded after the $what of “$title”. Manual recovery is needed on the homelab."
            job.status == "failed" -> "Reachy is available again" to "The $what of “$title” did not complete (${job.error ?: "unknown error"}), but Reachy is back online."
            else -> "Reachy is available again" to "The $what of “$title” is complete. Open Meetings to see it."
        }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(STATUS_CHANNEL, "Reachy status", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)
        manager.notify(
            NOTIFICATION_DONE,
            NotificationCompat.Builder(this, STATUS_CHANNEL).setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle(heading).setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setContentIntent(open).setAutoCancel(true).build(),
        )
    }

    private fun updateOngoing(job: DeepReviewJob) {
        val text = if (job.stage.isBlank()) "Deep review in progress. Reachy is unavailable." else "${job.stage}. Reachy is unavailable."
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ONGOING, ongoing(text))
    }

    private fun ongoing(text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(PROGRESS_CHANNEL, "Deep review", NotificationManager.IMPORTANCE_LOW))
        return NotificationCompat.Builder(this, PROGRESS_CHANNEL).setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("Reachy deep review").setContentText(text).setOngoing(true).setOnlyAlertOnce(true).build()
    }

    private fun enterForeground(text: String) {
        val notification = ongoing(text)
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION_ONGOING, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(NOTIFICATION_ONGOING, notification)
    }

    override fun onDestroy() { scope.cancel(); super.onDestroy() }

    companion object {
        const val JOB_ID = "job_id"
        private const val PROGRESS_CHANNEL = "deep_review"
        private const val STATUS_CHANNEL = "reachy_status"
        private const val NOTIFICATION_ONGOING = 8
        private const val NOTIFICATION_DONE = 9
    }
}
