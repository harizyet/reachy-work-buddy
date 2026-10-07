package app.reachy.companion

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.reachy.companion.data.ApiException
import app.reachy.companion.data.Meeting
import app.reachy.companion.data.Note
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.Prefs
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.Task
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File

data class ChatLine(
    val fromOwner: Boolean, val text: String, val failed: Boolean = false, val context: String? = null,
    val sources: List<app.reachy.companion.data.WebSource> = emptyList(), val searchFailed: Boolean = false,
)

enum class Session { Checking, SignedOut, SignedIn }

class AppViewModel(app: Application) : AndroidViewModel(app) {
    val prefs = Prefs(app)
    private val cookieJar = PersistentCookieJar({ prefs.cookies }, { prefs.cookies = it })
    private var api = ReachyApi(prefs.baseUrl.ifBlank { "http://localhost" }, cookieJar)
    private var userId: String? = null
    val player = MeetingPlayer(File(app.cacheDir, "meeting-audio")) { id, file -> api.downloadAudio(id, file) }
    private var chatId: String? = null

    var session by mutableStateOf(Session.Checking); private set
    var loginError by mutableStateOf<String?>(null); private set
    var loginBusy by mutableStateOf(false); private set

    val chat = mutableStateListOf<ChatLine>()
    var sending by mutableStateOf(false); private set
    var chatStatus by mutableStateOf<String?>(null)
    var lastReply by mutableStateOf<String?>(null); private set
    /** Counts replies, so the Talk screen can tell a new reply from one it already read aloud (it is rebuilt on every tab change). */
    var replySeq by mutableIntStateOf(0); private set
    var spokenSeq = 0

    val tasks = mutableStateListOf<Task>()
    val notes = mutableStateListOf<Note>()
    val meetings = mutableStateListOf<Meeting>()
    var openMeeting by mutableStateOf<Meeting?>(null); private set
    var listError by mutableStateOf<String?>(null)
    val uploading get() = RecordingController.uploading
    private var meetingPoll: Job? = null

    // Recording lives in RecordingService so it survives tab switches, standby and other apps.
    val recording get() = RecordingController.recording
    val recordingStartedAt get() = RecordingController.startedAt
    val recordError get() = RecordingController.error

    fun startRecording() = RecordingController.start(getApplication())
    fun stopRecording() = RecordingController.stop(getApplication())

    /** Retries clips whose upload failed earlier, then refreshes the list. */
    fun retryPendingUploads() {
        viewModelScope.launch {
            if (RecordingController.recording || RecordingController.uploading) return@launch
            RecordingController.uploading = true
            try { RecordingController.error = uploadPending(getApplication())?.let { "Upload failed ($it). The recording is kept on this phone." } } finally { RecordingController.uploading = false }
        }
    }

    init { viewModelScope.launch { resume() } }

    private suspend fun resume() {
        if (prefs.baseUrl.isBlank()) { session = Session.SignedOut; return }
        session = try { api.me(); userId = api.userId(); Session.SignedIn } catch (e: Exception) { Session.SignedOut }
        if (session == Session.SignedIn) resumeDeepReview()
    }

    fun signIn(url: String, username: String, password: String) {
        viewModelScope.launch {
            loginBusy = true; loginError = null
            try {
                prefs.baseUrl = app.reachy.companion.data.normalizeBaseUrl(url)
                prefs.username = username
                cookieJar.clear()
                api = ReachyApi(prefs.baseUrl, cookieJar)
                api.login(username, password)
                userId = api.userId()
                chat.clear(); chatId = null
                session = Session.SignedIn
                resumeDeepReview()
            } catch (e: ApiException) {
                loginError = if (e.unauthorized) "Wrong username or password" else e.message
            } catch (e: Exception) {
                loginError = "Could not reach ${prefs.baseUrl}. Check the address and that you are on the home network or VPN."
            } finally { loginBusy = false }
        }
    }

