# Phase 47: React web platform modernization and Brain visualization (plan)

Status: **plan approved by the owner 2026-10-08; 47A committed (`b5c5bd7`, branch `phase-47a`, pushed, not merged, not deployed); 47B1 to B3 (Planner, Notes, Activity) built on branch `phase-47b`, not merged, not deployed** (records in sections 13 and 14). B4 (alarms), WebRTC, the Brain API and any deployment need separate approval.

Numbering: the owner's brief called this "Phase 46". That number belongs to [Phase 46, least-privilege database roles](phase-46.md), so this is Phase 47 (owner decision D1, 2026-10-08: preserve Phases 44, 45 and 46).

Scope source: the owner's brief of 2026-10-08. Where the repository contradicts the brief, section 1 records the repository fact.

## 1. Repository findings that change the brief

| Brief assumed | Repository fact (verified 2026-10-08) | Consequence |
|---|---|---|
| Streaming chat and cancellation need migrating | Chat is request/response JSON (`POST /chats/{id}/messages`); cancellation is an `AbortController` on that fetch. No SSE, no WebSocket, no streaming in `clients/operator-ui/*.js` | No streaming work in 47B. The only streaming route (`POST /speech/stream`) belongs to the Android client |
| Memory management and document UI exists | **No operator-UI screen and no hub route** for memories or documents. Core has `/memories*` and `/documents*`; the hub exposes neither; Telegram `/recall` is the only surface | These are new features, not migrations. Out of 47B; listed as API gaps (section 7) |
| Hub OpenAPI can generate types | FastAPI serves `/openapi.json` (`FastAPI(title="reachy-hub")`), but only 29 `@app` decorators sit in `app.py`; most operator routes are registered by `install_operator_routes`, and several use ad hoc dict bodies. Generated types will be partial | Types are derived where the schema exists; hand-written zod/TS types for the rest, checked against fixtures (section 5) |
| Frontend has a build/test story to extend | **No build step.** [development.md](development.md) says "No frontend build dependency is required"; tests are 13 Playwright `node --test` files run with an external `NODE_PATH`; the hub Dockerfile `COPY`s `clients/` verbatim | Adding Node/Vite is a real change to the image build, CI and dev guide (section 6) |
| One UI to replace | Two static clients served by the hub: `clients/operator-ui` (`/ui/`, 6,365 lines incl. 13 tests) and `clients/web-pwa` (`/app/`, "Call Reachy" and telepresence, 453 lines, service worker) | web-pwa is in the inventory; its WebRTC pages are the highest-risk migration and are scheduled last |
| Working tree shared with other sessions | Clean at start (`git status`); a single worktree on `main`; HANDOVER warns another session works in this tree (Android) | Do the work on a branch in a separate worktree (section 9) |

Phase 44 state that bounds 47D/47E: indexing is **off** (`KNOWLEDGE_INDEXING_ENABLED=false`), 80 index rows exist for one meeting, retrieval is not wired to any route, and Phase 44 is paused ([HANDOVER](../HANDOVER.md)). Entities, relationships, and extraction (44C/44F) do not exist.

## 1a. Owner decisions (2026-10-08)

| # | Decision |
|---|---|
| D1 | Phase number is 47; Phases 44, 45 and 46 are preserved. |
| D2 | Multistage Docker build: a pinned Node.js stage with a lockfile builds the Vite bundle; only the static output is copied into the existing hub runtime image. No Node.js in the final runtime. |
| D3 | `HashRouter` during migration, React mounted at `/web/`; `/ui/` and `/app/` keep working. |
| D4 | A future read-only, source-backed Brain API is permitted independently of production knowledge indexing. It must enforce trusted owner authentication, authorization, source-state revalidation, sensitivity filtering and bounded pagination, behind an adapter contract that can later use the Phase 44 knowledge index. **Not implemented in 47A.** |
| D5 | `clients/web-pwa` is in the migration inventory and the final consolidation scope, but its implementation and `/app/` route are preserved initially. A React rewrite is deferred until separately justified and tested. |
| D6 | Memory Management and Document Management are new features on the roadmap (stage 47G), not parity migrations. They reuse governed backend APIs; backend gaps are listed in section 7a. Automatic memory capture is not part of this phase. |
| Scope | Only 47A was authorized. No deployment, production schema change, knowledge retrieval, Brain API, or 47B without further approval. |

## 2. Hosting, authentication, and API architecture (as built)

