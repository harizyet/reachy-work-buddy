package app.reachy.companion

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.reachy.companion.data.ApiException
import app.reachy.companion.data.EmailDraft
import app.reachy.companion.data.EmailForm
import app.reachy.companion.data.EmailGroup
import app.reachy.companion.data.EmailSuggestion
import app.reachy.companion.data.IdentifyScreen
import app.reachy.companion.data.isActive
import app.reachy.companion.data.Meeting
import app.reachy.companion.data.SpeakerDecision
import app.reachy.companion.data.MeetingLink
import app.reachy.companion.data.HandoffOutcome
import app.reachy.companion.data.MEETING_DEEP_LINK
import app.reachy.companion.data.Note
import app.reachy.companion.data.RECORDING_CONFIRMATION
import app.reachy.companion.data.RecorderResult
import app.reachy.companion.data.RecordingHandoff
import app.reachy.companion.data.Section
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.Processing
import app.reachy.companion.data.Prefs
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.noteHash
import app.reachy.companion.data.Task
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File

data class ChatLine(
    val fromOwner: Boolean, val text: String, val failed: Boolean = false, val context: String? = null,
    val sources: List<app.reachy.companion.data.WebSource> = emptyList(), val searchFailed: Boolean = false,
    /** The attached document this reply was answered from and the pages whose excerpts were supplied. */
    val document: String? = null, val pages: List<Int> = emptyList(),
)

/** A saved chat as it is shown in the Talk screen: each typed message, then its reply when one was recorded. */
fun chatLines(detail: app.reachy.companion.data.ChatDetail): List<ChatLine> = detail.turns.flatMap { turn ->
    listOfNotNull(
        ChatLine(true, turn.text, failed = turn.status != "complete"),   // no recorded reply: shown as "Reply not received"
        turn.reply?.let {
            ChatLine(
                false, it, sources = turn.webSearch?.results.orEmpty(), searchFailed = turn.webSearch?.failed == true,
                document = turn.document?.title, pages = app.reachy.companion.data.citedPages(turn.citations),
            )
        },
    )
}

enum class Session { Checking, SignedOut, SignedIn }

class AppViewModel(app: Application) : AndroidViewModel(app) {
    val prefs = Prefs(app)
    private val cookieJar = PersistentCookieJar({ prefs.cookies }, { prefs.cookies = it })
    private var api = ReachyApi(prefs.baseUrl.ifBlank { "http://localhost" }, cookieJar)
    private var userId: String? = null
    val player = MeetingPlayer(File(app.cacheDir, "meeting-audio")) { id, file -> api.downloadAudio(id, file) }
    private var chatId: String? = null
    val docs = DocumentsModel({ api }, { userId }, viewModelScope) { failed(it) }

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

    /** The meeting a reminder prepared. Nothing records until the owner taps Record. */
    var prepared by mutableStateOf<app.reachy.companion.data.PreparedMeeting?>(null); private set
    fun prepareMeeting(meeting: app.reachy.companion.data.PreparedMeeting) { prepared = meeting }
    fun clearPrepared() { prepared = null }
    fun preparedGate(): app.reachy.companion.data.RecordingGate? = prepared?.let { RecordingController.gate(getApplication(), it) }
    fun startPreparedRecording() {
        val meeting = prepared ?: return
        if (RecordingController.gate(getApplication(), meeting) == app.reachy.companion.data.RecordingGate.Ready) RecordingController.start(getApplication(), meeting)
    }

    // --- "Reachy, begin meeting recording" (docs/phase-52.md). The state machine is pure (data/RecordingHandoff.kt); this wires it to the real recorder, the microphone permission and the Talk screen. ---
    /** Navigation the screen should perform once (the Shell opens the section, then clears it). */
    var openRequest by mutableStateOf<Section?>(null)

    /** The Talk screen's side of the handoff while voice mode is open; null when it is not, which fails a handoff rather than starting a recording nobody can see. */
    interface VoiceSide {
        fun inForeground(): Boolean
        fun speakConfirmation(operation: Int): Boolean
        fun endVoice()
        fun resumeListening()
    }
    var voiceSide: VoiceSide? = null
    private var commandText = ""