    fun signOut() {
        viewModelScope.launch { api.logout(); chat.clear(); tasks.clear(); notes.clear(); meetings.clear(); chatId = null; if (recording) stopRecording(); DeepReviewController.job = null; session = Session.SignedOut }
    }

    private fun failed(e: Exception): String {
        if (e is ApiException && e.unauthorized) { session = Session.SignedOut; return "Please sign in again" }
        return e.message ?: "Something went wrong"
    }

    fun send(text: String, spoken: Boolean = false) {
        val message = text.trim()
        val user = userId
        if (message.isEmpty() || sending || user == null) return
        sending = true; chatStatus = null
        val line = ChatLine(true, message)
        chat.add(line)
        viewModelScope.launch {
            try {
                if (!spoken && chatId == null) chatId = api.createChat(user, message).id
                val reply = api.send(user, message, spoken, chatId, contextMeeting?.first, forceFrontier = contextCloud && contextMeeting != null)
                chat.add(ChatLine(false, reply.reply, context = reply.contextMeeting, sources = reply.webSearch?.results.orEmpty(), searchFailed = reply.webSearch?.failed == true)); lastReply = reply.reply; replySeq++
            } catch (e: Exception) {
                // Never retried automatically: the hub may already have acted on the message.
                chat[chat.lastIndex] = line.copy(failed = true)
                chatStatus = failed(e).let { "$it. The message may have been processed; check before sending it again." }
            } finally { sending = false }
        }
    }

    /** A meeting attached to the conversation (id, title): questions are answered from it, locally. */
    var contextMeeting by mutableStateOf<Pair<String, String>?>(null)

    /** Answer context questions with the cloud model instead (the meeting text is sent to the provider). */
    var contextCloud by mutableStateOf(false)

    fun useAsContext(meeting: Meeting) { contextMeeting = meeting.id to meeting.title; contextCloud = false }
    fun clearContext() { contextMeeting = null; contextCloud = false }

    fun newChat() { chat.clear(); chatId = null; chatStatus = null }

    private fun load(block: suspend () -> Unit) {
        viewModelScope.launch { try { block(); listError = null } catch (e: Exception) { listError = failed(e) } }
    }

    fun loadTasks() = load { tasks.replace(api.tasks().sortedBy { it.done }) }
    fun addTask(text: String) = load { api.addTask(text.trim()); loadTasksNow() }
    fun toggleTask(task: Task) = load { api.setTaskDone(task.id, !task.done); loadTasksNow() }
    fun deleteTask(task: Task) = load { api.deleteTask(task.id); loadTasksNow() }
    private suspend fun loadTasksNow() { tasks.replace(api.tasks().sortedBy { it.done }) }

    val reminders = mutableStateListOf<app.reachy.companion.data.Reminder>()
    private suspend fun loadRemindersNow() { reminders.replace(api.reminders()) }
    fun loadReminders() = load { loadRemindersNow(); loadTasksNow() }
    fun addReminder(text: String, dueAtIso: String) = load { api.addReminder(text.trim(), dueAtIso); loadRemindersNow() }
    fun completeReminder(id: String) = load { api.completeReminder(id); loadRemindersNow() }
    fun deleteReminder(id: String) = load { api.deleteReminder(id); loadRemindersNow() }
    fun editTask(task: Task, text: String) = load { api.editTask(task.id, text.trim()); loadTasksNow() }

    val alarms = mutableStateListOf<app.reachy.companion.data.Alarm>()
    val stations = mutableStateListOf<app.reachy.companion.data.Station>()
    private suspend fun loadAlarmsNow() {
        alarms.replace(api.alarms()); stations.replace(api.stations())
        AlarmScheduler.sync(getApplication(), alarms.toList())   // the phone keeps its own clock alarm for each of these
    }
    fun loadAlarms() = load { loadAlarmsNow() }
    fun setAlarmOn(id: String, on: Boolean) = load { api.setAlarmEnabled(id, on); loadAlarmsNow() }
    fun deleteAlarm(id: String) = load { api.deleteAlarm(id); loadAlarmsNow() }
    fun saveAlarm(id: String?, label: String, time: String, repeat: List<Int>, stationId: String?, volume: Int) = load {
        if (id == null) api.addAlarm(label.trim(), time, repeat, stationId, volume) else api.updateAlarm(id, label.trim(), time, repeat, stationId, volume)
        loadAlarmsNow()
    }