- **Serving.** The hub mounts `clients/operator-ui` at `/ui` and `clients/web-pwa` at `/app` through `RevalidatedStaticFiles` (`Cache-Control: no-cache`; added after a stale `app.js` ran against a new `index.html`). Caddy (`deploy/homelab/Caddyfile`, `:8080`) reverse-proxies `/hub/*` to `reachy-hub:8000` with the prefix stripped; `/core/*` is deliberately 404 except health. Browser paths are therefore **relative** (`new URL('../', location.href)`), which must survive a direct mount and the `/hub/` mount.
- **Owner session.** `POST /auth/login` sets the Starlette `SessionMiddleware` cookie `reachy_session` (SameSite=Strict, 12 h, `Secure` only if `SESSION_COOKIE_SECURE=true`). `POST /auth/logout` clears it and stops an owner-started robot microphone session. `GET /auth/me` is how the UI probes the session.
- **CSRF.** Every state-changing request must carry `X-Reachy-CSRF: 1` (`require_csrf`); there is no CORS grant, so the header forces a same-origin request.
- **Authorization.** `require_remote_auth` accepts either a bearer `REMOTE_UI_TOKEN` or the owner cookie (+CSRF on non-GET). Owner-recognition enrollment uses `require_owner_session` (cookie only, no bearer) plus fresh re-authentication. AGENTS.md states a browser login does not authenticate every legacy API endpoint; the React client must not imply otherwise.
- **Hub API surface used by the operator UI** is the proxy layer; core is never called from the browser. 401 anywhere returns the UI to the login panel (`showLogin()` clears state and resets every feature module).
- **State and storage.** No keys or transcripts in localStorage (AGENTS.md); `showLogin()` clears password and API-key inputs and every module's state. This is the behavior the React app must reproduce as "clear the query cache and component state on logout, on a 401, and on identity change".

## 3. Frontend inventory and migration matrix

Source of truth for 47B. `Tests` names the existing Playwright fixture file in `clients/operator-ui/tests/`; "none" means no regression test exists today, so 47B must write the **legacy** characterization test first. Status for every row is **not started**.

### 3.1 Application shell (`index.html`, `app.js`)

| Feature | Legacy source | Hub API | Tests | React target | Risk |
|---|---|---|---|---|---|
| Login panel, `me` probe, logout | `app.js` | `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` | `chat.test` (expiry), `workspace.test` | `app/auth`, route guard, `LoginPage` | Security-critical |
| Relative base path (direct and `/hub/`) | `app.js` `base` | n/a | `workspace.test` (mounts) | Vite `base: './'`, `HashRouter` or relative `basename` | High: wrong choice breaks the proxied mount |
| `api()` wrapper: no-store, same-origin credentials, CSRF header, 401 to login, error detail | `app.js` | all | indirectly all | `api/client.ts` | Security-critical |
| Upload variants (raw blob, multipart) | `apiUpload`, `apiUploadForm`, `apiDownload` | owner-recognition, meetings | `meeting_outputs`, `accounts` | `api/client.ts` helpers | Medium |
| View switching (10 views) and Settings sub-tabs (6) with ARIA roving tabindex | `app.js` `showView`, `showSettings` | n/a | `workspace.test` | `react-router` routes; `Tabs` primitive | Medium (keyboard behavior must be kept) |
| Notice (`aria-live`), deep-review banner | `app.js`, `meetings.js` | `GET /deep-review/current`, `/info` | `deep_review.test` | `NoticeProvider`, `DeepReviewBanner` | Low |
| Overview: status, robots, sessions, DND, audit, notifications, LLM usage, search usage | `app.js` | `GET /status`, `/robots`, `/sessions/{u}`, `PATCH /sessions/{u}/dnd`, `GET /audit/{u}`, `/notifications/{u}`, `/websearch/log` | `workspace.test`, `websearch.test` (partial) | `features/overview` | Medium; polling (see below) |
| Polling loop (overview) | `app.js` `polling` | as above | none | TanStack Query `refetchInterval`, paused when hidden | Medium |

### 3.2 Feature modules

