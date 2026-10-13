package app.reachy.companion

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import app.reachy.companion.data.MeetingReminder
import app.reachy.companion.data.PreparedMeeting
import app.reachy.companion.data.Prefs
import app.reachy.companion.data.ReminderIssue
import app.reachy.companion.data.ReminderSet
import app.reachy.companion.data.firedKey
import app.reachy.companion.data.millis
import app.reachy.companion.data.planReminders
import app.reachy.companion.data.preparedFrom
import app.reachy.companion.data.pruneFired
import app.reachy.companion.data.reconcile
import app.reachy.companion.data.reminderIssues
import app.reachy.companion.data.reminderText
import app.reachy.companion.data.reminderTitle
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

/*
 * Meeting recording reminders on the phone (ADR 0035). The hub supplies a bounded set; each reminder is scheduled here with AlarmManager so it arrives with no network and
 * survives a restart. A reminder is an ordinary notification in its own category, not an alarm: no looping sound, no alarm stream, no foreground service. "Start recording" only
 * opens the recorder with the meeting prepared; it never starts the microphone, and nothing is uploaded from here.
 */

/** What the phone keeps between runs, in app-private storage (no backup, removed on sign-out): the hub's last set (titles and times), what is armed, what was shown, and which meetings have a recording. */
@Serializable
data class ReminderState(
    val set: ReminderSet? = null,
    val armed: Map<String, Long> = emptyMap(),
    val fired: Set<String> = emptySet(),
    /** Calendar occurrence key to the meeting id its recording became, so a second "Start recording" opens that meeting instead of making another. */
    val recorded: Map<String, String> = emptyMap(),
    val syncFailed: Boolean = false,
    val lastSyncAtMs: Long = 0L,
    val blockedAtMs: Long = 0L,
)

object ReminderStore {
    private val json = Json { ignoreUnknownKeys = true }
    private var cache: ReminderState? = null

    private fun file(context: Context) = File(context.filesDir, "meeting-reminders.json")

    @Synchronized fun read(context: Context): ReminderState =
        cache ?: (runCatching { json.decodeFromString<ReminderState>(file(context).readText()) }.getOrNull() ?: ReminderState()).also { cache = it }

    @Synchronized fun update(context: Context, change: (ReminderState) -> ReminderState): ReminderState {
        val next = change(read(context))
        cache = next
        val target = file(context)
        val temp = File(target.parentFile, target.name + ".tmp")
        runCatching { temp.writeText(json.encodeToString(next)); if (!temp.renameTo(target)) { target.writeText(temp.readText()); temp.delete() } }
            .onFailure { Log.w("MeetingReminders", "could not save reminder state") }
        return next
    }

}

object MeetingReminderScheduler {
    const val CHANNEL = "meeting-reminders"
    const val FIRE = "app.reachy.companion.MEETING_REMINDER_FIRE"
    const val DISMISS = "app.reachy.companion.MEETING_REMINDER_DISMISS"
    const val PREPARE = "app.reachy.companion.MEETING_PREPARE_RECORDING"
    const val KEY = "meeting_key"
    const val TITLE = "meeting_title"
    const val START = "meeting_start"
    const val NOTIFICATION = "meeting_notification"
    private const val TAG = "MeetingReminders"

    /** Fetches the hub's current set and arms it. A failed fetch (offline) leaves what is already armed in place. */
    suspend fun syncFromHub(context: Context): Boolean {
        val prefs = Prefs(context)
        if (!prefs.meetingReminders) { disarm(context); return true }
        val api = apiFor(context) ?: return false
        return try {
            apply(context, api.meetingReminders())
            AlarmScheduler.ensureBackgroundSync(context)
            true
        } catch (e: Exception) {
            ReminderStore.update(context) { it.copy(syncFailed = true) }
            false
        }
    }

    /** Stores [set] and reconciles the armed alarms with it: new or moved reminders are scheduled, cancelled or removed ones are cancelled. */
    fun apply(context: Context, set: ReminderSet, nowMs: Long = System.currentTimeMillis()) {
        val state = ReminderStore.update(context) { it.copy(set = set, fired = pruneFired(it.fired, nowMs), syncFailed = false, lastSyncAtMs = nowMs) }
        arm(context, state, nowMs, rearmAll = false)
    }