    val recordingHandoff = RecordingHandoff(viewModelScope, object : RecordingHandoff.Host {
        override fun microphoneAllowed() = ContextCompat.checkSelfPermission(getApplication(), android.Manifest.permission.RECORD_AUDIO) == android.content.pm.PackageManager.PERMISSION_GRANTED
        override fun recordingActive() = RecordingController.recording
        override fun appInForeground() = voiceSide?.inForeground() == true
        override fun speakConfirmation(operation: Int) = voiceSide?.speakConfirmation(operation) ?: false
        override fun endVoice() { voiceSide?.endVoice() }
        override fun requestRecorderStart() = RecordingController.start(getApplication())
        override suspend fun awaitRecorder(): RecorderResult {
            // The service sets recording once the recorder is really running, or error when it could not start; a request being accepted proves neither.
            val seen = withTimeoutOrNull(RECORDER_START_TIMEOUT_MS) { snapshotFlow { RecordingController.recording to RecordingController.error }.first { (on, error) -> on || error != null } }
            return when {
                seen == null -> RecorderResult.Failed("The recorder did not confirm that it started. Check the Meetings tab before relying on a recording.")
                seen.first -> RecorderResult.Active
                else -> RecorderResult.Failed(seen.second ?: "Could not start recording")
            }
        }
        override fun finished(outcome: HandoffOutcome) {
            val heard = commandText.also { commandText = "" }
            val typed = commandTyped; commandTyped = false
            when (outcome) {
                is HandoffOutcome.Started -> {
                    chatStatus = null
                    if (typed) chat.add(ChatLine(false, "Recording the meeting. Stop and save it from Meetings."))
                    else if (heard.isNotBlank()) { chat.add(ChatLine(true, heard)); chat.add(ChatLine(false, RECORDING_CONFIRMATION)) }
                    openRequest = MEETING_DEEP_LINK
                }
                is HandoffOutcome.AlreadyRecording -> { chatStatus = "A meeting is already being recorded, so nothing new was started."; voiceSide?.resumeListening() }
                is HandoffOutcome.Cancelled -> chatStatus = outcome.message
                is HandoffOutcome.Failed -> {
                    chatStatus = outcome.message
                    if (outcome.resumeVoice) voiceSide?.resumeListening()
                    else { if (RecordingController.error == null) RecordingController.error = outcome.message; openRequest = MEETING_DEEP_LINK }
                }
            }
        }
    })

    /** A spoken command was recognised in voice mode. False when one is already in progress (a repeated or overlapping command is dropped). */
    fun startRecordingByVoice(heard: String): Boolean {
        if (recordingHandoff.busy) return false
        commandText = heard.trim()
        return recordingHandoff.begin()
    }

    private var commandTyped = false

    /** The same command typed into the chat box: nothing is sent to the hub, and no voice is spoken or ended. */
    private fun startRecordingByTyping(typed: String) {
        if (recordingHandoff.busy) return
        chatStatus = null; commandTyped = true; commandText = ""
        chat.add(ChatLine(true, typed))
        recordingHandoff.begin(speak = false)
    }

    /** Meeting reminders: what is wrong with delivery, the upcoming events with their classification, and a refresh from the hub. */
    var reminderIssues by mutableStateOf<List<app.reachy.companion.data.ReminderIssue>>(emptyList()); private set
    val schedule = mutableStateListOf<app.reachy.companion.data.CalendarItem>()
    var scheduleError by mutableStateOf<String?>(null); private set

    fun refreshReminders() {
        viewModelScope.launch {
            // Opening the app re-arms what was stored first (a force-stop clears every alarm without telling the app), then asks the hub what is current.
            MeetingReminderScheduler.restore(getApplication())
            MeetingReminderScheduler.syncFromHub(getApplication())
            reminderIssues = MeetingReminderScheduler.issues(getApplication())
            loadSchedule()
        }
    }