| Feature | Legacy source | Hub API | Tests | React target | Risk |
|---|---|---|---|---|---|
| Chat: send, user switch, duplicate-send guard, failed-draft restore, late-reply discard, fresh-tab, abort, literal rendering | `chat.js` (488) | `POST /chats`, `POST /chats/{id}/messages`, `GET /chats?user_id=`, `GET/DELETE /chats/{id}`, `GET /sessions/{u}` | `chat`, `chat_history`, `chat_citations`, `websearch` | `features/chat` | **High**: the race tests are the spec; text must stay literal (no HTML) |
| Chat citations, meeting-as-context chip | `chat.js` | same | `chat_citations`, `meeting_outputs` | `features/chat` | Medium |
| Frontier-model override and reset | `app.js`/`chat.js` | `GET/PUT /settings/llm` | `chat` | `features/chat` | Medium |
| Meetings: list/search sidebar, create/upload (multipart), cancel, detail, delete, status wording, speakers, corrections, title/description, outputs (summary/minutes, rerun, delete), recording playback, click-a-line and per-line edit | `meetings.js` (714) | `/meetings`, `/meetings/{id}`, `/cancel`, `/speakers`, `/corrections/{i}`, `/outputs/{section}`, `/title`, `/describe`, `/meetings/{id}/audio` | `meeting_outputs`, `deep_review`, `workspace` (selection races) | `features/meetings` | **High**: largest module; audio via authenticated URL |
| Deep review (14B swap) start/progress/banner | `meetings.js` | `/deep-review/*` | `deep_review` | `features/meetings` | High: takes Reachy offline, needs confirm dialog |
| To Do (tasks) | `planner.js` | `/planner/tasks` | `planner` | `features/planner` | Low |
| Reminders | `planner.js` | `/planner/reminders` | `planner` | `features/planner` | Medium (time zone, see HANDOVER) |
| Alarms: list, add/edit sheet, repeat days, volume, station select, delete, stop | `alarms.js` (219) | `/planner/alarms`, `/planner/alarms/stop`, `/planner/stations*` | `alarms` | `features/alarms` | Medium; **stop alarm** is safety-adjacent |
| Radio station search (TuneIn) | `alarms.js` | `/planner/stations/search` | `alarms` | `features/alarms` | Low |
| Notes (folders, list, editor) | `notes.js` | `/planner/notes` | `notes` | `features/notes` | Low |
| Recent activity (receipts) | `activity.js` | `/planner/receipts` | `activity` | `features/activity` | Low |
| Voice: robot-voice start/stop/renew/wake, status poll | `voice.js` | `/robot-voice*` | `voice` (one known failing label assertion) | `features/voice` | **High**: lifecycle must end with logout (hub `on_logout`) |
| Motion settings (switches) | `app.js` | motion-settings routes | `motion` | `features/robot` | **High**: robot control; mind the AGENTS.md motion rules |
| Persona settings, tone | `app.js` | `/settings/persona` | `workspace` | `features/settings` | Low |
| Language-model routing, cloud key, hosted fallback | `app.js` | `/settings/llm` | `chat`, `workspace` | `features/settings` | **High**: secrets are write-only, inputs cleared on logout |
| Web-search policy, provider keys, usage and log dialog | `app.js` | `/settings/websearch`, `/websearch/log` | `websearch` | `features/settings` | High (keys) |
| Accounts: Google connect/complete/desktop/disconnect, calendars, selection, events, free-busy, Gmail search/preview | `accounts.js` (239) | `/settings/accounts/google/*` | `accounts` | `features/accounts` | **High**: OAuth return redirect is relative (`../../../ui/?google=return`) and constrains the router |
| Coding-agent credentials | `coding_agents.js` | `/coding-agents/providers/*/credential*` | `coding_agents` | `features/coding` | High (secret never echoed, only `last_four`) |
| Coding monitor: allowance, projects, sessions, events, usage, refresh, stop, terminal sessions | `coding_monitor.js` (164) | `/coding-agents/*` | `coding_agents` (credentials only) | `features/coding` | Medium; monitor has no tests, characterize first |
| Owner recognition: enrollment, benchmark dataset capture (mic/camera), fresh-reauth, download | `owner-recognition.js` (235) | `/owner-recognition/*` | none | `features/recognition` | **High**: cookie-only, re-auth, device capture; scheduled last in 47B |
| Destructive confirmations (single `confirm-dialog`) | `index.html` | n/a | per feature | shared `ConfirmDialog` | Security-relevant |

### 3.3 web-pwa (`/app/`)

| Feature | Legacy source | API | Tests | Target | Risk |
|---|---|---|---|---|---|
| Call Reachy (WebRTC audio), PWA manifest and service worker | `clients/web-pwa/app.js`, `sw.js` | `/webrtc/*` | none (browser) | Out of 47A to 47E; decide in 47F whether it joins the React app | High |
| Telepresence (camera, control, e-stop) | `telepresence.js` | `/webrtc/telepresence/offer`, `/robots/*` | none | Same | **High**: bearer/cookie auth, emergency stop |

