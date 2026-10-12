# Phase 50 extraction inspector deployment to the MS-01 (2026-10-12)

Owner authorization (2026-10-12): deploy the extraction inspector, with a prior check that the rendered HTML cannot run scripts, navigate the parent, load external resources or reach authenticated APIs, and with stop conditions. Code: commit `d316829` (the approved `e63b725` plus the sanitising and frame-policy hardening the owner asked for; clean checkout, 0 modified files). **Result: deployed, every check passed, no stop condition hit. Not yet accepted: the owner-authenticated browser pass is the owner's.** Design and reuse of MinerU: [inspector record](phase-50-extraction-inspector-2026-10-12.md).

| | Before | After |
|---|---|---|
| core | `d53f23512f7f` | `7abec2fd5c32` |
| hub (includes the new web bundle) | `6d98cd606d6e` | `7b8cf16b39ee` |
| document-worker | `fbb760daf100` | `67931dbfc4e6` |
| coding-agent, postgres, pgbouncer, vLLM, caddy, the rest | unchanged | unchanged |
| schema | `031_documents` | `031_documents` (no migration; the diff to the deployed commit touches no schema file and the new core image's head is still `031_documents`) |

## Hardening and the frame check (step 4, done before deploying)

The worker now rebuilds MinerU's HTML and stylesheet from an allowlist (`htmlsafe.py`; no scripts, frames, images, forms, link addresses, event handlers, inline styles or URLs; no `@import`, `url()` or `<` in CSS), the frame has an empty `sandbox`, an inline policy forbidding every fetch and form post and `<base>` href, `no-referrer` and a `_blank` base target. A real-browser check on a throwaway stack (real built app, real owner session, real worker) replaced the page HTML in flight with markup that tries every route out (scripts reading the parent and cookies, fetches including one of the authenticated documents API with exfiltration, XHR, popups, form submit, `top.location`, meta refresh, link and `@import`, onerror image, nested frame, object, embed, video, `<base href>`, clicks on a top-targeted and a plain link): 0 requests reached the listener, nothing ran with page access, no navigation, no popups, the parent could not read into the frame, none of the markup entered the page's DOM, a script tag in the Markdown tab was literal text; 18 of 18 on desktop and mobile. The ordinary inspector run still passed (36 checks). The deployed bundle contains the same frame policy strings (checked in the served JavaScript).

## Timeline (UTC, 2026-10-12)

| Time | Step |
|---|---|
| 04:17 | Existing backups checked valid (dump: 49 table-data entries; document-source archive intact). Documents had changed since (the owner's UAT document is stored), so fresh ones were taken: `~/reachy-backups/reachy-before-inspector-20261012-041721.dump` (320,958 bytes, 0600, sha256 prefix `916b14a65f4c5e10`, 51 table-data entries) and `reachy-document-source-before-inspector-20261012-041721.tar` (266,240 bytes, 0600; the one stored original's name equals its sha256). Rollback images tagged: `reachy-rollback/companion-core:pre-inspector` (`d53f23512f7f`) and `reachy-hub:pre-inspector` (`6d98cd606d6e`). The deployed worker image could not be re-tagged (its tag had been moved by local test builds and its content was collected), so `reachy-rollback/document-worker:pre-inspector` (`1f67f740e888`) was rebuilt from commit `56cd1e1`, the pinned lock and clean worktree it was deployed from (equivalent, not byte-identical). |
| 04:2x | Images built from the clean checkout before anything was stopped; frozen Phase 48 files hash-identical between the new core image and the running one. |
| 04:29:25 to :50 | Worker recreated alone (`--profile documents --no-deps`), healthy in 25 s. `verify-worker.sh` all ok except "published on one specific address" (the homelab worker publishes no port at all); telemetry disabled; Vulkan masked; GPU memory unchanged at 13,875 MiB; vLLM healthy (0 restarts). |
| 04:30:00 to :05 | Core stopped gracefully (exit 0, not OOM-killed), hub stopped, selective-shadow file copied, core and hub recreated (`up -d --no-build --no-deps`). **Downtime 10 s** (no migration, no PgBouncer wait). Both healthy at once; 0 tracebacks in core, hub, coding-agent and worker. |

## Verification on the deployed stack (core with the real worker and MinerU; the hub's trusted ceiling supplied as the hub does)

* **Existing document, read-only (step 8):** the owner's 5-page public document was inspected on every page without reprocessing or modifying it: 12 to 19 blocks per page each with a bounding box inside the page, MinerU's page pictures (200 to 300 KB PNG), block crops, provenance (tier, hash, `derived_extraction`), nothing in any response naming a MinerU path, a backend locator, a script, frame, image, form, URL or handler, clean 404s for an out-of-range page and block, all four exports (Markdown, scriptless HTML with a `sandbox` policy, content list and structured JSON, attachments), and the original downloaded with its sha256 equal to the recorded hash. Afterwards its state, tier, `updated_at`, page count, hash and summaries were identical.
* **Table, figure and layout (a 2-page probe with a table, a figure and a formula-like line):** blocks `paragraph_title`, `text`, `table`, `chart` with positions; a real `<table>` in the rendered HTML and in the HTML export; the table as Markdown; the figure reference rewritten to `#page-1-block-5` with no locator; crops of the table and of the figure.
* **Tier escalation:** Standard in 4 s and Advanced in 244.8 s (two pages; very slow on CPU, as documented); at each level the inspector showed the new tier, still extracted the table, kept the page count and drew the page; `next_tier` correctly ended at Advanced.
* **Ceilings and authorization:** a sensitive document got 403 on all five inspector routes at the default and at a public ceiling and 200 at the owner ceiling; a work-private document got 403 at a public ceiling; an unknown ceiling was 400; an unknown document 404. The hub answered 401 to anonymous requests and to the robot bearer on all five routes.
* **Source integrity:** with the stored original altered, inspect, page picture, export and original download all returned 409 with the integrity message (also for a second document sharing the bytes); after restoring the exact bytes the document inspected again.
* **Cleanup:** the three test documents were deleted; only the owner's original document remains.
* **Existing behaviour:** legacy `/documents` 200, tasks, notes, reminders and meetings unchanged, an ordinary chat turn and a task question answered correctly, the library on, the Phase 48 and 49 flags unchanged.
* **GPU and resources:** a 2-second sampler across the Standard and Advanced runs saw no GPU compute process other than vLLM's engine (the earlier one-off 106 MiB process did not recur); GPU memory stayed at 13,875 MiB; vLLM never restarted; the worker peaked at about 3.9 GiB of 6 GiB and about 420 percent CPU during Advanced.
* **Browser (anonymous only):** headless Chromium against the deployed `http://localhost:8080/hub/web/#/documents`, desktop and 390 px: redirect to sign-in, no errors, no overflow. The owner-authenticated page is the owner's UAT.
* **Tests before deploying:** 3,089 passed, 142 skipped, the four known baseline failures plus the timing-flaky embodiment wake test (it passed on three isolated reruns); web 270 passed; ruff and typecheck clean.

## Phase 48 boundary

New segment H from core start 04:30:07 UTC. Segment G (02:20:26 to 04:30:00) ended with capture counters `{"attempted":12,"excluded_channel":11,"excluded_attachment":1}`: 11 `probe-050` turns plus one turn with a document attached (the owner's acceptance test), which capture excludes by design (`excluded_attachment`). Shadow-file copy at the boundary: `~/reachy-backups/phase48-boundary-050/selective-shadow.cohortG-end.jsonl` (3,975 bytes, 0600). Segment H so far: `{"attempted":2,"excluded_channel":2}` (two `probe-050` regression probes). **Subtract 15 `probe-050` turns in total (2 in F, 11 in G, 2 in H)** from any 48B/48F window. No frozen file, router, registry, retrieval, evidence rule or answerer changed (hash-identical).

## Rollback assets (keep until the owner accepts the inspector)

Images `reachy-rollback/{companion-core,reachy-hub,document-worker}:pre-inspector`; the dump and archive above; the earlier Phase 50 assets remain. No schema or data rollback is involved. **Rollback:** tag the three `pre-inspector` images back as `reachy-homelab-companion-core:latest`, `reachy-homelab-reachy-hub:latest` and `reachy-document-worker:latest`, then `docker compose -p reachy-homelab --env-file .env --profile documents up -d --no-build --no-deps companion-core reachy-hub document-worker` (with `SEARXNG_SECRET_KEY` exported from its file). Documents, summaries and originals are untouched by either direction.

## Using it and limits

Open `http://10.180.1.23:8080/hub/web/#/documents` (LAN) or `http://100.107.155.34:8080/hub/web/#/documents` (tailnet), sign in as the owner, open a document and choose **Inspect extraction**. Limits accepted by the owner: formulas show as LaTeX source, and the locked frame cannot be scrolled to a block (select blocks on the page picture or the blocks table). Not verified: the owner's authenticated browser pass; large scanned documents; a document with real formulas or complex figures.
