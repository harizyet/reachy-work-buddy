package app.reachy.companion

import app.reachy.companion.data.ChatDetail
import app.reachy.companion.data.Citation
import app.reachy.companion.data.DocumentSummary
import app.reachy.companion.data.InspectBlock
import app.reachy.companion.data.Part
import app.reachy.companion.data.PersistentCookieJar
import app.reachy.companion.data.ReachyApi
import app.reachy.companion.data.blockAt
import app.reachy.companion.data.citedPages
import app.reachy.companion.data.cleanSnippet
import app.reachy.companion.data.describeBlock
import app.reachy.companion.data.needsWriting
import app.reachy.companion.data.shownSummaryStyle
import app.reachy.companion.data.pagesLabel
import app.reachy.companion.data.parseExtracted
import app.reachy.companion.data.sizeLabel
import app.reachy.companion.data.titleFromFilename
import app.reachy.companion.data.uploadContentType
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class DocumentsTest {
    private lateinit var server: MockWebServer
    private var stored: String? = null
    private lateinit var api: ReachyApi
    private val doc = """{"id":"d1","title":"Policy","filename":"policy.pdf","size_bytes":2048,"sensitivity":"work-private","project_scope":null,"state":"ready","tier":"basic","page_count":3,"error_code":null,"next_tier":"standard","unknown_field":1}"""

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        api = ReachyApi(server.url("/hub").toString(), PersistentCookieJar({ stored }, { stored = it }))
    }

    @After fun tearDown() = server.shutdown()

    private fun ok(body: String, code: Int = 200) = server.enqueue(MockResponse().setResponseCode(code).setBody(body).setHeader("Content-Type", "application/json"))
    private fun body(request: okhttp3.mockwebserver.RecordedRequest) = Json.parseToJsonElement(request.body.readUtf8()).jsonObject

    @Test fun `the library is listed and parsed from the hub's shape`() = runBlocking {
        ok("""{"enabled":true}"""); assertTrue(api.documentLibraryEnabled())
        assertEquals("/hub/document-library/config", server.takeRequest().path)
        ok("[$doc]")
        val item = api.documents().single()
        assertEquals("/hub/document-library/documents", server.takeRequest().path)
        assertTrue(item.usable); assertFalse(item.waiting); assertEquals("standard", item.nextTier); assertEquals(3, item.pageCount)
    }

    @Test fun `a document being read is waiting and cannot be used yet`() {
        val json = Json { ignoreUnknownKeys = true }
        for (state in listOf("uploaded", "queued", "processing")) {
            val d = json.decodeFromString(app.reachy.companion.data.DocumentItem.serializer(), """{"id":"x","title":"t","state":"$state"}""")
            assertTrue(state, d.waiting); assertFalse(state, d.usable)
        }
        val partial = json.decodeFromString(app.reachy.companion.data.DocumentItem.serializer(), """{"id":"x","title":"t","state":"partial"}""")
        assertTrue(partial.usable && partial.waiting)  // answerable so far, and still being read
    }

    @Test fun `an upload is a multipart post with the class and project, streamed from the picked file`() = runBlocking {
        ok(doc, 201)
        api.uploadDocument("policy.pdf", "application/pdf", 7, { "PDFDATA".byteInputStream() }, "Policy", "sensitive", "Alpha")
        val request = server.takeRequest()
        assertEquals("POST", request.method); assertEquals("/hub/document-library/documents", request.path)
        assertEquals("1", request.getHeader("X-Reachy-CSRF"))
        assertTrue(request.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        val text = request.body.readUtf8()
        assertTrue(text.contains("name=\"file\"; filename=\"policy.pdf\"") && text.contains("PDFDATA"))
        assertTrue(text.contains("name=\"sensitivity\"") && text.contains("sensitive") && text.contains("name=\"project_scope\"") && text.contains("Alpha"))
        assertFalse(text.contains("user_id") || text.contains("ceiling"))  // the phone claims no owner and no privacy ceiling
    }

    @Test fun `rename, classification, project and reprocess send only what changes`() = runBlocking {
        ok(doc); api.patchDocument("d1", title = " New ")
        server.takeRequest().let { assertEquals("PATCH", it.method); assertEquals("/hub/document-library/documents/d1", it.path); assertEquals("""{"title":"New"}""", it.body.readUtf8()) }
        ok(doc); api.patchDocument("d1", sensitivity = "public")
        assertEquals("""{"sensitivity":"public"}""", server.takeRequest().body.readUtf8())
        ok(doc); api.patchDocument("d1", clearProject = true)
        assertEquals("""{"project_scope":null}""", server.takeRequest().body.readUtf8())
        ok(doc); api.reprocessDocument("d1", "standard")
        server.takeRequest().let { assertEquals("/hub/document-library/documents/d1/reprocess", it.path); assertEquals("""{"tier":"standard"}""", it.body.readUtf8()) }
        ok(doc); api.reprocessDocument("d1", null)
        assertEquals("{}", server.takeRequest().body.readUtf8())
        server.enqueue(MockResponse().setResponseCode(204)); api.deleteDocument("d1")
        server.takeRequest().let { assertEquals("DELETE", it.method); assertEquals("/hub/document-library/documents/d1", it.path) }
    }

    @Test fun `a one-off question names the document and nothing about privacy or ownership`() = runBlocking {
        ok("""{"reply":"Seven days.","context_document":"Policy","citations":[{"document_id":"d1","title":"Policy","page":2},{"document_id":"d1","title":"Policy","page":2}]}""")
        val reply = api.askDocument("owner", "d1", "How long?")
        val sent = body(server.takeRequest())
        assertEquals("d1", sent["context_document_id"]!!.jsonPrimitive.content); assertEquals("text", sent["input_modality"]!!.jsonPrimitive.content)
        assertEquals(setOf("user_id", "channel", "input_modality", "text", "context_document_id"), sent.keys)
        assertEquals(listOf(2), citedPages(reply.citations)); assertEquals("Policy", reply.contextDocument)
    }

    @Test fun `search, summaries and the inspector use the document's own routes`() = runBlocking {
        ok("""{"hits":[{"snippet":"seven days","page":2,"locator":"x"}],"complete":false}""")
        val found = api.searchDocument("d1", "retention")
        server.takeRequest().let { assertEquals("/hub/document-library/documents/d1/search", it.path); assertEquals("retention", body(it)["query"]!!.jsonPrimitive.content) }
        assertEquals(2, found.hits.single().page); assertFalse(found.complete)
        ok("""{"id":"s1","style":"executive","status":"running","text":"","sections":[]}""")
        assertEquals("running", api.startSummary("d1", "executive").status)
        server.takeRequest().let { assertEquals("/hub/document-library/documents/d1/summaries", it.path); assertEquals("executive", body(it)["style"]!!.jsonPrimitive.content) }
        ok("""{"page":2,"page_count":3,"tier":"basic","page_image":true,"blocks":[{"block":1,"type":"text","bbox":[0.1,0.1,0.9,0.2]},{"block":2,"type":"table","bbox":null}],"markdown":"# T","html":"<script>x</script>"}""")
        val page = api.inspectPage("d1", 2)
        assertEquals("/hub/document-library/documents/d1/inspect/pages/2", server.takeRequest().path)
        assertEquals(2, page.blocks.size); assertNull(page.blocks[1].bbox)
        server.enqueue(MockResponse().setBody("PNGBYTES"))
        assertEquals("PNGBYTES", String(api.pageImage("d1", 2)))
        assertEquals("/hub/document-library/documents/d1/inspect/pages/2/image", server.takeRequest().path)
        server.enqueue(MockResponse().setBody("CROP"))
        api.pageImage("d1", 2, 5)
        assertEquals("/hub/document-library/documents/d1/inspect/pages/2/blocks/5/image", server.takeRequest().path)
    }

    @Test fun `the attachment is the hub's to set, replace and remove and read back with availability`() = runBlocking {
        ok("""{"document":{"id":"d1","title":"Policy","available":true}}""")
        assertEquals("d1", api.setChatDocument("owner", "c1", "d1")!!.id)
        server.takeRequest().let { assertEquals("PUT", it.method); assertEquals("/hub/chats/c1/document", it.path); assertEquals("""{"user_id":"owner","document_id":"d1"}""", it.body.readUtf8()) }
        ok("""{"document":null}""")
        assertNull(api.setChatDocument("owner", "c1", null))
        assertEquals("""{"user_id":"owner","document_id":null}""", server.takeRequest().body.readUtf8())
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"Document not found"}"""))
        try { api.setChatDocument("owner", "c1", "gone"); throw AssertionError("expected 404") } catch (e: app.reachy.companion.data.ApiException) { assertEquals(404, e.code); assertEquals("Document not found", e.message) }
    }

    @Test fun `a saved chat shows its attachment, the pages each answer used and a deleted document as unavailable`() {
        val detail = Json { ignoreUnknownKeys = true }.decodeFromString(
            ChatDetail.serializer(),
            """{"id":"c1","title":"T","document":{"id":"d1","title":"Policy","available":false},"turns":[{"text":"How long?","reply":"Seven days.","status":"complete","document":{"id":"d1","title":"Policy","available":true},"citations":[{"document_id":"d1","title":"Policy","page":3},{"document_id":"d1","title":"Policy","page":1}],"meeting_id":null}]}""",
        )
        assertFalse(detail.document!!.available)
        val lines = chatLines(detail)
        assertEquals(listOf(null, "Policy"), lines.map { it.document }); assertEquals(listOf(1, 3), lines[1].pages)
        assertEquals("pages 1, 3", pagesLabel(lines[1].pages)); assertEquals("page 2", pagesLabel(listOf(2)))
    }

    @Test fun `only PDF, DOCX, PNG and JPEG can be picked`() {
        assertEquals("application/pdf", uploadContentType("Report.PDF", null))
        assertEquals("image/jpeg", uploadContentType("scan.jpeg", "application/octet-stream"))
        assertEquals("image/png", uploadContentType("scan", "image/png"))
        assertNull(uploadContentType("notes.txt", "text/plain")); assertNull(uploadContentType("macro.docm", null)); assertNull(uploadContentType("setup.exe", "application/x-msdownload"))
        assertEquals("Annual report", titleFromFilename("Annual report.pdf")); assertEquals("a.b", titleFromFilename("a.b.docx"))
        assertEquals("2 KB", sizeLabel(2048)); assertEquals("1.5 MB", sizeLabel(1_572_864))
    }

    @Test fun `a tap picks the smallest block under it and blocks without a position are never hit`() {
        val blocks = listOf(
            InspectBlock(1, "text", listOf(0.0, 0.0, 1.0, 1.0)), InspectBlock(2, "table", listOf(0.2, 0.2, 0.6, 0.4)), InspectBlock(3, "figure", null),
        )
        assertEquals(2, blockAt(blocks, 0.3, 0.3)!!.block); assertEquals(1, blockAt(blocks, 0.9, 0.9)!!.block); assertNull(blockAt(blocks, 1.5, 0.5))
        assertEquals("From 20% across and 20% down; 40% wide, 20% tall", describeBlock(blocks[1])); assertEquals("No position", describeBlock(blocks[2]))
    }

    @Test fun `extracted markdown becomes headings, paragraphs and tables, and HTML is only ever text`() {
        val md = "# Policy\n\nRetention is\nseven days.\n\n| Item | Days |\n| --- | --- |\n| Logs | 7 |\n| Mail | 30 |\n\n<table><tr><th>A</th><td>x &amp; y</td></tr><tr><td>B</td><td><script>alert(1)</script>z</td></tr></table>\n\n## Next\nText"
        val parts = parseExtracted(md)
        assertEquals(Part.Heading(1, "Policy"), parts[0])
        assertEquals(Part.Paragraph("Retention is seven days."), parts[1])
        assertEquals(Part.Table(listOf(listOf("Item", "Days"), listOf("Logs", "7"), listOf("Mail", "30"))), parts[2])
        val html = parts[3] as Part.Table
        assertEquals("x & y", html.rows[0][1]); assertTrue(html.rows[1][1].contains("z"))
        assertEquals(Part.Heading(2, "Next"), parts[4]); assertEquals(Part.Paragraph("Text"), parts[5])
        assertTrue(parseExtracted("").isEmpty())
        assertEquals(Part.Paragraph("#hashtag"), parseExtracted("#hashtag").single())
    }

    @Test fun `citations are listed once each in page order`() {
        val cites = listOf(Citation("d", "T", 4), Citation("d", "T", 2), Citation("d", "T", 4))
        assertEquals(listOf(2, 4), citedPages(cites))
    }

    @Test fun `a search hit is shown as reading text without markdown, image references or table rules`() {
        assertEquals(
            "2. Termination Either party may terminate with ninety days. Figure 1: Incidents",
            cleanSnippet("## 2. Termination Either party may terminate with ninety days. Figure 1: Incidents ![Chart block](doc:a6c788a/tier:basic/page:2/block:4)"),
        )
        assertEquals("Gold · 2 hours · 4200 · Silver · 8 hours · 2800", cleanSnippet("…--- | --- | --- | | Gold | 2 hours | 4200 | | Silver | 8 hours | 2800 |"))
        assertEquals("plain text", cleanSnippet("  plain\n text "))
    }

    @Test fun `the summary style buttons choose what is shown and write only a style that has none`() {
        val ordinary = DocumentSummary(id = "s1", style = "ordinary", status = "ready", text = "Plain.")
        val technical = DocumentSummary(id = "s2", style = "technical", status = "ready", text = "Tech.")
        assertNull(shownSummaryStyle(null, emptyList()))                       // nothing yet: the screen says so
        assertEquals("ordinary", shownSummaryStyle(null, listOf(technical, ordinary)))  // before a choice, the first style that exists, in the buttons' order
        assertEquals("technical", shownSummaryStyle("technical", listOf(ordinary, technical)))
        assertEquals("executive", shownSummaryStyle("executive", listOf(ordinary)))      // chosen but still being written: the choice stands
        assertFalse(needsWriting("ordinary", listOf(ordinary)))                // pressing it shows it; the hub would return the same summary anyway
        assertTrue(needsWriting("executive", listOf(ordinary, technical)))      // pressing it starts one
        assertFalse(needsWriting("ordinary", listOf(ordinary.copy(status = "running", text = ""))))
    }
}