### 3.4 Coverage gaps to close before migration

No tests exist for: Overview polling, coding monitor, owner recognition, telepresence, the PWA, the `/hub/` proxied mount for every feature, and a real (non-fixture) hub round trip. The 13 existing fixture files encode the legacy race and security behavior and become the parity specification; each ported feature must pass an equivalent Playwright case against **both** UIs where practical.

## 4. Architecture decisions (confirmed by D2/D3, built in 47A)

1. **Coexistence by mount, not replacement.** The React build is served at a new hub mount, `/web/` (Caddy `/hub/web/`), by a second `RevalidatedStaticFiles`. `/ui/` and `/app/` stay untouched until 47F. No existing route changes.
2. **Static output, no Node in production.** Vite builds to `clients/web/dist/` in a `node:22.22.1-slim` stage pinned by digest, with `npm ci` against the committed lockfile; the hub image copies only `dist`. Nothing generated is committed.
3. **Relative base.** Vite `base: './'` and `HashRouter` work under both `/web/` and `/hub/web/` with no server fallback route. Decided for the migration period (D3); revisit at 47F.
4. **Same auth, no new mechanism.** Cookie plus `X-Reachy-CSRF`, one fetch wrapper, 401 handling identical to `app.js`. No tokens in browser storage; no cache persistence plugin for TanStack Query. Query cache `clear()` on logout, on any 401, and on `me` returning a different user.
5. **Dependency discipline.** React, React Router, TanStack Query, Tailwind, Radix primitives (via shadcn/ui source copy, which adds no runtime dependency beyond Radix), Vitest, Testing Library, Playwright. Three.js/R3F/Drei are **only** added in 47C and lazy-loaded on the Brain route so the main bundle never pays for them. No state library, no CSS-in-JS, no second router.
6. **Playwright is already the house browser tool**, so it stays; Vitest replaces nothing (the legacy tests remain `node --test`).
7. **Vite dev proxy** to a hub run in development, so the dev server is same-origin for cookies and never needs CORS. No CORS loosening on the hub.
8. **Backend untouched in 47A to 47C.** No hub change except the static mount in 47A.

## 5. Proposed project structure (reconciled)

The brief's layout is accepted with these changes: the directory is `clients/web/` (does not collide: current siblings are `android`, `operator-ui`, `web-pwa`); `features/` is kept as proposed; `memory/` is **not** created in 47A (no API yet); `robot/` holds motion settings only until telepresence is decided.

```text
clients/web/
  package.json  tsconfig.json  vite.config.ts  tailwind config
  src/
    app/        App.tsx  router.tsx  providers.tsx  layout/
    api/        client.ts  auth.ts  errors.ts  types/ (generated + hand-written)
    components/ ui/ (shadcn)  shared/ (ConfirmDialog, EmptyState, ErrorState, Notice)
    features/   overview  chat  meetings  planner  alarms  notes  activity
                voice  robot  settings  accounts  coding  recognition  brain
    hooks/  styles/  utils/
  tests/        vitest setup; e2e/ (Playwright)
```

Type derivation (as built in 47A): the live OpenAPI schema was checked first. `/auth/me`, `/auth/login`, `/auth/logout` and `/status` are declared as bare `dict` responses, so the schema carries no field information and `openapi-typescript` would generate `{[key: string]: unknown}`; it was therefore not adopted. Instead `clients/web/src/api/` holds a snapshot of those operations from the real app (`openapi.json`), a real response sample (`samples.json`), hand-written types with runtime parsers (`types.ts`) that check exactly the fields the client reads, and `services/reachy-hub/tests/test_web_client.py`, which fails when the hub's response shapes or those OpenAPI operations drift from the snapshot. Regenerate with `python services/reachy-hub/tests/test_web_client.py`. Revisit generation if the hub gains typed response models (the better fix, and a backend change for the owner to decide).

## 6. Build, test and deployment impact