    fun loadNotes() = load { notes.replace(api.notes()) }
    fun saveNote(id: String?, title: String, body: String, onSaved: (String) -> Unit = {}) = load {
        val saved = api.saveNote(id, title.trim(), body)
        notes.replace(api.notes())
        onSaved(saved.id)
    }
    fun deleteNote(note: Note) = load { api.deleteNote(note.id); notes.replace(api.notes()) }

    fun loadMeetings() = load { meetings.replace(api.meetings().sortedByDescending { it.createdAt }) }

    var suggestions by mutableStateOf<List<app.reachy.companion.data.Suggestion>>(emptyList()); private set
    var suggesting by mutableStateOf(false); private set
    var suggestionNote by mutableStateOf<String?>(null); private set

    var renaming by mutableStateOf(false); private set
    var renameError by mutableStateOf<String?>(null); private set

    /** Saves the owner's title and description for the open meeting; [onDone] runs when it worked. */
    fun renameMeeting(title: String, description: String, onDone: () -> Unit) {
        val id = openMeeting?.id ?: return
        viewModelScope.launch {
            renaming = true; renameError = null
            try {
                openMeeting = api.renameMeeting(id, title.trim(), description.trim())
                meetings.replace(api.meetings().sortedByDescending { it.createdAt })
                onDone()
            } catch (e: Exception) { renameError = failed(e) } finally { renaming = false }
        }
    }

    fun describeMeeting(onDone: () -> Unit) {
        val id = openMeeting?.id ?: return
        viewModelScope.launch {
            renaming = true; renameError = null
            try {
                openMeeting = api.describeMeeting(id)
                meetings.replace(api.meetings().sortedByDescending { it.createdAt })
                onDone()
            } catch (e: Exception) { renameError = failed(e) } finally { renaming = false }
        }
    }

    private fun annotate(call: suspend (String) -> Meeting) {
        val id = openMeeting?.id ?: return
        viewModelScope.launch { try { openMeeting = call(id); listError = null } catch (e: Exception) { listError = failed(e) } }
    }

    val glossary = mutableStateListOf<String>()

    private fun glossaryCall(call: suspend () -> List<String>) {
        viewModelScope.launch { try { glossary.replace(call()); listError = null } catch (e: Exception) { listError = failed(e) } }
    }

    fun loadGlossary() = glossaryCall { api.glossary() }
    fun addGlossaryTerm(term: String) = glossaryCall { api.addGlossaryTerm(term.trim()) }
    fun deleteGlossaryTerm(term: String) = glossaryCall { api.deleteGlossaryTerm(term) }
    fun setKeyTerms(terms: List<String>) = annotate { api.setKeyTerms(it, terms) }

    // ---- deleting, summaries and minutes ------------------------------------------------------------------------
    var generatingKind by mutableStateOf<String?>(null); private set

    fun generateOutput(kind: String, model: String) {
        val id = openMeeting?.id ?: return
        if (generatingKind != null) return
        generatingKind = kind
        viewModelScope.launch {
            try { openMeeting = api.generateOutput(id, kind, model); listError = null }
            catch (e: Exception) { listError = failed(e) } finally { generatingKind = null }
        }
    }

    fun clearOutput(kind: String) = annotate { api.clearOutput(it, kind) }

