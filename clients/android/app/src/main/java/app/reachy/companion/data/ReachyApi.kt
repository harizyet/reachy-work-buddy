package app.reachy.companion.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
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

    suspend fun saveNote(id: String?, title: String, body: String): Note {
        val payload = jsonBody(buildJsonObject { put("title", title); put("body", body) })
        val request = if (id == null) req("/planner/notes").post(payload) else req("/planner/notes/$id").put(payload)
        return json.decodeFromString(call(request.build()))
    }

    suspend fun deleteNote(id: String) { call(req("/planner/notes/$id").delete().build()) }

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

    suspend fun clearCorrection(id: String, segment: Int): Meeting =
        json.decodeFromString(call(req("/meetings/$id/corrections/$segment").delete().build()))

    suspend fun receipts(): List<Receipt> =
        json.decodeFromString(ListSerializer(Receipt.serializer()), call(req("/planner/receipts").build()))
}