| Area | Change needed | Where documented |
|---|---|---|
| Hub image | Multi-stage Node builder; copy `clients/web/dist` to the runtime; hub mounts `/web` only if the directory exists (the pattern `/ui` and `/app` already use) | [deployment](deployment.md) |
| Dev guide | Replace "No frontend build dependency is required" with a scoped statement: legacy UI has none, `clients/web` needs Node 22 and `npm ci` | [development](development.md) |
| Tests | `vitest run`, `playwright test` for `clients/web`; legacy `node --test` unchanged; Ruff unaffected | development |
| Lockfile and index routing | `package-lock.json` committed; npm registry only, per the repo's dependency/index routing rules (read `development.md` before 47A) | development |
| Compose / Caddy | No Caddy change: `/hub/*` already proxies the new mount | n/a |
| Rollback | Remove the mount (or the dist directory); the old UI never stopped serving | 47F |

## 7. Brain Visualization: API gaps and security review

**Existing machinery (core, Phase 44B/44D):** unified index (`knowledge/index.py`), outbox and worker, `search.py` (B1a lexical, B1b hybrid), `retrieval.py`, and `revalidate.py`, which re-reads every candidate from its authoritative source, takes the stricter of index and source classification, then applies a trusted `AccessContext` and returns a `ContextBundle` plus counted drops. `memories` and `documents` have core routes; **the hub proxies none of this, and no route exposes the index.**

**Gaps (all backend, all deferred to 47D, none needed before):**