    fun setMeetingReminders(on: Boolean) {
        prefs.meetingReminders = on
        if (on) refreshReminders() else { MeetingReminderScheduler.disarm(getApplication()); reminderIssues = MeetingReminderScheduler.issues(getApplication()); schedule.clear() }
    }

    // --- the Calendar screen ---------------------------------------------------------------------------------------------------------------------------
    var calendarView by mutableStateOf<app.reachy.companion.data.ScheduleView?>(null); private set
    var calendarCheckedMs by mutableStateOf<Long?>(null); private set
    /** True when the last attempt to reach the hub failed, so what is shown is the copy saved on this phone. */
    var calendarOffline by mutableStateOf(false); private set
    var calendarRefreshing by mutableStateOf(false); private set
    var calendarMessage by mutableStateOf<String?>(null); private set
    var calendarMonth by mutableStateOf(java.time.YearMonth.now())
    var calendarDay by mutableStateOf(java.time.LocalDate.now())

    /** Shows the saved copy at once (so the screen is never blank offline), then asks the hub for the current revision. */
    fun openCalendar() {
        if (calendarView == null) CalendarCache.read(getApplication())?.let { calendarView = it.view; calendarCheckedMs = it.checkedAtMs; calendarOffline = true }
        loadCalendar()
    }

    /** Reads the current revision. A different revision than the phone's reminders were built from reconciles them straight away: moved meetings are rescheduled, removed ones cancelled. */
    fun loadCalendar() {
        viewModelScope.launch {
            val zone = java.time.ZoneId.systemDefault()
            val grid = app.reachy.companion.data.monthGrid(calendarMonth)
            val today = java.time.LocalDate.now()
            val from = minOf(grid.first(), today).atStartOfDay(zone).toOffsetDateTime().toString()
            val to = maxOf(grid.last().plusDays(1), today.plusDays(14)).atStartOfDay(zone).toOffsetDateTime().toString()
            try {
                val view = api.calendarSchedule(from, to)
                val now = System.currentTimeMillis()
                calendarView = view; calendarCheckedMs = now; calendarOffline = false
                CalendarCache.write(getApplication(), CachedSchedule(view, now))
                if (prefs.meetingReminders && MeetingReminderScheduler.appliedGeneration(getApplication()) != view.generation) {
                    MeetingReminderScheduler.syncFromHub(getApplication()); reminderIssues = MeetingReminderScheduler.issues(getApplication())
                }
            } catch (e: Exception) { calendarOffline = true }
        }
    }

    /** The owner's Refresh: the hub downloads the source and publishes a new revision at once, then this phone reads it and reconciles its reminders. */
    fun refreshCalendarSource() {
        viewModelScope.launch {
            calendarRefreshing = true; calendarMessage = null
            try { api.refreshCalendar(); calendarMessage = null } catch (e: ApiException) { calendarMessage = if (e.unauthorized) "Sign in again" else "The hub could not refresh the calendar" } catch (e: Exception) { calendarMessage = "The hub could not be reached" }
            loadCalendar()
            calendarRefreshing = false
        }
    }

    private suspend fun loadSchedule() {
        if (!prefs.meetingReminders) return
        val start = java.time.ZonedDateTime.now().truncatedTo(java.time.temporal.ChronoUnit.DAYS)
        scheduleError = try {
            schedule.clear()
            schedule.addAll(api.calendarEvents(start.toOffsetDateTime().toString(), start.plusDays(3).toOffsetDateTime().toString()).filter { app.reachy.companion.data.onSchedule(it) })
            null
        } catch (e: Exception) { "The calendar could not be loaded" }
    }

    // --- Home (docs/phase-51.md) ---------------------------------------------------------------------------------------------------------------------
    var homeView by mutableStateOf<app.reachy.companion.data.HomeSnapshot?>(null); private set
    var homeCheckedMs by mutableStateOf<Long?>(null); private set
    /** True when the last attempt to reach the hub failed, so what is shown is the copy saved on this phone (or nothing yet). */
    var homeOffline by mutableStateOf(false); private set
    var homeLoading by mutableStateOf(false); private set
    var homeBusy by mutableStateOf<Set<String>>(emptySet()); private set
    var homeError by mutableStateOf<String?>(null); private set
    var homeBrief by mutableStateOf<app.reachy.companion.data.HomeBrief?>(null); private set
    var homeBriefBusy by mutableStateOf(false); private set
    var homeBriefError by mutableStateOf<String?>(null); private set

