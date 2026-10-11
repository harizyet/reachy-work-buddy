# Phase 47 Brain x Phase 49 provenance: `derived_from` edges (2026-10-11)

**Committed `d34ad51`; deployed to production 2026-10-11 10:08 UTC, see the [deployment record](phase-49-brain-provenance-deployment-2026-10-11.md).**

## Root cause (investigation, read-only)

Both accepted to-dos had a correct provenance row (`notepad_provenance`: "refactor clickhouse migration" -> note "My Task for next week", "spin up gitlab repo" -> note "GIT"), the knowledge index already held those records (indexing on, outbox empty), and the Brain already listed them as nodes. The Brain never read the provenance: `brain.edges_among()` was a hardcoded empty return ("no structured links exist yet"), written in Phase 47 before Phase 49 added the link. The API route, the hub proxy and the React client (which already maps `/brain/edges` and draws edges whose ends are loaded, by default only for the selected node unless "Show all links" is on) were correct. Not the cause: disabled indexing (the Brain does not use the index), a failed provenance write, serialization, or the frontend. The Brain is a knowledge visualization computed from the authoritative stores at request time, not the index and not a provenance graph.

## Change

* `NotepadStore.list_provenance(record_ids)`: read-only, in-memory and PostgreSQL.
* `brain.edges_among(ids, adapters, context, provenance)` emits `{id: "derived_from:<proposal id>", from: "task:<id>" | "reminder:<id>", to: "note:<id>", kind: "derived_from", basis}` from the provenance row only. An edge appears only if both ends are in the requested ids and both pass the node visibility check (`_visible_node`: exists now, visible in its store, within the owner's work-private ceiling). A restricted, deleted or unknown end yields no edge, no count and no id, and the response is identical to one for a missing record. Ids are deterministic (the proposal id) and duplicates are collapsed. The basis names the processed version (snapshot hash prefix) and never the note's text.
* `brain.summarise(..., provenance)` counts `len(edges_among(visible node ids))`, so the summary and the endpoint cannot disagree.
* `app.py`: `app.state.notepad_provenance` is set from an injected store, from the notepad store when processing is on, and otherwise from a **read-only** PostgreSQL store opened at startup, so historical provenance is readable with `NOTEPAD_PROCESSING_ENABLED=false` (no service, runner or route is created in that case). The `/brain/edges` and `/brain/summary` routes pass it in.
* No schema migration, no reindex, no model, no inference, no frontend change (the client ignores the extra `kind` field and uses id, from, to and basis), no proposal nodes: a pending proposal has no edge and the Brain's node types are unchanged.

Lifecycle: the provenance row has no foreign key and outlives edits (it names the version the task came from, so the edge and its id survive an edit of the note); deleting the note or the task makes an end invisible, so the edge disappears without deleting the row.

## Verification

* `test_brain_provenance.py` (new; each case runs with the flag off and on, 24 runs): accepted task -> visible note; accepted reminder -> note; three tasks from one note give three distinct edges; the real topology ("My Task for next week" -> "refactor clickhouse migration", "GIT" -> "spin up gitlab repo", nothing crossing and nothing to "Reachy Project"); restricted note or task (no edge, no trace, response identical to missing records); deleted note or task (no edge, provenance kept); edited note (same edge, same id, same basis); pending proposal (no edge, no node, summary 0); both ends must be requested; summary equals edges and repeated or duplicated requests give identical output with no duplicates; reading writes nothing and unprovenanced records get no edge; provenance written by the real `NotepadService.accept` shows in the Brain with processing off; no store at all fails closed. The pre-existing `test_brain.py` passes unchanged (33 passed together). With the Brain change removed, the new tests fail (24 failed).
* On a disposable PostgreSQL (container removed afterwards): `list_provenance` and the production lifespan, flag off and on, a restart, repeated identical responses, a restricted note and its task absent from the response and the summary, a pending proposal absent, nodes without a `proposal` type, reading wrote nothing, and deleting a note hides its edge while its provenance row remains (`test_the_brain_draws_derived_from_edges_from_real_provenance_with_the_flag_off_or_on`).
* Suites: companion-core with the PostgreSQL suites on: 2103 passed, 2 failed (`test_knowledge_index` reconcile and `test_knowledge_retrieval` historical mode: the known baseline failures, identical at the pre-Phase-49 commit); the four Phase 48 freeze tests pass (no frozen file changed); hub `test_web_client.py` 17 passed; ruff clean.

## Limits

* Edges exist only for tasks and reminders created through the Notepad review path (that is what provenance records). Tasks created by chat, the To Do page or the API have no note and get no edge.
* A single graph request is capped at 1,000 ids by the existing route; the summary counts over everything visible.
* In the 3D view an edge is drawn for the selected record unless "Show all links" is on, as for every edge.
* Deploying this is a core recreate (a Phase 48 boundary under the trial protocol) and needs the owner's approval; no hub or web change is needed.