    fun startDeepOutput(kind: String) {
        val id = openMeeting?.id ?: return
        viewModelScope.launch {
            try {
                val job = api.startDeepOutput(id, kind)
                DeepReviewController.job = job
                DeepReviewController.follow(getApplication(), job.id)
                suggestionNote = "Deep ${kind} started. Reachy is unavailable until it finishes."
                listError = null
            } catch (e: Exception) { listError = failed(e) }
        }
    }

    fun deleteMeeting(id: String) {
        viewModelScope.launch {
            try {
                api.deleteMeeting(id)
                if (openMeeting?.id == id) showMeeting(null)
                if (contextMeeting?.first == id) contextMeeting = null
                meetings.replace(api.meetings().sortedByDescending { it.createdAt }); listError = null
            } catch (e: Exception) { listError = failed(e) }
        }
    }

    fun cancelMeeting(id: String) {
        viewModelScope.launch {
            try { api.cancelMeeting(id); meetings.replace(api.meetings().sortedByDescending { it.createdAt }); listError = null }
            catch (e: Exception) { listError = failed(e) }
        }
    }

    /** Removes every failed or cancelled meeting (and its recording) in one go. */
    fun clearFailedMeetings() {
        viewModelScope.launch {
            try {
                meetings.filter { it.status == "failed" || it.status == "cancelled" }.forEach { api.deleteMeeting(it.id) }
                meetings.replace(api.meetings().sortedByDescending { it.createdAt }); listError = null
            } catch (e: Exception) { listError = failed(e) }
        }
    }

    // ---- deep local review (the larger model; Reachy is unavailable while it runs) ----------------------------
    var deepInfo by mutableStateOf<app.reachy.companion.data.DeepReviewInfo?>(null); private set
    private val deepResults = HashMap<String, app.reachy.companion.data.Suggestions>()
    private var lastRefreshedJob: String? = null

    fun loadDeepInfo() {
        viewModelScope.launch { deepInfo = try { api.deepInfo() } catch (e: Exception) { app.reachy.companion.data.DeepReviewInfo(reason = failed(e)) } }
    }

    fun startDeepReview() {
        val id = openMeeting?.id ?: return
        viewModelScope.launch {
            try {
                val job = api.startDeepReview(id)
                DeepReviewController.job = job
                DeepReviewController.follow(getApplication(), job.id)
                suggestions = emptyList(); suggestionNote = "Deep review started. Reachy is unavailable until it finishes."
                listError = null
            } catch (e: Exception) { listError = failed(e) }
        }
    }

    /** Called as the followed job updates: shows the suggestions as soon as the review has them. */
    fun acceptDeepResult(job: app.reachy.companion.data.DeepReviewJob?) {
        if (job != null && job.task != "corrections") {
            // A deep summary or minutes is saved on the meeting itself: reload it once the job is finished.
            if (openMeeting?.id == job.meetingId && job.result != null && lastRefreshedJob != job.id) {
                lastRefreshedJob = job.id
                viewModelScope.launch { try { openMeeting = api.meeting(job.meetingId) } catch (e: Exception) { listError = failed(e) } }
            }
            return
        }
        val result = job?.result ?: return
        if (openMeeting?.id == job.meetingId) {
            suggestions = result.suggestions
            suggestionNote = "Deep review: checked against ${result.termsUsed} term${if (result.termsUsed == 1) "" else "s"}."
        } else deepResults[job.meetingId] = result
    }

    /** After sign-in or relaunch: pick up a review that is still running (it may have been started from another device). */
    fun resumeDeepReview() {
        viewModelScope.launch {
            try {
                val job = api.deepCurrent() ?: return@launch
                DeepReviewController.job = job
                if (!job.finished) DeepReviewController.follow(getApplication(), job.id)
            } catch (e: Exception) { /* the banner simply does not show */ }
        }
    }

    fun renameSpeaker(label: String, name: String) = annotate { api.setSpeakerNames(it, mapOf(label to name.trim())) }
    /** A reply in Reachy's voice, or null when the hub cannot speak (the caller then uses the phone's own voice). */
    suspend fun replyVoice(text: String): File? {
        val target = File(getApplication<Application>().cacheDir, "reply-voice.wav")
        return try { if (api.speech(text, target)) target else null } catch (e: Exception) { null }
    }