    /** Shows the saved copy at once (so Home is never blank offline), then asks the hub for the current snapshot. */
    fun openHome() {
        if (homeView == null) HomeCache.read(getApplication())?.let { homeView = it.view; homeCheckedMs = it.checkedAtMs; homeOffline = true }
        loadHome()
    }

    fun loadHome() {
        viewModelScope.launch {
            homeLoading = true
            try {
                val view = api.home()
                val now = System.currentTimeMillis()
                homeView = view; homeCheckedMs = now; homeOffline = false; homeError = null
                HomeCache.write(getApplication(), CachedHome(view, now))
            } catch (e: ApiException) { homeOffline = true; homeError = if (e.unauthorized) "Sign in again" else "Home could not be loaded (${e.message})" }
            catch (e: Exception) { homeOffline = true; homeError = null }
            finally { homeLoading = false }
        }
    }

    /** One card refreshes on its own: only its section changes, and the others keep what they show. */
    fun refreshHomeSection(name: String) {
        if (name in homeBusy) return
        viewModelScope.launch {
            homeBusy = homeBusy + name
            try {
                val fresh = api.home(listOf(name))
                val merged = homeView?.let { app.reachy.companion.data.mergeSection(it, fresh, name) } ?: fresh
                val now = System.currentTimeMillis()
                homeView = merged; homeOffline = false; homeError = null; homeCheckedMs = now
                HomeCache.write(getApplication(), CachedHome(merged, now))
            } catch (e: ApiException) { homeError = if (e.unauthorized) "Sign in again" else "That section could not be refreshed" }
            catch (e: Exception) { homeError = "The hub could not be reached"; homeOffline = true }
            finally { homeBusy = homeBusy - name }
        }
    }

    fun briefMe() {
        viewModelScope.launch {
            homeBriefBusy = true; homeBriefError = null
            try { homeBrief = api.homeBrief(true) }
            catch (e: ApiException) { homeBriefError = if (e.unauthorized) "Sign in again" else "The briefing could not be prepared" }
            catch (e: Exception) { homeBriefError = "The hub could not be reached, so there is no briefing right now" }
            finally { homeBriefBusy = false }
        }
    }

    fun closeBrief() { homeBrief = null; homeBriefError = null }

    /** Retries clips whose upload failed earlier, then refreshes the list. */
    fun retryPendingUploads() {
        viewModelScope.launch {
            if (RecordingController.recording || RecordingController.uploading) return@launch
            RecordingController.uploading = true
            try { RecordingController.error = uploadPending(getApplication())?.let { "Upload failed ($it). The recording is kept on this phone." } } finally { RecordingController.uploading = false }
        }
    }

    init { RecordingController.loadHeld(getApplication()); viewModelScope.launch { resume() } }
    fun keepShortRecording() = RecordingController.uploadHeld(getApplication())
    fun discardShortRecording() = RecordingController.discardHeld()

