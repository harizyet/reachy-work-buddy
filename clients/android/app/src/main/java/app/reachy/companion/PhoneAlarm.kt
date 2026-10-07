package app.reachy.companion

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.util.Log
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import app.reachy.companion.data.Alarm
import app.reachy.companion.data.Prefs
import app.reachy.companion.data.Verdict
import app.reachy.companion.data.dueMillis
import app.reachy.companion.data.isOn
import app.reachy.companion.data.phoneVerdict
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Backup for Reachy's own alarm: the phone keeps a clock alarm for each of the owner's alarms and, when one comes due, asks
 * the hub what Reachy did with it. If Reachy was offline, found nobody in the room or could not play it, the phone rings.
 */
object AlarmScheduler {
    /** Schedules a phone alarm for every alarm that is switched on and still to come, and cancels ones that no longer are. */
    fun sync(context: Context, alarms: List<Alarm>) {
        val prefs = Prefs(context)
        val manager = context.getSystemService(AlarmManager::class.java)
        val now = System.currentTimeMillis()
        val wanted = if (prefs.phoneAlarms) alarms.filter { isOn(it) && dueMillis(it) > now } else emptyList()
        for (id in prefs.scheduledAlarmIds - wanted.map { it.id }.toSet()) manager.cancel(fire(context, id, 0, "", 100))
        for (alarm in wanted) {
            val due = dueMillis(alarm)
            val show = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            // Without permission to set exact alarms the phone just has no backup; it must not break loading the alarm list.
            try { manager.setAlarmClock(AlarmManager.AlarmClockInfo(due, show), fire(context, alarm.id, due, alarm.label, alarm.volume)) }
            catch (e: SecurityException) { Log.w("PhoneAlarm", "cannot schedule exact alarms: ${e.message}") }
        }
        prefs.scheduledAlarmIds = wanted.map { it.id }.toSet()
        scheduleBackgroundSync(context, prefs.phoneAlarms)
    }

    /**
     * Alarms set elsewhere (Telegram, the robot, the web) only reach the phone when it asks, so it asks about every 15 minutes
     * in the background as well as whenever the app opens, rings, or the phone restarts. The job survives a closed app and a reboot.
     */
    private fun scheduleBackgroundSync(context: Context, on: Boolean) {
        val scheduler = context.getSystemService(JobScheduler::class.java)
        if (!on) { scheduler.cancel(SYNC_JOB_ID); return }
        if (scheduler.getPendingJob(SYNC_JOB_ID) != null) return
        scheduler.schedule(
            JobInfo.Builder(SYNC_JOB_ID, ComponentName(context, AlarmSyncJob::class.java))
                .setPeriodic(15 * 60 * 1000L).setPersisted(true).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).build(),
        )
    }

    private const val SYNC_JOB_ID = 4101

    /** Fetches the alarms from the hub and schedules them; used when the phone starts up. */
    suspend fun syncFromHub(context: Context) {
        val api = apiFor(context) ?: return
        try { sync(context, api.alarms()) } catch (e: Exception) { /* offline: the next time the app opens will do it */ }
    }

    private fun fire(context: Context, id: String, due: Long, label: String, volume: Int): PendingIntent {
        val intent = Intent(context, AlarmReceiver::class.java)
            .putExtra(AlarmService.ID, id).putExtra(AlarmService.DUE, due).putExtra(AlarmService.LABEL, label).putExtra(AlarmService.VOLUME, volume)
        return PendingIntent.getBroadcast(context, id.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
}

/** The 15-minute background sync. */
class AlarmSyncJob : JobService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    override fun onStartJob(params: JobParameters): Boolean {
        scope.launch { try { AlarmScheduler.syncFromHub(applicationContext) } finally { jobFinished(params, false) } }
        return true
    }
    override fun onStopJob(params: JobParameters): Boolean { scope.cancel(); return true }
}

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val check = Intent(context, AlarmService::class.java).setAction(AlarmService.CHECK).putExtras(intent)
        ContextCompat.startForegroundService(context, check)
    }
}

