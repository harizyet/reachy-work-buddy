package app.reachy.companion.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.source
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(val code: Int, message: String) : IOException(message) {
    val unauthorized get() = code == 401
}

/** Persists the owner's session cookie so the app stays signed in across launches. */
class PersistentCookieJar(private val load: () -> String?, private val save: (String?) -> Unit) : CookieJar {
    private var cookies: List<Cookie>? = null

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        val merged = (current(url).filter { old -> cookies.none { it.name == old.name } } + cookies)
            .filter { it.expiresAt > System.currentTimeMillis() }
        this.cookies = merged
        save(merged.joinToString("\n") { it.toString() }.ifEmpty { null })
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> = current(url).filter { it.matches(url) }

    private fun current(url: HttpUrl): List<Cookie> =
        cookies ?: load().orEmpty().lineSequence().mapNotNull { Cookie.parse(url, it) }.toList().also { cookies = it }

    fun clear() { cookies = emptyList(); save(null) }
}

fun normalizeBaseUrl(raw: String): String {
    val trimmed = raw.trim().trimEnd('/')
    return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "http://$trimmed"
}

/**
 * Talks only to reachy-hub's owner routes (the same ones the web control panel
 * uses): cookie login plus the X-Reachy-CSRF header. Nothing here reaches core
 * or the robot directly, and no key or transcript is persisted by this class.
 */