| Need | Gap | Smallest proposal |
|---|---|---|
| Node list | No listing of authorized knowledge items. Search needs a query; the graph needs a bounded enumeration | Core `GET /brain/nodes` (paged, `source_type`, `project_scope`, `time_range`, `sensitivity`, `q`), built on the existing adapters and `revalidate`; hub owner-cookie proxy `GET /brain/nodes` (read-only, no CSRF header needed for GET) |
| Node detail and provenance | `KnowledgeItem.provenance` exists in core, unreachable from the browser | `GET /brain/nodes/{id}`; text excerpt capped and sent as data, never rendered as HTML |
| Summary | No counts | `GET /brain/summary`: counts **computed after** access filtering and revalidation, never from raw index rows (a raw count leaks restricted records, the brief's "infer through counts" rule) |
| Edges | **No relationship store exists** (44C/44F are undecided) | `GET /brain/edges` returns only edges derivable from authoritative structured data that already exist (a task's `meeting_id`, a reminder's linked task, a note's folder). No inferred edges, no similarity edges. If a relationship type has no backing data the response says so and the UI shows "unavailable" |
| Source-type vocabulary | Brain tab clusters: memories, documents, meetings, notes, tasks, reminders | Use `SourceRef.kind` from core; do not invent categories |

**Rules carried into the contract.** Every node passes `revalidate` with the owner's `AccessContext` at request time, so forgotten, deleted, expired, hidden, and over-ceiling records are omitted and **not counted**; ids are opaque, stable per source reference, and not guessable; pagination is cursor-based with a server-side cap; no edge may reference a node the response omits; the reasons in `ContextBundle` drops are logged server-side as counts, never sent; owner-cookie authentication only (not bearer, matching the owner-recognition precedent), because the graph is a full personal-data view and `REMOTE_UI_TOKEN` is a robot-control credential; retrieved text is rendered literally and is never sent to a model by this feature.

**Does it need indexing enabled?** Not necessarily. `/brain/nodes` can enumerate from the source adapters (as `revalidate` already does) and keep `KNOWLEDGE_INDEXING_ENABLED=false`. Search (`q`) over the index would require it, or can fall back to the existing lexical `documents/search`/`memories/recall`. Enabling indexing remains a separate owner decision (Phase 44 paused). This is the main open question for 47D (section 11).

**Adapter contract (D4, design only; nothing built).** The Brain API depends on one internal interface, not on the index: `list_nodes(access: AccessContext, filters, cursor, limit) -> Page[KnowledgeItem]`, `get_node(access, id) -> KnowledgeItem | None`, and `list_edges(access, node_ids) -> list[Edge]`, where every implementation must return only items that passed source-state revalidation (existing, visible, not forgotten or expired) and the access filter, with `limit` capped server-side and the cursor opaque. The first implementation reads the authoritative source adapters directly. A later one may take candidates from the Phase 44 index and must still pass them through `revalidate`; swapping implementations must not change the HTTP contract. Authentication is the trusted owner session, resolved server-side into the `AccessContext`; the browser supplies filters only, never a sensitivity ceiling.

**Visual honesty.** Three explicit data classes in the scene and legend: decorative particles (never selectable, no tooltip), knowledge nodes (real records), edges (explicit only; the legend names the basis). Layout is deterministic (seeded by id) and the UI states that proximity carries no meaning. No fictional activity feed; "recent activity" is hidden until a real signal exists.

## 7a. Memory and Document Management: roadmap and backend gaps (D6)

New features, not parity migrations (the legacy UI has no such screens, section 1). Verified against `companion_core/app.py` routes on 2026-10-08:

| Area | Exists in core (not exposed by the hub) | Gap to close before the screen |
|---|---|---|
| Memories | `POST /memories` (optional `sensitivity`), `GET /memories`, `GET /memories/recall`, `POST /memories/{id}/request-forget` then `POST /memories/{id}/forget/confirm` (ADR 0011 two-step consent), `POST /memories/{id}/restore` | Hub owner-cookie proxies; no edit or reclassify route; confirmation must stay explicit, never a one-click bypass |
| Documents | `POST /documents` (with `sensitivity`, `project_scope`), `GET /documents` (returns names only), `GET /documents/search` | **No document deletion route. No classification change route. No document detail or chunk listing.** Each is a backend feature needing its own review; the UI cannot offer them until they exist |
| Capture | none to add | Automatic memory capture is out of scope for the frontend phase; the screens create or forget only on an explicit owner action |

## 8. Stages, scope, and acceptance gates

Each stage is its own branch, commit(s), verification record, and acceptance gate; none is deployed without separate owner authorization. Backend, frontend, and infrastructure changes are never combined in one deployment.

| Stage | Scope | Gate |
|---|---|---|
| **47A** Foundation | See section 10 | Section 10 gate |
| **47B** Migration, in this order | Overview, Planner (tasks, reminders), Notes, Activity, Alarms, Settings (persona, models, search), Chat, Meetings, Voice and motion, Accounts, Coding, Recognition. Each feature: characterize legacy test, port, equivalent Playwright test, privacy/authorization check, mark migrated in section 3 | Matrix has no "not started" row except those the owner defers; both UIs pass; no regression in the 13 legacy suites |
| **47C** Brain 3D foundation | Synthetic data only, lazy-loaded route: instanced particles, nodes, lines, camera, search, filters, legend, details panel, reduced-motion, WebGL-fallback list view, hidden-tab pause, dispose on unmount | Measured: frame rate on integrated graphics, memory after 10 mount/unmount cycles, bundle delta; Playwright covers fallback and keyboard path; no network calls |
| **47D** Real knowledge | Section 7 backend (core then hub, read-only, no schema change), adapter replacing the synthetic source | Core and hub tests for: forgotten, deleted, expired, reclassified, over-ceiling, cross-scope records never appear and never change a count; reproducible pagination; indexing flag unchanged; existing retrieval tests unchanged |
| **47E** Relationships and activity | Only what the data supports (explicit links); inferred/reviewed/disputed shown as "unavailable" unless 44C/44F are separately approved | Every displayed edge cites its source data; no edge without backing |
| **47G** Memory and Document Management (new features) | See section 7a. Needs its own consent review and any backend gaps closed first; sequenced by the owner, independent of 47C to 47E | Governed reads and writes only through existing consent paths; no automatic capture; tests for forgotten/restore and classification display |
| **47F** Cutover | web-pwa consolidation per D5 only if separately justified; hub serves React at `/ui/` (or redirects); legacy retained at a rollback path | Rollback rehearsed on a disposable project; parity matrix complete; owner approves; legacy not deleted |

Non-goals are as in the brief (no core rewrite, no model or auth policy change, no enabling Phase 44 retrieval, no GraphRAG or Neo4j, no robot or Android changes).

## 9. Risks

| Risk | Mitigation |
|---|---|
| Relative-path/mount regression (direct vs `/hub/`) broke before | Playwright runs the same suite against both mounts; `HashRouter`; OAuth return path tested |
| Auth regressions (cookie, CSRF, 401, logout, cache) | One fetch wrapper with unit tests; logout clears TanStack cache and local state; a Playwright test asserts no sensitive text remains in the DOM or storage after logout |
| Stale-asset-after-deploy (already happened) | Hashed Vite filenames plus `no-cache` `RevalidatedStaticFiles` for `index.html` |
| Race behavior in chat/meetings is subtle | Port the legacy race tests first; they are the specification |
| Toolchain adds supply-chain and image-size surface | Lockfile, exact registry, builder stage only, `npm audit` result recorded, no postinstall surprises |
| Bundle bloat from three.js | Lazy route; budget set from measured numbers in 47A/47C |
| Shared working tree | Separate git worktree and branch; stage files explicitly; never `git add -A`; never touch uncommitted Android/hub edits |
| Robot-control UI regressions | Motion and voice ported late, with explicit stop/disarm tests; AGENTS.md motion rules apply to any live test |
| WebGL on weak hardware / the homelab has no discrete GPU in the browser's machine | Fallback list view; reduced motion; measure on integrated graphics |
| "Fake" knowledge density | Hard rule in section 7; synthetic data labelled in the UI during 47C |

## 10. Smallest safe 47A slice

1. Create a worktree/branch; add `clients/web/` (Vite, React, TypeScript, Tailwind, Router, Query, Vitest, Playwright). Nothing under `clients/operator-ui` or `web-pwa` changes.
2. One hub change: mount `clients/web/dist` at `/web` if present (same pattern as `/ui`), and a Dockerfile builder stage. A hub test asserts `/web/` serves and `/ui/` is unchanged.
3. App shell with responsive navigation and the **login/guard/logout** path only, plus one real read-only page: **Overview** (`GET /status`) to prove API, polling, error and empty states. No other feature.
4. Typed client: `fetch` wrapper identical in behavior to `api()`; generated types from the OpenAPI snapshot; unit tests for CSRF header, 401 handling, error detail, and cache clearing.
5. Playwright: login, protected-route redirect when logged out, logout then back-navigation shows no data, expiry mid-session, desktop and mobile widths, and the same run through a `/hub/`-style prefix proxy.
6. Docs: this page's matrix updated, the development guide's build statement, the verification record, a roadmap row. HANDOVER updated last.

**47A acceptance gate.** The React app loads independently at `/web/`; legacy `/ui/` and `/app/` unchanged (existing `node --test` suite and hub tests still pass, with the pre-existing failures named); login/logout works and logout clears cache; protected routes unreachable unauthenticated; Overview works through the existing hub route under both mounts; component and browser tests pass and are recorded with actual counts; Ruff clean; no hub route other than the static mount added; bundle size and load time recorded as the baseline for budgets. No deployment.

## 11. Decisions

Resolved by D1 to D6 (section 1a). Still open for later stages: whether `/brain/nodes` search may use the index (47D; D4 permits a source-backed design first), the 47F cutover shape, and the go-ahead for 47B.

## 12. Verification of this page

Planning only, no code run. Facts were taken from `HANDOVER.md`, `AGENTS.md`, `docs/README.md`, `docs/development.md`, `docs/phase-44.md`, `docs/phase-46.md`, `deploy/homelab/Caddyfile`, `services/reachy-hub/Dockerfile`, `services/reachy-hub/src/reachy_hub/app.py` and `operator.py`, `clients/operator-ui/*.js` and `index.html`, `clients/web-pwa/`, and `services/companion-core/src/companion_core/knowledge/`. The route list in section 3 comes from string-literal extraction over the legacy scripts and was not cross-checked against the live OpenAPI schema; 47A's first task is to regenerate it from `openapi.json` and reconcile any difference. The matrix lists tests by file name and was not re-run in this session.

## 13. 47A record (2026-10-08)

Built on branch `phase-47a` in a separate worktree; nothing deployed. Layout as built: `clients/web/` with `src/{app,api,components,features,styles}`, `tests/` (Vitest), `e2e/` (Playwright against a real in-process hub); one hub change (the `/web` mount in `app.py`), the Dockerfile Node stage, `.dockerignore` entries, and `services/reachy-hub/tests/test_web_client.py`. Only login, guard, logout and Overview exist; every other matrix row is still **not started**. Results, bundle sizes and the API compatibility check are in the [47A verification record](verification/phase-47a-2026-10-08.md). Deviations from the plan: `openapi-typescript` was dropped (section 5); shadcn/Radix were not adopted because 47A needs only a button, card, pill and spinner (they remain the intended primitive source once dialogs and menus arrive in 47B); the Overview shows components and model-usage totals but not the per-call usage table, sessions, DND, audit or notifications, which belong with the chat/session work.

## 14. 47B record (2026-10-08): B1 Planner, B2 Notes, B3 Activity

Authorized by the owner on 2026-10-08 as local development only: B1 tasks and reminders, B2 notes, B3 activity. Branch `phase-47b`, from the pushed 47A commit. Not B4 (alarms), not WebRTC, not the Brain API, no deployment, no backend authorization or knowledge-flag change. Evidence: [47B verification](verification/phase-47b-2026-10-08.md).

Method for each feature: (1) pin the hub behaviour with tests through the real owner-session chain (`test_web_client.py::test_planner_*`), next to the existing legacy fixture tests; (2) implement the React page; (3) hold it to the same cases with component tests (the legacy cases are reproduced one for one) and Playwright against the real hub; (4) cross-check with the legacy UI on the same hub.

### Feature-parity status

| Matrix row | React | Parity evidence | Status |
|---|---|---|---|
| To Do (open list, round check, completed section, inline add that stays open, inline rename, delete, refresh, empty and error states, literal text) | `/todo` | `planner.test.tsx`; `planner.spec.ts` (both mounts, both widths); legacy `planner.test.cjs` cases reproduced; legacy-to-React round trip | **Migrated, pending owner acceptance** |
| Reminders (earliest first, due text, overdue marker, completed section with disabled tick, New Reminder sheet with next whole hour, delete) | `/reminders` | same; due text compared with the legacy row for the same record | **Migrated, pending owner acceptance** |
| Notes (date sections, preview, search on the server, debounced autosave, serialised save, no blank note, title fallback, flush on switch, delete with confirmation, narrow-screen list/editor/back) | `/notes` | `notes.test.tsx`; `planner.spec.ts`; legacy-note round trip | **Migrated, pending owner acceptance** |
| Recent activity (receipts newest first, failed struck through with reason, fields, empty and error states) | `/activity` | `activity.test.tsx`; `planner.spec.ts` against hub receipts | **Migrated, pending owner acceptance** |

"Migrated" here means built and tested, not owner-accepted: the legacy tabs stay the fallback and nothing is deployed.

### Deliberate differences from the legacy UI

- Navigation is links in the app header, not tab buttons; the legacy workspace tab bar is unchanged.
- The Notes toolbar spans the top of the page rather than sitting in the editor pane, so New note is reachable on a narrow screen while the list is showing. This was found by the browser suite: the component tests (jsdom, no CSS) passed while the button was hidden at phone width.
- Leaving the Notes page while signed in saves a pending edit; the legacy tab kept its timer running instead. On sign-out, session expiry or a new sign-in an unsaved edit is dropped, not sent.
- Deleting a task or reminder has no confirmation, as in the legacy UI (only notes confirm). Not changed in a parity migration; see the gaps below.

### Authentication-generation isolation

`api/client.ts` keeps a generation counter. Sign-in, sign-out and a 401 advance it; every request records the generation it started in and aborts with `StaleSessionError` if it finishes in a later one, before any caller sees the answer. Advancing also aborts everything in flight. A 401 for an older generation never runs the sign-out handler, so a late 401 cannot end a newer sign-in. The Notes editor ties "still the same session" to the generation rather than to React state, because state lags the unmount that triggers its last flush (a mutation test showed an unsaved edit being sent after sign-out began until this was fixed). Regression tests: `session.test.tsx` (10 cases, 11 runs: list answered after logout, with and without the abort taking effect; answered after a 401 expiry; slow `/auth/me` against an expiry; late 401 against a newer sign-in; late success against a different owner's session; the next session's empty cache while loading; a mutation answered after logout; unsaved and in-flight note saves at logout; the save-on-leave case), `client.test.ts` (request-layer cases), and `planner.spec.ts` (a real browser: the in-flight list request is cancelled, its late answer is ignored, back-navigation shows nothing). Each of the five protections was broken on purpose and a test failed.

### API gaps and decisions needing separate approval

1. Operator routes return bare dicts, so OpenAPI has no response fields (47A finding). The planner responses are checked by parsers and a hub drift test. Typed response models in the hub would remove the hand-written layer; that is a backend change.
2. Hub validation errors for bodies (422) return `detail` as a list, which the client shows as "Request failed (422)", as the legacy UI does. A readable message needs a hub change.
3. Reminders cannot be edited or reopened (no hub route). Notes and tasks have no reclassification route by design (`_NoReclassification`).
4. Deleting tasks and reminders is immediate in both UIs. Whether to add the confirmation ADR 0011 describes for destructive actions is an owner decision, not a parity task.
5. Hub receipts are read-only and only the 100 newest are returned by default; there is no paging route.
6. Notes search is a server call on every pause; there is no result limit parameter.

None of these was changed. The 47B stage added no hub route, no schema change and no flag change.