    fun playMeetingFrom(id: String, seconds: Double) { viewModelScope.launch { player.playFrom(id, seconds) } }

    override fun onCleared() { player.release() }

    fun editSegment(index: Int, text: String) = annotate { api.setCorrection(it, index, text.trim()) }
    fun restoreSegment(index: Int) = annotate { api.clearCorrection(it, index) }

    /** [model] is "local" (stays on the homelab) or "cloud" (the owner chose to send this transcript to the cloud provider). */
    fun suggestCorrections(model: String) {
        val id = openMeeting?.id ?: return
        if (suggesting) return
        suggesting = true; suggestionNote = null; suggestions = emptyList()
        viewModelScope.launch {
            try {
                val result = api.suggestCorrections(id, model)
                suggestions = result.suggestions
                suggestionNote = when {
                    result.truncated -> "Some parts of the meeting could not be checked. Run Suggest again to retry."
                    result.suggestions.isEmpty() && result.termsUsed == 0 -> "No likely mistakes found. Add key terms (names, products) to catch more."
                    result.suggestions.isEmpty() -> "No likely mistakes found (checked against ${result.termsUsed} terms)."
                    else -> "Checked against ${result.termsUsed} term${if (result.termsUsed == 1) "" else "s"}."
                }
            } catch (e: Exception) { suggestionNote = failed(e) } finally { suggesting = false }
        }
    }

    fun applySuggestion(s: app.reachy.companion.data.Suggestion) {
        suggestions = suggestions - s
        // Built from the segment's current text so two suggestions on one segment both apply.
        val current = openMeeting?.let { app.reachy.companion.data.segmentText(it, s.segment) } ?: return
        if (s.original in current) editSegment(s.segment, current.replaceFirst(s.original, s.suggested))
    }

    /** Applies one suggestion's change to every matching place in the transcript, not only the flagged segment. */
    fun changeAll(s: app.reachy.companion.data.Suggestion) {
        suggestions = suggestions.filterNot { it.original == s.original && it.suggested == s.suggested }
        replaceEverywhere(s.original, s.suggested)
    }

    fun replaceEverywhere(find: String, replace: String) {
        val id = openMeeting?.id ?: return
        viewModelScope.launch {
            try {
                val result = api.replaceEverywhere(id, find.trim(), replace.trim())
                openMeeting = result.meeting; listError = null
                suggestionNote = if (result.replacedSegments == 0) "\u201c${find.trim()}\u201d was not found." else "Changed ${result.replacedSegments} place${if (result.replacedSegments == 1) "" else "s"}."
            } catch (e: Exception) { listError = failed(e) }
        }
    }

    private fun acceptDeepResultFor(id: String, result: app.reachy.companion.data.Suggestions) {
        suggestions = result.suggestions
        suggestionNote = "Deep review: checked against ${result.termsUsed} term${if (result.termsUsed == 1) "" else "s"}."
    }

    fun dismissSuggestion(s: app.reachy.companion.data.Suggestion) { suggestions = suggestions - s }

    fun showMeeting(id: String?) {
        suggestions = emptyList(); suggestionNote = null
        id?.let { deepResults.remove(it) }?.let { acceptDeepResultFor(id, it) }
        meetingPoll?.cancel()
        if (id == null) { openMeeting = null; return }
        meetingPoll = viewModelScope.launch {
            // Processing takes minutes; keep the open meeting fresh until it settles.
            while (true) {
                try { openMeeting = api.meeting(id); listError = null } catch (e: Exception) { listError = failed(e); break }
                if (openMeeting?.status in setOf("complete", "failed", "cancelled", "aligning")) break
                delay(5000)
            }
        }
    }
}

private fun <T> MutableList<T>.replace(items: List<T>) { clear(); addAll(items) }
