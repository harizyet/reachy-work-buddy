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
    var speakReplies: Boolean
        get() = store.getBoolean("speak_replies", true)
        set(value) = store.edit().putBoolean("speak_replies", value).apply()
}