    private suspend fun resume() {
        if (prefs.baseUrl.isBlank()) { session = Session.SignedOut; return }
        session = try { api.me(); userId = api.userId(); Session.SignedIn } catch (e: Exception) { Session.SignedOut }
        if (session == Session.SignedIn) { resumeDeepReview(); refreshReminders(); loadEmailConfig() }
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
                chat.clear(); chatId = null; attachedDocument = null; docs.clear()
                session = Session.SignedIn
                resumeDeepReview()
                refreshReminders()
                loadEmailConfig()
            } catch (e: ApiException) {
                loginError = if (e.unauthorized) "Wrong username or password" else e.message
            } catch (e: Exception) {
                loginError = "Could not reach ${prefs.baseUrl}. Check the address and that you are on the home network or VPN."
            } finally { loginBusy = false }
        }
    }

    fun signOut() {
        recordingHandoff.cancel("Signed out"); viewModelScope.launch { api.logout(); chat.clear(); attachedDocument = null; docs.clear(); chatHistory.clear(); tasks.clear(); notes.clear(); meetings.clear(); processing.clear(); meetingLinks.clear(); processingPoll?.cancel(); chatId = null; if (recording) stopRecording(); DeepReviewController.job = null
            MeetingReminderScheduler.disarm(getApplication()); CalendarCache.clear(getApplication()); HomeCache.clear(getApplication()); homeView = null; homeCheckedMs = null; homeBrief = null; homeBriefError = null; homeError = null; calendarView = null; calendarCheckedMs = null; schedule.clear(); prepared = null; reminderIssues = emptyList(); session = Session.SignedOut }
    }

    private fun failed(e: Exception): String {
        if (e is ApiException && e.unauthorized) { session = Session.SignedOut; return "Please sign in again" }
        return e.message ?: "Something went wrong"
    }

    fun send(text: String, spoken: Boolean = false) {
        val message = text.trim()
        val user = userId
        if (message.isEmpty() || sending || user == null) return
        if (!spoken && app.reachy.companion.data.isMeetingRecordingCommand(message)) { startRecordingByTyping(message); return }
        sending = true; chatStatus = null
        val line = ChatLine(true, message)
        chat.add(line)
        viewModelScope.launch {
            try {
                if (!spoken && chatId == null) {
                    chatId = api.createChat(user, message).id; runCatching { chatHistory.replace(api.chats(user)) }
                    // A document chosen before the first message is saved on the hub with the new chat, before anything is sent: a message must
                    // never go out as ordinary chat when the owner meant it to be answered from the document.
                    val chosen = attachedDocument
                    if (chosen != null) {
                        try { attachedDocument = api.setChatDocument(user, chatId!!, chosen.id) } catch (e: Exception) {
                            chat.remove(line); chatStatus = "The document could not be attached (${failed(e)}). Nothing was sent."; return@launch
                        }
                    }
                }
                val reply = api.send(user, message, spoken, chatId, contextMeeting?.first, forceFrontier = contextCloud && contextMeeting != null)
                chat.add(ChatLine(
                    false, reply.reply, context = reply.contextMeeting, sources = reply.webSearch?.results.orEmpty(), searchFailed = reply.webSearch?.failed == true,
                    document = reply.contextDocument, pages = app.reachy.companion.data.citedPages(reply.citations),
                )); lastReply = reply.reply; replySeq++
                if (!spoken) runCatching { chatHistory.replace(api.chats(user)) }   // the chat moves to the top
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

    fun useAsContext(meeting: Meeting) {
        // One source at a time: the hub answers from an attached document first, so choosing a meeting lets go of it.
        if (attachedDocument != null) attachDocument(null)
        contextMeeting = meeting.id to meeting.title; contextCloud = false
    }
    fun clearContext() { contextMeeting = null; contextCloud = false }

    fun newChat() { chat.clear(); chatId = null; chatStatus = null; attachedDocument = null }

    /**
     * The document this chat answers from. For a saved chat it is the hub's own record (it survives restarts and other devices); for a chat not
     * yet started it is held here and saved the moment the chat is created, before the first message.
     */
    var attachedDocument by mutableStateOf<app.reachy.companion.data.ChatDocument?>(null); private set

    /** Attaches or replaces the chat's document, or removes it (null). Choosing one lets go of a chosen meeting. */
    fun attachDocument(document: app.reachy.companion.data.DocumentItem?) {
        val user = userId ?: return
        val id = chatId
        if (document != null) clearContext()
        if (id == null) { attachedDocument = document?.let { app.reachy.companion.data.ChatDocument(it.id, it.title) }; return }
        viewModelScope.launch {
            try { attachedDocument = api.setChatDocument(user, id, document?.id); chatStatus = null } catch (e: Exception) { chatStatus = failed(e) }
        }
    }

    /** The saved chats (newest first) and the one open in the Talk screen. */
    val chatHistory = mutableStateListOf<app.reachy.companion.data.ChatRecord>()
    val openChatId get() = chatId

    fun loadChatHistory() = load { val user = userId ?: return@load; chatHistory.replace(api.chats(user)) }

    /** Shows a saved chat. Nothing is read aloud: only replies that arrive now are. */
    fun openChat(id: String) {
        val user = userId ?: return
        if (sending) return
        viewModelScope.launch {
            try {
                val detail = api.chat(user, id)
                chat.replace(chatLines(detail)); chatId = detail.id; chatStatus = null; listError = null
                attachedDocument = detail.document
                if (detail.document != null) clearContext()
            } catch (e: Exception) { listError = failed(e) }
        }
    }

    fun deleteChat(record: app.reachy.companion.data.ChatRecord) {
        val user = userId ?: return
        viewModelScope.launch {
            try {
                api.deleteChat(user, record.id)
                if (chatId == record.id) newChat()
                chatHistory.replace(api.chats(user)); listError = null
            } catch (e: Exception) { listError = failed(e) }
        }
    }

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
    fun saveNote(id: String?, title: String, body: String, tag: String?, onSaved: (String) -> Unit = {}) = load {
        val saved = api.saveNote(id, title.trim(), body, tag)
        notes.replace(api.notes())
        onSaved(saved.id)
    }
    fun deleteNote(note: Note) = load { api.deleteNote(note.id); notes.replace(api.notes()) }

    // ---- Notepad processing (Phase 49). Off unless the hub says it is on; the server decides every state and every proposal.
    var processingEnabled by mutableStateOf(false); private set
    val processing = mutableStateMapOf<String, Processing>()
    val meetingLinks = mutableStateMapOf<String, List<MeetingLink>>()
    /** True from the moment a note is sent until the server has finished with it. */
    var processingBusy by mutableStateOf(false); private set
    var processingMessage by mutableStateOf<String?>(null); private set
    private var processingPoll: Job? = null

    fun loadProcessingConfig() {
        viewModelScope.launch { processingEnabled = try { api.processingEnabled() } catch (e: Exception) { false } }
    }

    /** Opening a note: its processing state and meeting links, and keep asking while the server is working on it. */
    fun openProcessing(noteId: String) {
        if (processingBusy) return // a send that just created this note is already following it; restarting would cut it short
        processingPoll?.cancel(); processingMessage = null
        processingPoll = viewModelScope.launch {
            try { meetingLinks[noteId] = api.meetingLinks(noteId) } catch (e: Exception) { processingMessage = failed(e) }
            followProcessing(noteId, null)
        }
    }

    fun closeProcessing() { processingPoll?.cancel(); processingMessage = null }

    private suspend fun followProcessing(noteId: String, first: Processing?) {
        var next = first
        var polls = 0
        while (true) {
            val state = try { next ?: api.processing(noteId) } catch (e: Exception) { processingMessage = failed(e); return }
            processing[noteId] = state
            if (!state.inProgress || ++polls > 400) return
            delay(1500); next = null
        }
    }

    /** Saves the note first when it has unsaved changes (processing reads what is stored, never the model's view of the editor), then sends it. */
    fun processNote(id: String?, title: String, body: String, tag: String?, save: Boolean, force: Boolean, includeMeetings: Boolean, onSaved: (String) -> Unit) {
        if (processingBusy) return
        processingBusy = true; processingMessage = null
        processingPoll?.cancel()
        processingPoll = viewModelScope.launch {
            try {
                var noteId = id
                if (save || noteId == null) { noteId = api.saveNote(noteId, title.trim(), body, tag).id; notes.replace(api.notes()); onSaved(noteId) }
                followProcessing(noteId, api.sendForProcessing(noteId, noteHash(body), force, includeMeetings))
            } catch (e: Exception) { processingMessage = failed(e) } finally { processingBusy = false }
        }
    }

    private fun processingAction(noteId: String, block: suspend () -> Unit) {
        viewModelScope.launch {
            processingMessage = null
            try { block() } catch (e: Exception) { processingMessage = failed(e) }
        }
    }

    fun retryProcessing(noteId: String, jobId: String) {
        processingPoll?.cancel()
        processingPoll = viewModelScope.launch {
            processingMessage = null
            try { followProcessing(noteId, api.retryProcessing(jobId)) } catch (e: Exception) { processingMessage = failed(e) }
        }
    }

    /** Accepting adds a task or reminder (once, with its receipt); the lists are reloaded so it shows at once. */
    fun acceptProposal(noteId: String, proposalId: String, text: String? = null, kind: String? = null, dueAt: String? = null) = processingAction(noteId) {
        api.acceptProposal(proposalId, text, kind, dueAt)
        processing[noteId] = api.processing(noteId)
        loadTasksNow(); loadRemindersNow()
    }

    fun dismissProposal(noteId: String, proposalId: String) = processingAction(noteId) {
        api.dismissProposal(proposalId)
        processing[noteId] = api.processing(noteId)
    }

    fun setMeetingLink(noteId: String, meetingId: String, confirmed: Boolean) = processingAction(noteId) {
        meetingLinks[noteId] = api.setMeetingLink(noteId, meetingId, confirmed)
    }

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
    var generatingModel by mutableStateOf("local"); private set

    fun generateOutput(kind: String, model: String) {
        val id = openMeeting?.id ?: return
        if (generatingKind != null) return
        generatingKind = kind
        generatingModel = model
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

    // Identify Speakers (Phase 54): the screen's server data, and a one-line note on the last save.
    var identify by mutableStateOf<IdentifyScreen?>(null); private set
    var identifyNote by mutableStateOf<String?>(null); private set
    var identifySaving by mutableStateOf(false); private set

    fun loadIdentify() {
        val id = openMeeting?.id ?: return
        viewModelScope.launch {
            try { identify = api.identifySpeakers(id); listError = null } catch (e: Exception) { identify = null; listError = failed(e) }
        }
    }

    fun clearIdentify() { identify = null; identifyNote = null }

    /** Saves the owner's decisions in one request, then reloads the screen so it shows what is stored. */
    fun saveIdentify(decisions: Map<String, SpeakerDecision>) {
        val id = openMeeting?.id ?: return
        val fingerprint = identify?.fingerprint
        identifySaving = true; identifyNote = null
        viewModelScope.launch {
            try {
                openMeeting = api.confirmSpeakers(id, fingerprint, decisions)
                identify = api.identifySpeakers(id)
                identifyNote = "Saved. The transcript now shows these names."; listError = null
            } catch (e: Exception) { identifyNote = failed(e) }
            finally { identifySaving = false }
        }
    }

    fun playSample(id: String, start: Double, end: Double) { viewModelScope.launch { player.playRange(id, start, end) } }

    // Share minutes (Phase 55): the server's state of the owner's meeting emails. The phone holds no credential and sends nothing by itself; every message needs the owner's typed approval.
    var emailEnabled by mutableStateOf(false); private set
    var emailSenderReady by mutableStateOf(false); private set
    var emailSenderConfigured by mutableStateOf(false); private set
    var emailDelaySeconds by mutableStateOf(600); private set
    var emailDrafts by mutableStateOf<List<EmailDraft>>(emptyList()); private set
    var emailGroups by mutableStateOf<List<EmailGroup>>(emptyList()); private set
    var emailSuggestions by mutableStateOf<List<EmailSuggestion>>(emptyList()); private set
    var emailNote by mutableStateOf<String?>(null); private set
    var emailNeedsAck by mutableStateOf(false); private set
    var emailBusy by mutableStateOf(false); private set
    var openEmailId by mutableStateOf<String?>(null)
    private var emailPoll: Job? = null

    /** Whether the hub has the feature on. A hub without it (or an older one) simply makes the section absent. */
    fun loadEmailConfig() {
        viewModelScope.launch {
            try {
                val config = api.emailConfig()
                emailEnabled = config.enabled; emailSenderConfigured = config.sender?.configured == true; emailSenderReady = config.sender?.let { it.configured && it.enabled } == true
                emailDelaySeconds = config.sendDelaySeconds
            } catch (e: Exception) { emailEnabled = false }
        }
    }

    fun loadEmail(meetingId: String) {
        viewModelScope.launch {
            try {
                emailDrafts = api.emailDrafts(meetingId); emailNote = null
                runCatching { emailGroups = api.emailGroups(); emailSuggestions = api.emailSuggestions(meetingId) }
            } catch (e: Exception) { emailNote = failed(e) }
        }
        emailPoll?.cancel()
        emailPoll = viewModelScope.launch {
            // While a message waits or is being sent the server says where it is; nothing is polled otherwise.
            while (true) {
                delay(5000)
                if (emailDrafts.none { isActive(it) }) continue
                try { emailDrafts = api.emailDrafts(meetingId) } catch (e: Exception) { break }
            }
        }
    }

    fun openMeetingId(): String? = openMeeting?.id

    fun clearEmail() { emailPoll?.cancel(); emailDrafts = emptyList(); emailNote = null; emailNeedsAck = false; openEmailId = null }

    private fun emailAction(after: (EmailDraft) -> Unit = {}, call: suspend () -> EmailDraft) {
        emailBusy = true; emailNote = null
        viewModelScope.launch {
            try {
                val draft = call()
                emailDrafts = listOf(draft) + emailDrafts.filter { it.id != draft.id }
                openEmailId = draft.id; after(draft)
            } catch (e: Exception) {
                emailNote = failed(e)
                if (e is ApiException && e.reason == "sensitive_meeting") emailNeedsAck = true
                openMeeting?.id?.let { id -> runCatching { emailDrafts = api.emailDrafts(id) } }  // show what the server holds now
            } finally { emailBusy = false }
        }
    }

    fun prepareEmail(meetingId: String, includePdf: Boolean, allowSensitive: Boolean) = emailAction({ emailNeedsAck = false }) { api.prepareEmail(meetingId, includePdf, allowSensitive) }
    fun saveEmail(id: String, form: EmailForm) = emailAction { api.editEmail(id, form) }
    fun refreshEmail(id: String) = emailAction { api.refreshEmail(id) }

    /** Approve the exact saved package with the typed word, then queue it when sending is on. The server checks the hash, the word, the sender and that the meeting has not changed. */
    fun approveEmail(draft: EmailDraft, typed: String) = emailAction {
        val approved = api.approveEmail(draft.id, draft.packageHash.orEmpty(), typed)
        if (approved.senderReady) api.queueEmail(draft.id) else approved
    }
    fun queueEmail(id: String) = emailAction { api.queueEmail(id) }
    fun cancelEmailSend(id: String) = emailAction { api.cancelEmailSend(id) }
    fun discardEmail(id: String) = emailAction({ openEmailId = null }) { api.discardEmail(id) }
    fun resolveEmail(id: String, delivered: Boolean) = emailAction { api.resolveEmail(id, delivered) }

    /** Downloads the attachment as it will be sent into the app's cache for the in-app preview. */
    suspend fun fetchEmailAttachment(id: String, name: String): File {
        val dir = File(getApplication<Application>().cacheDir, "email-preview").also { it.mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        return File(dir, "preview.pdf").also { api.downloadEmailAttachment(id, name, it) }
    }
    /** Streams a reply in Reachy's voice; false (nothing played) when the hub cannot speak. */
    suspend fun replyStream(text: String, onRate: (Int) -> Unit, onPcm: (ByteArray, Int) -> Unit): Boolean =
        try { api.speechStream(text, onRate, onPcm) } catch (e: Exception) { false }

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

/** A failure guard only (never used to decide when to start): how long the recorder gets to report that it is running before the owner is told it did not confirm. */
private const val RECORDER_START_TIMEOUT_MS = 15_000L

private fun <T> MutableList<T>.replace(items: List<T>) { clear(); addAll(items) }