class ReachyApi(baseUrl: String, private val cookieJar: PersistentCookieJar, client: OkHttpClient = OkHttpClient()) {
    private val base = normalizeBaseUrl(baseUrl)
    private val json = Json { ignoreUnknownKeys = true }
    private val http = client.newBuilder()
        .cookieJar(cookieJar)
        .addInterceptor { chain -> chain.proceed(chain.request().newBuilder().header("X-Reachy-CSRF", "1").build()) }
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(140, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()

    private fun jsonBody(value: JsonObject): RequestBody =
        json.encodeToString(JsonObject.serializer(), value).toRequestBody("application/json".toMediaType())

    private suspend fun call(request: Request): String = withContext(Dispatchers.IO) {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) throw ApiException(response.code, errorDetail(text) ?: "Request failed (${response.code})")
            text
        }
    }

    private fun errorDetail(body: String): String? = runCatching {
        val detail = json.parseToJsonElement(body).jsonObject["detail"]
        (detail as? JsonPrimitive)?.contentOrNull
    }.getOrNull()

    private fun req(path: String) = Request.Builder().url(base + path)

    suspend fun login(username: String, password: String) {
        call(req("/auth/login").post(jsonBody(buildJsonObject { put("username", username); put("password", password) })).build())
    }

    suspend fun me(): String =
        json.parseToJsonElement(call(req("/auth/me").build())).jsonObject["username"]!!.jsonPrimitive.content

    suspend fun logout() {
        runCatching { call(req("/auth/logout").post("{}".toRequestBody("application/json".toMediaType())).build()) }
        cookieJar.clear()
    }

    suspend fun userId(): String =
        json.decodeFromString<StatusInfo>(call(req("/status").build())).defaultUserId
            ?: throw ApiException(409, "The hub has no owner user configured")

    suspend fun createChat(userId: String, title: String): ChatRecord =
        json.decodeFromString(call(req("/chats").post(jsonBody(buildJsonObject {
            put("user_id", userId); put("title", title.take(120))
        })).build()))

    private fun chatReq(path: String, userId: String) = req("$path?user_id=${java.net.URLEncoder.encode(userId, "UTF-8")}")

    suspend fun chats(userId: String): List<ChatRecord> =
        json.decodeFromString(ListSerializer(ChatRecord.serializer()), call(chatReq("/chats", userId).build()))

    suspend fun chat(userId: String, id: String): ChatDetail =
        json.decodeFromString(call(chatReq("/chats/$id", userId).build()))

    suspend fun deleteChat(userId: String, id: String) { call(chatReq("/chats/$id", userId).delete().build()) }

    /** Typed turns join a chat record; spoken turns do not (the hub archives typed web messages only). */
    suspend fun send(userId: String, text: String, spoken: Boolean, chatId: String?, contextMeetingId: String? = null, forceFrontier: Boolean = false): Reply =
        json.decodeFromString<Reply>(call(req("/messages").post(jsonBody(buildJsonObject {
            put("user_id", userId); put("channel", "web"); put("text", text)
            put("input_modality", if (spoken) "voice" else "text")
            if (!spoken && chatId != null) put("chat_id", chatId)
            // A meeting attached as context: the hub answers with the local model only (the transcript stays private).
            if (contextMeetingId != null) put("context_meeting_id", contextMeetingId)
            // Only when the owner picks the cloud for this question: the attached meeting text then leaves the homelab.
            if (forceFrontier) put("force_frontier", true)
        })).build()))

    suspend fun tasks(): List<Task> =
        json.decodeFromString(ListSerializer(Task.serializer()), call(req("/planner/tasks").build()))

    suspend fun addTask(text: String): Task =
        json.decodeFromString(call(req("/planner/tasks").post(jsonBody(buildJsonObject { put("text", text) })).build()))

    suspend fun setTaskDone(id: String, done: Boolean) {
        call(req("/planner/tasks/$id/${if (done) "complete" else "reopen"}").post("{}".toRequestBody("application/json".toMediaType())).build())
    }

    suspend fun deleteTask(id: String) { call(req("/planner/tasks/$id").delete().build()) }

    suspend fun notes(): List<Note> =
        json.decodeFromString(ListSerializer(Note.serializer()), call(req("/planner/notes").build()))

    suspend fun saveNote(id: String?, title: String, body: String, tag: String?): Note {
        val payload = jsonBody(buildJsonObject { put("title", title); put("body", body); put("tag", tag) })
        val request = if (id == null) req("/planner/notes").post(payload) else req("/planner/notes/$id").put(payload)
        return json.decodeFromString(call(request.build()))
    }

    suspend fun deleteNote(id: String) { call(req("/planner/notes/$id").delete().build()) }

    // Notepad processing (Phase 49). A 404 on the config route (an older hub, or the feature off) means off, never an error.
    suspend fun processingEnabled(): Boolean = try {
        json.parseToJsonElement(call(req("/notepad-processing/config").build())).jsonObject["enabled"]?.jsonPrimitive?.booleanOrNull == true
    } catch (e: ApiException) {
        if (e.code == 404) false else throw e
    }

    suspend fun processing(noteId: String): Processing = json.decodeFromString(call(req("/notes/$noteId/processing").build()))

    suspend fun sendForProcessing(noteId: String, expectedHash: String?, force: Boolean, includeMeetings: Boolean): Processing =
        json.decodeFromString(call(req("/notes/$noteId/processing").post(jsonBody(buildJsonObject {
            if (expectedHash != null) put("expected_hash", expectedHash)
            put("force", force); put("include_meetings", includeMeetings)
        })).build()))

    suspend fun retryProcessing(jobId: String): Processing =
        json.decodeFromString(call(req("/notepad-processing/jobs/$jobId/retry").post("{}".toRequestBody("application/json".toMediaType())).build()))

    /** Only the fields the owner changed are sent; the server falls back to its own proposal for the rest. */
    suspend fun acceptProposal(id: String, text: String? = null, kind: String? = null, dueAt: String? = null) {
        call(req("/notepad-proposals/$id/accept").post(jsonBody(buildJsonObject {
            if (text != null) put("text", text)
            if (kind != null) put("kind", kind)
            if (dueAt != null) put("due_at", dueAt)
        })).build())
    }

    suspend fun dismissProposal(id: String) {
        call(req("/notepad-proposals/$id/dismiss").post("{}".toRequestBody("application/json".toMediaType())).build())
    }

    suspend fun meetingLinks(noteId: String): List<MeetingLink> =
        json.decodeFromString<MeetingLinks>(call(req("/notes/$noteId/meeting-links").build())).links

    suspend fun setMeetingLink(noteId: String, meetingId: String, confirmed: Boolean): List<MeetingLink> =
        json.decodeFromString<MeetingLinks>(call(req("/notes/$noteId/meeting-links/$meetingId").put(jsonBody(buildJsonObject {
            put("state", if (confirmed) "confirmed" else "rejected")
        })).build())).links

    /** The recording reminders to schedule on this phone (the hub bounds the horizon), from the owner's calendar feed. */
    suspend fun meetingReminders(): ReminderSet = json.decodeFromString(call(req("/calendar-feed/reminders").build()))

    /** Calendar events in a window with their classification, for the schedule list. */
    suspend fun calendarEvents(startIso: String, endIso: String): List<CalendarItem> {
        val url = (base + "/calendar-feed/events").toHttpUrl().newBuilder().addQueryParameter("start", startIso).addQueryParameter("end", endIso).build()
        return json.decodeFromString(ListSerializer(CalendarItem.serializer()), call(Request.Builder().url(url).build()))
    }

    /** Events and the feed's status from one revision of the calendar, for the Calendar screen. */
    suspend fun calendarSchedule(startIso: String, endIso: String): ScheduleView {
        val url = (base + "/calendar-feed/schedule").toHttpUrl().newBuilder().addQueryParameter("start", startIso).addQueryParameter("end", endIso).build()
        return json.decodeFromString(call(Request.Builder().url(url).build()))
    }

    /** Asks the hub to download and publish the calendar source now (the owner's manual Refresh). */
    suspend fun refreshCalendar() { call(req("/calendar-feed/refresh").post("{}".toRequestBody("application/json".toMediaType())).build()) }

    /** The Home snapshot (docs/phase-51.md), or only the named sections so one card refreshes on its own. Read-only. */
    suspend fun home(sections: List<String>? = null): HomeSnapshot {
        val url = (base + "/home").toHttpUrl().newBuilder().apply { if (!sections.isNullOrEmpty()) addQueryParameter("sections", sections.joinToString(",")) }.build()
        return parseHome(call(Request.Builder().url(url).build()))
    }

    /** "Brief me on today": the deterministic lines, and the local model's wording of them when `narrative` is asked for and it checks out. Read-only. */
    suspend fun homeBrief(narrative: Boolean): HomeBrief =
        parseBrief(call(req("/home/brief").post(jsonBody(buildJsonObject { put("narrative", narrative) })).build()))

    suspend fun meetings(): List<Meeting> =
        json.decodeFromString(ListSerializer(Meeting.serializer()), call(req("/meetings").build()))

    suspend fun meeting(id: String): Meeting = json.decodeFromString(call(req("/meetings/$id").build()))

    suspend fun uploadMeeting(title: String, file: File, contentType: String = "audio/mp4"): Meeting {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("title", title)
            .addFormDataPart("audio", file.name, file.asRequestBody(contentType.toMediaType()))
            .build()
        return json.decodeFromString(call(req("/meetings").post(body).build()))
    }

    suspend fun setSpeakerNames(id: String, names: Map<String, String>): Meeting =
        json.decodeFromString(call(req("/meetings/$id/speakers").put(jsonBody(buildJsonObject {
            put("names", buildJsonObject { names.forEach { (label, name) -> put(label, name) } })
        })).build()))

    suspend fun identifySpeakers(id: String): IdentifyScreen =
        json.decodeFromString(call(req("/meetings/$id/speakers/identify").build()))

    /** Saves the owner's decisions (named, unknown, skipped or clear) in one request; the hub refuses it if the speaker detection changed since [fingerprint]. */
    suspend fun confirmSpeakers(id: String, fingerprint: String?, decisions: Map<String, SpeakerDecision>): Meeting =
        json.decodeFromString(call(req("/meetings/$id/speakers/identify").put(jsonBody(buildJsonObject {
            if (fingerprint != null) put("fingerprint", fingerprint)
            put("decisions", buildJsonObject {
                decisions.forEach { (label, d) -> put(label, buildJsonObject { put("status", d.status); if (d.name != null) put("name", d.name) }) }
            })
        })).build()))

    /** Asks the local model for likely mis-heard words. Nothing is changed until a suggestion is applied. */
    suspend fun suggestCorrections(id: String, model: String = "local"): Suggestions {
        val slow = http.newBuilder().readTimeout(260, TimeUnit.SECONDS).build()
        val body = withContext(Dispatchers.IO) {
            slow.newCall(req("/meetings/$id/corrections/suggest").post(jsonBody(buildJsonObject { put("model", model) })).build()).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) throw ApiException(response.code, errorDetail(text) ?: "Request failed (${response.code})")
                text
            }
        }
        return json.decodeFromString(body)
    }

    suspend fun setCorrection(id: String, segment: Int, text: String): Meeting =
        json.decodeFromString(call(req("/meetings/$id/corrections/$segment").put(jsonBody(buildJsonObject { put("text", text) })).build()))

    /** Changes every whole-word, case-insensitive match of [find] across the transcript; reversible per segment. */
    suspend fun replaceEverywhere(id: String, find: String, replace: String): ReplaceResult =
        json.decodeFromString(call(req("/meetings/$id/corrections/replace").post(jsonBody(buildJsonObject {
            put("find", find); put("replace", replace)
        })).build()))

    suspend fun setKeyTerms(id: String, terms: List<String>): Meeting =
        json.decodeFromString(call(req("/meetings/$id/terms").put(jsonBody(buildJsonObject {
            put("terms", kotlinx.serialization.json.JsonArray(terms.map { JsonPrimitive(it) }))
        })).build()))

    suspend fun glossary(): List<String> =
        json.decodeFromString(ListSerializer(String.serializer()), call(req("/meeting-terms").build()))

    suspend fun addGlossaryTerm(term: String): List<String> =
        json.decodeFromString(ListSerializer(String.serializer()),
            call(req("/meeting-terms").post(jsonBody(buildJsonObject { put("term", term) })).build()))

    suspend fun deleteGlossaryTerm(term: String): List<String> {
        val url = (base + "/meeting-terms").toHttpUrl().newBuilder().addQueryParameter("term", term).build()
        return json.decodeFromString(ListSerializer(String.serializer()),
            call(Request.Builder().url(url).delete().build()))
    }

    suspend fun deleteMeeting(id: String) { call(req("/meetings/$id").delete().build()) }

    suspend fun cancelMeeting(id: String): Meeting =
        json.decodeFromString(call(req("/meetings/$id/cancel").post("{}".toRequestBody("application/json".toMediaType())).build()))

    /** Summary or minutes on "local" or "cloud"; blocks until the model has written it. */
    suspend fun generateOutput(id: String, kind: String, model: String): Meeting {
        val slow = http.newBuilder().readTimeout(280, TimeUnit.SECONDS).build()
        val text = withContext(Dispatchers.IO) {
            slow.newCall(req("/meetings/$id/outputs/$kind").post(jsonBody(buildJsonObject { put("model", model) })).build()).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) throw ApiException(response.code, errorDetail(body) ?: "Request failed (${response.code})")
                body
            }
        }
        return json.decodeFromString(text)
    }

    suspend fun clearOutput(id: String, kind: String): Meeting =
        json.decodeFromString(call(req("/meetings/$id/outputs/$kind").delete().build()))

    suspend fun startDeepOutput(id: String, kind: String): DeepReviewJob =
        json.decodeFromString(call(req("/meetings/$id/outputs/$kind/deep").post("{}".toRequestBody("application/json".toMediaType())).build()))

    suspend fun deepInfo(): DeepReviewInfo = json.decodeFromString(call(req("/deep-review/info").build()))

    suspend fun startDeepReview(meetingId: String): DeepReviewJob =
        json.decodeFromString(call(req("/meetings/$meetingId/corrections/deep-review").post("{}".toRequestBody("application/json".toMediaType())).build()))

    suspend fun deepJob(id: String): DeepReviewJob = json.decodeFromString(call(req("/deep-review/$id").build()))

    /** The running or most recent review, if any (the hub answers `null` when there has been none). */
    suspend fun deepCurrent(): DeepReviewJob? {
        val body = call(req("/deep-review/current").build()).trim()
        return if (body == "null" || body.isEmpty()) null else json.decodeFromString(body)
    }

    /** Streams the recording to [target]; the whole file is fetched once and played locally so seeking is instant. */
    suspend fun downloadAudio(id: String, target: File) = withContext(Dispatchers.IO) {
        val slow = http.newBuilder().readTimeout(120, TimeUnit.SECONDS).build()
        slow.newCall(req("/meetings/$id/audio").build()).execute().use { response ->
            if (!response.isSuccessful) throw ApiException(response.code, errorDetail(response.body?.string().orEmpty()) ?: "Recording unavailable (${response.code})")
            val temp = File(target.parentFile, target.name + ".part")
            response.body!!.byteStream().use { input -> temp.outputStream().use { input.copyTo(it) } }
            if (!temp.renameTo(target)) throw IOException("could not store the recording")
        }
    }

    /** Reachy's voice as raw 16-bit mono PCM, delivered while the hub is still synthesizing; false when the hub cannot speak. */
    suspend fun speechStream(text: String, onRate: (Int) -> Unit, onPcm: (ByteArray, Int) -> Unit): Boolean = withContext(Dispatchers.IO) {
        val slow = http.newBuilder().readTimeout(60, TimeUnit.SECONDS).build()
        slow.newCall(req("/speech/stream").post(jsonBody(buildJsonObject { put("text", text.take(3000)) })).build()).execute().use { response ->
            val rate = response.header("X-Sample-Rate")?.toIntOrNull()
            if (!response.isSuccessful || rate == null) return@use false
            onRate(rate)
            val buffer = ByteArray(8192)
            response.body!!.byteStream().use { input ->
                while (true) { val n = input.read(buffer); if (n < 0) break; if (n > 0) onPcm(buffer, n) }
            }
            true
        }
    }

    suspend fun reminders(): List<Reminder> =
        json.decodeFromString(ListSerializer(Reminder.serializer()), call(req("/planner/reminders").build()))

    suspend fun addReminder(text: String, dueAtIso: String): Reminder =
        json.decodeFromString(call(req("/planner/reminders").post(jsonBody(buildJsonObject { put("text", text); put("due_at", dueAtIso) })).build()))

    suspend fun completeReminder(id: String) {
        call(req("/planner/reminders/$id/complete").post("{}".toRequestBody("application/json".toMediaType())).build())
    }

    suspend fun deleteReminder(id: String) { call(req("/planner/reminders/$id").delete().build()) }

    suspend fun editTask(id: String, text: String) {
        call(req("/planner/tasks/$id").put(jsonBody(buildJsonObject { put("text", text) })).build())
    }

    /** Sets the owner's own title and/or description; a title set here is never replaced by an automatic one. */
    suspend fun renameMeeting(id: String, title: String?, description: String?): Meeting =
        json.decodeFromString(call(req("/meetings/$id/title").put(jsonBody(buildJsonObject {
            title?.let { put("title", it) }; description?.let { put("description", it) }
        })).build()))

    /** Writes the title and description again from the transcript on the local model. */
    suspend fun describeMeeting(id: String): Meeting =
        json.decodeFromString(call(req("/meetings/$id/describe").post(jsonBody(buildJsonObject { put("model", "local") })).build()))

    suspend fun alarms(): List<Alarm> =
        json.decodeFromString(ListSerializer(Alarm.serializer()), call(req("/planner/alarms").build()))

    suspend fun stations(): List<Station> =
        json.decodeFromString(ListSerializer(Station.serializer()), call(req("/planner/stations").build()))

    /** [time] is "HH:MM" in the owner's time zone; the hub rings at its next occurrence on one of [repeat]. */
    suspend fun addAlarm(label: String, time: String, repeat: List<Int>, stationId: String?, volume: Int): Alarm =
        json.decodeFromString(call(req("/planner/alarms").post(jsonBody(alarmBody(label, time, repeat, stationId, volume))).build()))

    suspend fun updateAlarm(id: String, label: String, time: String, repeat: List<Int>, stationId: String?, volume: Int): Alarm =
        json.decodeFromString(call(req("/planner/alarms/$id").patch(jsonBody(alarmBody(label, time, repeat, stationId, volume))).build()))

    suspend fun setAlarmEnabled(id: String, enabled: Boolean): Alarm =
        json.decodeFromString(call(req("/planner/alarms/$id").patch(jsonBody(buildJsonObject { put("enabled", enabled) })).build()))

    suspend fun deleteAlarm(id: String) { call(req("/planner/alarms/$id").delete().build()) }

    private fun alarmBody(label: String, time: String, repeat: List<Int>, stationId: String?, volume: Int) = buildJsonObject {
        put("label", label); put("time", time); put("volume", volume)
        put("repeat", kotlinx.serialization.json.JsonArray(repeat.map { JsonPrimitive(it) }))
        put("station_id", stationId?.let { JsonPrimitive(it) } ?: kotlinx.serialization.json.JsonNull)
    }

    suspend fun clearCorrection(id: String, segment: Int): Meeting =
        json.decodeFromString(call(req("/meetings/$id/corrections/$segment").delete().build()))

    suspend fun receipts(): List<Receipt> =
        json.decodeFromString(ListSerializer(Receipt.serializer()), call(req("/planner/receipts").build()))

    // --- Document library (Phase 50). The same owner routes the web Documents page uses; the hub sets the access ceiling itself. ---

    private val documents = "/document-library/documents"

    suspend fun documentLibraryEnabled(): Boolean =
        json.parseToJsonElement(call(req("/document-library/config").build())).jsonObject["enabled"]?.jsonPrimitive?.booleanOrNull == true

    suspend fun documents(): List<DocumentItem> =
        json.decodeFromString(ListSerializer(DocumentItem.serializer()), call(req(documents).build()))

    suspend fun document(id: String): DocumentItem = json.decodeFromString(call(req("$documents/${enc(id)}").build()))

    /** Streams the picked file to the hub; [length] is the size when the provider knows it (else the upload is chunked). */
    suspend fun uploadDocument(
        name: String, contentType: String, length: Long, open: () -> java.io.InputStream?,
        title: String?, sensitivity: String, projectScope: String?,
    ): DocumentItem {
        val file = object : RequestBody() {
            override fun contentType() = contentType.toMediaType()
            override fun contentLength() = length
            override fun writeTo(sink: okio.BufferedSink) {
                (open() ?: throw IOException("The file could not be opened")).use { input -> sink.writeAll(input.source()) }
            }
        }
        val form = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", name, file)
            .addFormDataPart("sensitivity", sensitivity)
            .addFormDataPart("processing_priority", "normal")
        title?.takeIf { it.isNotBlank() }?.let { form.addFormDataPart("title", it.trim()) }
        projectScope?.takeIf { it.isNotBlank() }?.let { form.addFormDataPart("project_scope", it.trim()) }
        return json.decodeFromString(call(req(documents).post(form.build()).build()))
    }

    /** Only the fields given change; a null [projectScope] clears it when [clearProject] is set. */
    suspend fun patchDocument(id: String, title: String? = null, sensitivity: String? = null, projectScope: String? = null, clearProject: Boolean = false): DocumentItem =
        json.decodeFromString(call(req("$documents/${enc(id)}").patch(jsonBody(buildJsonObject {
            title?.let { put("title", it.trim()) }
            sensitivity?.let { put("sensitivity", it) }
            if (clearProject) put("project_scope", kotlinx.serialization.json.JsonNull) else projectScope?.let { put("project_scope", it.trim()) }
        })).build()))

    /** Reads the retained original again, at [tier] when given (the next extraction level up). */
    suspend fun reprocessDocument(id: String, tier: String?): DocumentItem =
        json.decodeFromString(call(req("$documents/${enc(id)}/reprocess").post(jsonBody(buildJsonObject { tier?.let { put("tier", it) } })).build()))

    suspend fun deleteDocument(id: String) { call(req("$documents/${enc(id)}").delete().build()) }

    suspend fun searchDocument(id: String, query: String): DocumentSearch =
        json.decodeFromString(call(req("$documents/${enc(id)}/search").post(jsonBody(buildJsonObject { put("query", query); put("limit", 10) })).build()))

    suspend fun summaries(id: String): List<DocumentSummary> =
        json.decodeFromString(ListSerializer(DocumentSummary.serializer()), call(req("$documents/${enc(id)}/summaries").build()))

    suspend fun startSummary(id: String, style: String, force: Boolean = false): DocumentSummary =
        json.decodeFromString(call(req("$documents/${enc(id)}/summaries").post(jsonBody(buildJsonObject { put("style", style); put("force", force) })).build()))

    /** A one-off question about one document, sent as an ordinary typed message; the hub keeps its history per document. */
    suspend fun askDocument(userId: String, documentId: String, text: String): Reply =
        json.decodeFromString(call(req("/messages").post(jsonBody(buildJsonObject {
            put("user_id", userId); put("channel", "web"); put("input_modality", "text"); put("text", text); put("context_document_id", documentId)
        })).build()))

    suspend fun inspectPage(id: String, page: Int): InspectPage = json.decodeFromString(call(req("$documents/${enc(id)}/inspect/pages/$page").build()))

    /** MinerU's picture of the original page, or of one block's crop when [block] is given (PNG or JPEG bytes). */
    suspend fun pageImage(id: String, page: Int, block: Int? = null): ByteArray = withContext(Dispatchers.IO) {
        val path = "$documents/${enc(id)}/inspect/pages/$page" + (block?.let { "/blocks/$it" } ?: "") + "/image"
        http.newCall(req(path).build()).execute().use { response ->
            if (!response.isSuccessful) throw ApiException(response.code, errorDetail(response.body?.string().orEmpty()) ?: "The picture is not available (${response.code})")
            response.body!!.bytes()
        }
    }

    /** Attaches, replaces (another id) or removes (null) the document a saved chat answers from. The hub holds it; the chat keeps it across restarts and devices. */
    suspend fun setChatDocument(userId: String, chatId: String, documentId: String?): ChatDocument? {
        val text = call(req("/chats/${enc(chatId)}/document").put(jsonBody(buildJsonObject {
            put("user_id", userId); put("document_id", documentId?.let { JsonPrimitive(it) } ?: kotlinx.serialization.json.JsonNull)
        })).build())
        return json.parseToJsonElement(text).jsonObject["document"]?.takeIf { it !is kotlinx.serialization.json.JsonNull }
            ?.let { json.decodeFromJsonElement(ChatDocument.serializer(), it) }
    }

    private fun enc(value: String) = java.net.URLEncoder.encode(value, "UTF-8").replace("+", "%20")
}