    /** After a restart (or an app update, or a clock change) every alarm is gone: arm again from what was last stored, which needs no network. */
    fun restore(context: Context, nowMs: Long = System.currentTimeMillis()) {
        if (!Prefs(context).meetingReminders) return
        val state = ReminderStore.update(context) { it.copy(fired = pruneFired(it.fired, nowMs)) }
        if (state.set != null) arm(context, state, nowMs, rearmAll = true)
    }

    private fun arm(context: Context, state: ReminderState, nowMs: Long, rearmAll: Boolean) {
        val set = state.set ?: return
        val manager = context.getSystemService(AlarmManager::class.java)
        val planned = planReminders(set, nowMs, state.fired)
        val change = reconcile(state.armed, planned, rearmAll)
        for (key in change.cancel) manager.cancel(fireIntent(context, key))
        val exact = exactAllowed(context)
        for (item in change.schedule) {
            val intent = fireIntent(context, item.key)
            try {
                if (exact) manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, item.fireAtMs, intent)
                else manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, item.fireAtMs, intent)
            } catch (e: SecurityException) {
                // The exact-alarm permission was withdrawn between the check and the call: an approximate alarm is better than none.
                Log.w(TAG, "exact alarm refused, using an approximate one")
                runCatching { manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, item.fireAtMs, intent) }
            }
        }
        ReminderStore.update(context) { it.copy(armed = planned.associate { p -> p.key to p.fireAtMs }) }
    }

    /** Cancels every armed alarm and shown notification and forgets the stored calendar data (sign-out, or the owner turning reminders off). */
    fun disarm(context: Context) {
        val manager = context.getSystemService(AlarmManager::class.java)
        val shown = NotificationManagerCompat.from(context)
        for (key in ReminderStore.read(context).armed.keys) { manager.cancel(fireIntent(context, key)); shown.cancel(notificationId(key)) }
        // The calendar titles and times go; which meetings already have a recording stays, so a reminder turned on again cannot make a second record.
        ReminderStore.update(context) { ReminderState(recorded = it.recorded) }
    }

    fun exactAllowed(context: Context): Boolean =
        Build.VERSION.SDK_INT < 31 || context.getSystemService(AlarmManager::class.java).canScheduleExactAlarms()

    /** What is wrong with delivery right now, worst first; empty means reminders should arrive. */
    fun issues(context: Context): List<ReminderIssue> {
        val manager = context.getSystemService(NotificationManager::class.java)
        val channel = if (Build.VERSION.SDK_INT >= 26) manager.getNotificationChannel(CHANNEL) else null
        val state = ReminderStore.read(context)
        return reminderIssues(
            enabled = Prefs(context).meetingReminders, notificationsAllowed = NotificationManagerCompat.from(context).areNotificationsEnabled(),
            channelAllowed = channel == null || channel.importance != NotificationManager.IMPORTANCE_NONE, exactAllowed = exactAllowed(context),
            set = state.set, lastSyncFailed = state.syncFailed,
        )
    }

    fun notificationId(key: String) = key.hashCode()

    private fun fireIntent(context: Context, key: String): PendingIntent {
        val intent = Intent(context, MeetingReminderReceiver::class.java).setAction(FIRE).setData(Uri.parse("reachy-meeting://reminder/" + Uri.encode(key)))
        return PendingIntent.getBroadcast(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun dismissIntent(context: Context, key: String): PendingIntent {
        val intent = Intent(context, MeetingReminderReceiver::class.java).setAction(DISMISS).setData(Uri.parse("reachy-meeting://dismiss/" + Uri.encode(key)))
            .putExtra(NOTIFICATION, notificationId(key))
        return PendingIntent.getBroadcast(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    /** Opens the app on the Meetings tab with this meeting prepared. It does not start the microphone: the owner taps Record. */
    private fun prepareIntent(context: Context, reminder: MeetingReminder, startMs: Long): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).setAction(PREPARE).setData(Uri.parse("reachy-meeting://prepare/" + Uri.encode(reminder.eventKey)))
            .putExtra(KEY, reminder.eventKey).putExtra(TITLE, reminder.title).putExtra(START, startMs).putExtra(NOTIFICATION, notificationId(reminder.eventKey))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    /** Shows the reminder for [key] if it is still wanted. Returns false when it was not shown (changed, started, already shown, or notifications are blocked). */
    fun show(context: Context, key: String, nowMs: Long = System.currentTimeMillis()): Boolean {
        val state = ReminderStore.read(context)
        val reminder = state.set?.reminders?.firstOrNull { it.eventKey == key } ?: return false  // the calendar changed since this was armed
        val startMs = runCatching { millis(reminder.start) }.getOrNull() ?: return false
        if (startMs <= nowMs || firedKey(key, startMs) in state.fired || state.armed[key] == null) return false
        val manager = context.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26 && manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "Meeting reminders", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "A heads-up before a meeting, with a shortcut to the recorder. Not an alarm."
            })
        }
        val allowed = NotificationManagerCompat.from(context).areNotificationsEnabled() &&
            (Build.VERSION.SDK_INT < 26 || manager.getNotificationChannel(CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE)
        if (!allowed) {
            ReminderStore.update(context) { it.copy(blockedAtMs = nowMs) }  // shown to the owner as a problem; nothing is lost silently
            return false
        }
        val open = prepareIntent(context, reminder, startMs)
        val public = NotificationCompat.Builder(context, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_my_calendar).setContentTitle("Meeting reminder").build()
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_my_calendar)
            .setContentTitle(reminderTitle(reminder.title)).setContentText(reminderText(startMs, nowMs))
            .setCategory(Notification.CATEGORY_EVENT).setPriority(NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(public)  // the title stays off the lock screen
            .setWhen(startMs).setShowWhen(true).setAutoCancel(true).setOnlyAlertOnce(true)
            .setTimeoutAfter(maxOf(60_000L, startMs - nowMs + 5 * 60_000L))
            .setContentIntent(open)
            .addAction(0, "Start recording", open)
            .addAction(0, "Dismiss", dismissIntent(context, key))
            .build()
        manager.notify(notificationId(key), notification)
        ReminderStore.update(context) { it.copy(fired = it.fired + firedKey(key, startMs)) }
        return true
    }

    fun dismiss(context: Context, key: String) {
        NotificationManagerCompat.from(context).cancel(notificationId(key))
        val startMs = ReminderStore.read(context).set?.reminders?.firstOrNull { it.eventKey == key }?.start?.let { runCatching { millis(it) }.getOrNull() } ?: return
        ReminderStore.update(context) { it.copy(fired = it.fired + firedKey(key, startMs)) }
    }

    /** What an intent from a notification asks the app to prepare, or null when it is not acceptable. */
    fun preparedFromIntent(intent: Intent?, nowMs: Long = System.currentTimeMillis()): PreparedMeeting? {
        if (intent?.action != PREPARE) return null
        return preparedFrom(intent.getStringExtra(KEY), intent.getStringExtra(TITLE), intent.getLongExtra(START, 0L), nowMs)
    }

    fun recordedMeetings(context: Context): Map<String, String> = ReminderStore.read(context).recorded

    fun noteRecorded(context: Context, key: String, meetingId: String) {
        ReminderStore.update(context) { it.copy(recorded = it.recorded + (key to meetingId)) }
    }
}

/** Delivers a reminder when its alarm fires, and handles Dismiss. Works with no network: everything it needs is in [ReminderStore]. */
class MeetingReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val key = intent.data?.lastPathSegment ?: return
        when (intent.action) {
            MeetingReminderScheduler.FIRE -> MeetingReminderScheduler.show(context, key)
            MeetingReminderScheduler.DISMISS -> MeetingReminderScheduler.dismiss(context, key)
        }
    }
}

/** Arms the stored reminders again after a restart, an app update or a clock change, which all clear AlarmManager. Local only; the hub is asked afterwards. */
class ReminderRestoreReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pending = goAsync()
        val app = context.applicationContext
        CoroutineScope(Dispatchers.Default).launch {
            try {
                MeetingReminderScheduler.restore(app)
                MeetingReminderScheduler.syncFromHub(app)
            } finally { pending.finish() }
        }
    }
}
