package app.reachy.companion.data

import android.content.Context

/** Connection details only: the hub address, the owner's username and the session cookie. No keys, transcripts or notes. */
class Prefs(context: Context) {
    private val store = context.getSharedPreferences("reachy", Context.MODE_PRIVATE)
    var baseUrl: String
        get() = store.getString("base_url", "") ?: ""
        set(value) = store.edit().putString("base_url", value).apply()
    var username: String
        get() = store.getString("username", "") ?: ""
        set(value) = store.edit().putString("username", value).apply()
    var cookies: String?
        get() = store.getString("cookies", null)
        set(value) = store.edit().putString("cookies", value).apply()
    /** Ring an alarm on this phone when Reachy cannot (offline, nobody detected, playback failed). */
    var phoneAlarms: Boolean
        get() = store.getBoolean("phone_alarms", true)
        set(value) = store.edit().putBoolean("phone_alarms", value).apply()
    var askedAlarmNotifications: Boolean
        get() = store.getBoolean("asked_alarm_notifications", false)
        set(value) = store.edit().putBoolean("asked_alarm_notifications", value).apply()
    /** Ids of the alarms scheduled on this phone, so ones that were changed or deleted can be cancelled. */
    var scheduledAlarmIds: Set<String>
        get() = store.getStringSet("scheduled_alarm_ids", emptySet()) ?: emptySet()
        set(value) = store.edit().putStringSet("scheduled_alarm_ids", value).apply()
    var speakReplies: Boolean
        get() = store.getBoolean("speak_replies", true)
        set(value) = store.edit().putBoolean("speak_replies", value).apply()
}
