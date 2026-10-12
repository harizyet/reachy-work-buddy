from __future__ import annotations

import hashlib

TOKEN = "t0ken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def pdf_bytes(*pages: str) -> bytes:
    return b"%PDF-1.4\n" + "\f".join(pages).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


DOC_A = pdf_bytes("Page one\nThe retention requirement is 7 days.", "Page two\nThe retention requirement is 14 days.")


def test_health_is_open_and_reports_readiness_and_telemetry(client, engine):
    assert client.get("/health").json() == {
        "ok": True, "engine_ready": True, "telemetry_disabled": True, "tiers": ["flash", "basic", "standard", "advanced"], "detail": None,
    }
    engine.telemetry_disabled = False
    body = client.get("/health").json()
    assert body["ok"] is False and body["telemetry_disabled"] is False


def test_routes_need_the_token_and_fail_closed_without_one(client, settings, engine):
    assert client.get("/documents/doc1/status").status_code == 401
    assert client.get("/documents/doc1/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    from dataclasses import replace

    from document_worker.app import create_app

    unset = type(client)(create_app(replace(settings, token=""), engine))
    assert unset.get("/documents/doc1/status", headers=AUTH).status_code == 503


def test_ingest_registers_a_document_and_never_returns_a_path(client):
    r = client.upload("doc1", DOC_A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "ready" and body["source_hash"] == sha(DOC_A) and body["backend_ref"] == sha(DOC_A)[:7]
    assert "work" not in r.text and "source.pdf" not in r.text and "/data" not in r.text


def test_ingest_rejects_wrong_hash_type_size_and_extension(client):
    assert client.upload("d1", DOC_A, source_hash="0" * 64).json() == {"error": "hash_mismatch"}
    assert client.upload("d2", b"not a pdf at all", extension="pdf").json() == {"error": "content_type_mismatch"}
    assert client.upload("d3", pdf_bytes("x" * 5000)).status_code == 413
    assert client.upload("d4", DOC_A, extension="exe").json() == {"error": "unsupported_type"}
    assert client.upload("d5", DOC_A, tier="turbo").status_code == 422
    assert client.upload("d6", DOC_A, source_hash="xyz").json() == {"error": "bad_hash"}
    assert client.upload("../evil", DOC_A).status_code == 422
    # a rejected upload leaves nothing behind
    assert client.get("/documents/d1/status", headers=AUTH).status_code == 404


def test_ingest_is_idempotent_for_the_same_bytes_and_conflicts_otherwise(client):
    assert client.upload("doc1", DOC_A).status_code == 200
    assert client.upload("doc1", DOC_A).status_code == 200
    other = pdf_bytes("different")
    assert client.upload("doc1", other).json() == {"error": "document_id_in_use"}


def test_status_maps_backend_states(client, engine):
    engine.parse_status = "parsing"
    client.upload("doc1", DOC_A)
    assert client.get("/documents/doc1/status", headers=AUTH).json()["state"] == "processing"
    engine.docs[sha(DOC_A)]["status"] = "pending"
    assert client.get("/documents/doc1/status", headers=AUTH).json()["state"] == "queued"
    engine.docs[sha(DOC_A)]["status"] = "failed"
    body = client.get("/documents/doc1/status", headers=AUTH).json()
    assert body["state"] == "failed" and body["error_code"] == "parse_failed"


def test_page_limit_makes_a_ready_document_partial(client):
    many = pdf_bytes(*[f"p{i}" for i in range(8)])  # max_pages is 5 in the fixture
    body = client.upload("big", many).json()
    assert body["state"] == "partial" and body["page_limit_applied"] is True and body["page_count"] == 8


def test_search_ranks_the_named_documents_own_pages(client):
    other = pdf_bytes("Other\nThe retention requirement is 99 days.")
    client.upload("doc1", DOC_A)
    client.upload("doc2", other)
    body = client.post("/documents/doc1/search", headers=AUTH, json={"query": "retention requirement"}).json()
    assert body["complete"] is True
    assert {h["page"] for h in body["hits"]} == {1, 2}
    by_page = {h["page"]: h["snippet"] for h in body["hits"]}
    assert "retention requirement is 7 days" in by_page[1] and "retention requirement is 14 days" in by_page[2]
    assert all(h["locator"] == f"doc:{sha(DOC_A)[:7]}/tier:basic/page:{h['page']}" for h in body["hits"])
    assert "99" not in client.post("/documents/doc1/search", headers=AUTH, json={"query": "retention"}).text  # another document's text never appears


def test_search_scores_pages_so_the_page_that_answers_comes_first(client):
    pages = [f"Section {i}. Filler about topic {i}." for i in range(1, 7)]
    pages[3] = "Section 4. Vendors must retain security audit logs for ninety days. Logs are protected."
    pages[5] = "Section 6. The word logs appears once here."
    client.upload("doc1", pdf_bytes(*pages))
    hits = client.post("/documents/doc1/search", headers=AUTH, json={"query": "How long must audit logs be kept?", "limit": 3}).json()["hits"]
    assert hits[0]["page"] == 4 and "audit logs" in hits[0]["snippet"]  # the page with both terms outranks the page with one
    assert [h["page"] for h in hits if h["page"] == 6] in ([], [6])  # a weaker partial match may follow, never ahead


def test_search_finds_nothing_when_no_page_has_the_terms_and_never_guesses_a_page(client):
    client.upload("doc1", DOC_A)
    assert client.post("/documents/doc1/search", headers=AUTH, json={"query": "airspeed velocity swallow"}).json()["hits"] == []
    assert client.post("/documents/doc1/search", headers=AUTH, json={"query": "what is the of"}).json()["hits"] == []  # only filler words


def test_search_reports_incomplete_when_the_document_is_longer_than_the_worker_reads(client):
    many = pdf_bytes(*[f"Part {i} text" for i in range(8)])  # max_pages is 5 in the fixture
    client.upload("big", many)
    body = client.post("/documents/big/search", headers=AUTH, json={"query": "part"}).json()
    assert body["complete"] is False and max(h["page"] for h in body["hits"]) <= 5


def test_search_fails_closed_on_engine_error_without_leaking_the_message(client, engine):
    client.upload("doc1", DOC_A)
    engine.fail_with = "parse_failed /data/work/doc1/source.pdf"
    r = client.post("/documents/doc1/search", headers=AUTH, json={"query": "retention"})
    assert r.status_code == 502 and r.json() == {"error": "engine_error"} and "/data" not in r.text


def test_read_returns_page_content_with_locator_ranges(client):
    client.upload("doc1", DOC_A)
    body = client.get("/documents/doc1/read", headers=AUTH, params={"page_range": "2"}).json()
    ref = sha(DOC_A)[:7]
    assert "14 days" in body["content"] and body["ranges"] == [
        {"start": f"doc:{ref}/tier:basic/page:2", "end": f"doc:{ref}/tier:basic/page:2/block:2"}
    ]
    assert client.get("/documents/doc1/read", headers=AUTH, params={"page_range": "2;rm"}).json() == {"error": "bad_page_range"}
    assert client.get("/documents/doc1/read", headers=AUTH, params={"after": "doc:ffffff0/tier:basic/page:1"}).json() == {
        "error": "bad_cursor"
    }


def test_locator_of_another_document_is_not_found(client):
    client.upload("doc1", DOC_A)
    client.upload("doc2", pdf_bytes("zzz"))
    mine = f"doc:{sha(DOC_A)[:7]}/tier:basic/page:1/block:1"
    theirs = f"doc:{sha(pdf_bytes('zzz'))[:7]}/tier:basic/page:1/block:1"
    assert client.get("/documents/doc1/locator", headers=AUTH, params={"locator": mine}).status_code == 200
    assert client.get("/documents/doc1/locator", headers=AUTH, params={"locator": theirs}).json() == {"error": "not_found"}
    assert client.get("/documents/doc1/locator", headers=AUTH, params={"locator": "doc:../../etc"}).json() == {"error": "not_found"}


def test_read_before_ready_is_a_conflict(client, engine):
    engine.parse_status = "pending"
    client.upload("doc1", DOC_A)
    assert client.get("/documents/doc1/read", headers=AUTH).json() == {"error": "not_ready"}


def test_parse_with_force_invalidates_then_reparses(client, engine):
    client.upload("doc1", DOC_A)
    body = client.post("/documents/doc1/parse", headers=AUTH, json={"tier": "standard", "force": True}).json()
    assert engine.invalidated == [(sha(DOC_A)[:7], "standard")] and body["tier"] == "standard"
    assert client.post("/documents/doc1/parse", headers=AUTH, json={"tier": "turbo"}).status_code == 422
    assert client.post("/documents/doc1/parse", headers=AUTH, json={"tier": "advanced"}).json()["tier"] == "advanced"  # the quality-escalation tier is served like the others


def test_delete_removes_the_document_and_verifies(client, engine):
    client.upload("doc1", DOC_A)
    r = client.delete("/documents/doc1", headers=AUTH).json()
    assert r == {"document_id": "doc1", "deleted": True, "verified": True, "shared_hash_remaining": False}
    assert engine.docs == {}
    assert client.get("/documents/doc1/status", headers=AUTH).status_code == 404
    assert client.delete("/documents/doc1", headers=AUTH).json()["verified"] is True  # idempotent


def test_delete_of_one_of_two_identical_documents_keeps_the_other(client, engine):
    client.upload("doc1", DOC_A)
    client.upload("doc2", DOC_A)
    assert client.delete("/documents/doc1", headers=AUTH).json() == {
        "document_id": "doc1", "deleted": True, "verified": True, "shared_hash_remaining": True,
    }
    assert client.get("/documents/doc2/status", headers=AUTH).json()["state"] == "ready"
    assert client.post("/documents/doc2/search", headers=AUTH, json={"query": "retention"}).json()["hits"]
    assert client.delete("/documents/doc2", headers=AUTH).json()["shared_hash_remaining"] is False
    assert engine.docs == {}


def test_delete_keeps_the_record_when_the_backend_fails_so_it_can_be_retried(client, engine):
    client.upload("doc1", DOC_A)
    engine.fail_with = "engine_unavailable"
    assert client.delete("/documents/doc1", headers=AUTH).status_code == 502
    engine.fail_with = None
    assert client.get("/documents/doc1/status", headers=AUTH).status_code == 200
    assert client.delete("/documents/doc1", headers=AUTH).json()["verified"] is True


def test_page_range_is_sent_for_pdf_only(client, engine):
    client.upload("doc1", DOC_A)
    docx = b"PK\x03\x04 fake docx"
    assert client.upload("doc2", docx, extension="docx", tier="flash").status_code == 200
    assert engine.page_ranges == [(".pdf", "1-5"), (".docx", None)]


def test_a_worker_can_be_configured_without_the_advanced_tier(client, engine, settings):
    from dataclasses import replace

    from document_worker.app import create_app

    from shared.models.document_worker import WorkerTier

    limited = type(client)(create_app(replace(settings, tiers=(WorkerTier.FLASH, WorkerTier.BASIC, WorkerTier.STANDARD)), engine))
    assert limited.upload("doc1", DOC_A, tier="advanced").json() == {"error": "tier_not_enabled"}
    assert limited.get("/health").json()["tiers"] == ["flash", "basic", "standard"]


def test_inspect_page_returns_minerus_view_without_backend_identity(client):
    page1 = "Page one ![Chart block](doc:" + sha(b"x")[:7] + "/tier:basic/page:1/block:2) and a <b>tag</b>"
    data = pdf_bytes(page1, "Page two")
    client.upload("doc1", data)
    ref = sha(data)[:7]
    body = client.get("/documents/doc1/inspect/pages/1", headers=AUTH).json()
    assert (body["page"], body["page_count"], body["tier"], body["source_type"]) == (1, 2, "basic", "pdf")
    assert [(b["block"], b["type"], b["bbox"]) for b in body["blocks"]] == [(1, "text", [0.1, 0.1, 0.9, 0.2]), (2, "chart", None)]
    assert "#page-1-block-2" in body["markdown"] and "doc:" not in body["markdown"] and ref not in body["markdown"]
    assert "&lt;b>tag" in body["html"] and "<script" not in body["html"].lower()
    assert (body["width_pt"], body["height_pt"]) == (595.0, 842.0)
    assert client.get("/documents/doc1/inspect/pages/3", headers=AUTH).json() == {"error": "page_not_found"}
    assert client.get("/documents/doc1/inspect/pages/0", headers=AUTH).status_code == 422
    assert client.get("/documents/nope/inspect/pages/1", headers=AUTH).status_code == 404
    assert client.get("/documents/doc1/inspect/pages/1").status_code == 401


def test_inspect_images_come_from_the_backend_renderer_and_carry_safe_headers(client):
    client.upload("doc1", DOC_A)
    page = client.get("/documents/doc1/inspect/pages/2/image", headers=AUTH)
    assert page.status_code == 200 and page.headers["content-type"] == "image/png" and page.content == b"\x89PNG-fake-2-None"
    assert page.headers["cache-control"] == "no-store" and page.headers["x-content-type-options"] == "nosniff"
    block = client.get("/documents/doc1/inspect/pages/1/blocks/2/image", headers=AUTH, params={"format": "jpeg"})
    assert block.headers["content-type"] == "image/jpeg" and block.content.endswith(b"1-2")
    assert client.get("/documents/doc1/inspect/pages/1/blocks/99/image", headers=AUTH).json() == {"error": "asset_not_found"}
    assert client.get("/documents/doc1/inspect/pages/1/image", headers=AUTH, params={"format": "gif"}).status_code == 422
    assert client.get("/documents/doc1/inspect/pages/9/image", headers=AUTH).json() == {"error": "page_not_found"}
    docx = b"PK\x03\x04 fake docx"
    client.upload("doc2", docx, extension="docx", tier="flash")
    assert client.get("/documents/doc2/inspect/pages/1/image", headers=AUTH).json() == {"error": "no_page_image"}  # MinerU renders page images for PDFs and images only


def test_exports_are_minerus_outputs_and_rewrite_locators(client):
    data = pdf_bytes("Intro ![Fig](doc:" + sha(b"y")[:7] + "/tier:basic/page:1/block:3)", "Second page")
    client.upload("doc1", data)
    md = client.get("/documents/doc1/export", headers=AUTH, params={"format": "markdown"})
    assert md.status_code == 200 and md.headers["x-export-extension"] == "md" and md.headers["content-type"].startswith("text/markdown")
    assert "#page-1-block-3" in md.text and "Second page" in md.text and "doc:" not in md.text
    for kind, ext in (("content_list", "json"), ("middle_json", "json"), ("html", "html")):
        r = client.get("/documents/doc1/export", headers=AUTH, params={"format": kind})
        assert r.status_code == 200 and r.headers["x-export-extension"] == ext, kind
    assert client.get("/documents/doc1/export", headers=AUTH).headers["x-export-extension"] == "md"  # markdown by default
    assert client.get("/documents/doc1/export", headers=AUTH, params={"format": "pdf"}).status_code == 422
    assert client.get("/documents/doc1/export", params={"format": "markdown"}).status_code == 401


def test_inspector_fails_closed_on_engine_errors_without_leaking_messages(client, engine):
    client.upload("doc1", DOC_A)
    engine.fail_with = "parse_failed /data/work/doc1/source.pdf"
    for path in ("/documents/doc1/inspect/pages/1", "/documents/doc1/export"):
        r = client.get(path, headers=AUTH)
        assert r.status_code == 502 and r.json() == {"error": "engine_error"} and "/data" not in r.text