/** Re-schedules the phone alarms after a restart, which clears them. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val pending = goAsync()
        CoroutineScope(Dispatchers.Default).launch { try { AlarmScheduler.syncFromHub(context.applicationContext) } finally { pending.finish() } }
    }
}

class AlarmService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var player: MediaPlayer? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            CHECK -> {
                val id = intent.getStringExtra(ID) ?: return START_NOT_STICKY
                val label = intent.getStringExtra(LABEL).orEmpty()
                startForeground("Alarm: $label", "Checking whether Reachy played it…", ringing = false)
                wakeLock = (getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "reachy:alarm").apply { acquire(6 * 60 * 1000L) }
                scope.launch { check(id, intent.getLongExtra(DUE, 0), label, intent.getIntExtra(VOLUME, 100)) }
            }
            STOP -> { stopRinging(); finish() }
        }
        return START_NOT_STICKY
    }

    /** Waits for the hub to say what Reachy did with this ring; no answer in time means Reachy did not, so the phone rings. */
    private suspend fun check(id: String, due: Long, label: String, volume: Int) {
        val api = apiFor(this)
        val deadline = System.currentTimeMillis() + WAIT_MS
        var why: String? = null
        var unreachable = 0
        while (why == null && System.currentTimeMillis() < deadline) {
            try {
                val alarms = requireNotNull(api).alarms()
                unreachable = 0
                when (val verdict = phoneVerdict(alarms.firstOrNull { it.id == id }, due)) {
                    is Verdict.Done -> { AlarmScheduler.sync(this, alarms); finish(); return }
                    is Verdict.Ring -> why = verdict.why
                    is Verdict.Wait -> delay(POLL_MS)
                }
            } catch (e: Exception) {
                // Reachy's hub cannot be reached, so Reachy cannot have played it: do not wait the full time to ring.
                if (++unreachable >= UNREACHABLE_TRIES) why = "Reachy cannot be reached" else delay(POLL_MS)
            }
        }
        ring(label, why ?: "Reachy did not answer", volume)
        // Schedule the next occurrence of a repeating alarm while this one rings.
        api?.let { runCatching { AlarmScheduler.sync(this, it.alarms()) } }
    }

    private fun ring(label: String, why: String, volume: Int) {
        startForeground("Alarm: $label", "$why. Tap Stop to silence.", ringing = true)
        val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
        player = runCatching {
            MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                setDataSource(this@AlarmService, uri)
                isLooping = true
                setVolume((volume / 100f).coerceIn(0.1f, 1f), (volume / 100f).coerceIn(0.1f, 1f))
                prepare(); start()
            }
        }.getOrNull()
        getSystemService(Vibrator::class.java)?.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 600, 400), 0))
        scope.launch { delay(RING_MS); stopRinging(); finish() }
    }

    private fun stopRinging() {
        player?.runCatching { stop() }; player?.release(); player = null
        getSystemService(Vibrator::class.java)?.cancel()
    }

    private fun finish() {
        wakeLock?.takeIf { it.isHeld }?.release(); wakeLock = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() { stopRinging(); wakeLock?.takeIf { it.isHeld }?.release(); scope.cancel(); super.onDestroy() }

    private fun startForeground(title: String, text: String, ringing: Boolean) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Phone alarm", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val builder = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm).setContentTitle(title).setContentText(text)
            .setOngoing(true).setOnlyAlertOnce(true).setContentIntent(open).setCategory(Notification.CATEGORY_ALARM)
        if (ringing) builder.addAction(0, "Stop", PendingIntent.getService(this, 2, Intent(this, AlarmService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE))
        // Both types from the start: a service started by the alarm clock may not be allowed to add one later.
        val type = ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK or ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION_ID, builder.build(), type) else startForeground(NOTIFICATION_ID, builder.build())
    }

    companion object {
        const val CHECK = "app.reachy.companion.ALARM_CHECK"
        const val STOP = "app.reachy.companion.ALARM_STOP"
        const val ID = "alarm_id"
        const val DUE = "alarm_due"
        const val LABEL = "alarm_label"
        const val VOLUME = "alarm_volume"
        private const val CHANNEL = "phone-alarm"
        private const val NOTIFICATION_ID = 9
        // A sweep and a minute of playing on the robot can take about two minutes before the hub records the result.
        private const val WAIT_MS = 180_000L
        private const val POLL_MS = 4_000L
        private const val UNREACHABLE_TRIES = 3
        private const val RING_MS = 5 * 60_000L
    }
}
