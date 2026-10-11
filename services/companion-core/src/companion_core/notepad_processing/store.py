"""Phase 49 stores: jobs, proposals and provenance. The in-memory twin has the same states and guarantees as the PostgreSQL store (postgres_store.py)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from companion_core.notepad_processing.models import (
    ACCEPTING_STALE_SECONDS,
    ACTIVE_JOBS,
    LEASE_SECONDS,
    Job,
    JobStatus,
    Kind,
    MeetingLink,
    Proposal,
    ProposalStatus,
    Provenance,
)
from shared.models.response import Privacy

OPEN_PROPOSALS = (ProposalStatus.PENDING, ProposalStatus.ACCEPTING)
RANK = {Privacy.PUBLIC: 0, Privacy.WORK_PRIVATE: 1, Privacy.SENSITIVE: 2}


@dataclass(frozen=True)
class Claim:
    outcome: str  # claimed | in_progress | done | closed | missing
    proposal: Proposal | None = None


@dataclass(frozen=True)
class Decision:
    outcome: str  # done | already | closed | missing
    proposal: Proposal | None = None


class NotepadStore(Protocol):
    async def enqueue(self, job: Job, *, force: bool) -> tuple[Job, bool]: ...
    async def get_job(self, job_id: str) -> Job | None: ...
    async def latest_job(self, note_id: str) -> Job | None: ...
    async def claim_next(self, now: datetime) -> Job | None: ...
    async def complete_job(self, job_id: str, proposals: list[Proposal], *, model: str, now: datetime) -> int: ...
    async def fail_job(self, job_id: str, error: str, *, now: datetime) -> None: ...
    async def retry_job(self, job_id: str, *, now: datetime) -> tuple[Job | None, str]: ...
    async def processed_note_ids(self) -> set[str]: ...
    async def list_proposals(self, *, note_id: str | None = None, statuses: tuple[ProposalStatus, ...] | None = None) -> list[Proposal]: ...
    async def get_proposal(self, proposal_id: str) -> Proposal | None: ...
    async def claim_accept(self, proposal_id: str, *, kind: Kind, text: str, due_at: datetime | None, sensitivity: Privacy, edited: bool, now: datetime) -> Claim: ...
    async def finish_accept(self, proposal_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Proposal | None: ...
    async def dismiss(self, proposal_id: str, *, now: datetime) -> Decision: ...
    async def close_for_note(self, note_id: str, *, now: datetime) -> int: ...
    async def stale_accepting(self, now: datetime) -> list[str]: ...
    async def add_provenance(self, provenance: Provenance) -> None: ...
    async def get_provenance(self, record_kind: str, record_id: str) -> Provenance | None: ...
    async def suggest_link(self, link: MeetingLink) -> MeetingLink: ...
    async def set_link(self, note_id: str, meeting_id: str, *, state: str, now: datetime) -> MeetingLink: ...
    async def list_links(self, *, note_id: str | None = None, meeting_id: str | None = None, states: tuple[str, ...] | None = None) -> list[MeetingLink]: ...
    async def drop_links(self, *, note_id: str | None = None, meeting_id: str | None = None) -> int: ...
    async def close(self) -> None: ...


class InMemoryNotepadStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._proposals: dict[str, Proposal] = {}
        self._provenance: dict[tuple[str, str], Provenance] = {}
        self._links: dict[tuple[str, str], MeetingLink] = {}
        self._assoc: dict[tuple[str, str], str] = {}  # (proposal id, note id) -> snapshot hash of that note's job

    async def enqueue(self, job: Job, *, force: bool) -> tuple[Job, bool]:
        for existing in self._jobs.values():
            if existing.note_id == job.note_id and existing.status in ACTIVE_JOBS:
                return existing, False
        if not force:
            for existing in self._jobs.values():
                if existing.note_id == job.note_id and existing.inputs_hash == job.inputs_hash and existing.status is JobStatus.SUCCEEDED:
                    return existing, False
        self._jobs[job.id] = job
        return job, True

    async def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def latest_job(self, note_id: str) -> Job | None:
        jobs = [j for j in self._jobs.values() if j.note_id == note_id]
        return max(reversed(jobs), key=lambda j: j.created_at, default=None)  # the latest inserted wins a tie

    async def claim_next(self, now: datetime) -> Job | None:
        ready = [j for j in self._jobs.values()
                 if j.status is JobStatus.QUEUED or (j.status is JobStatus.PROCESSING and j.lease_until is not None and j.lease_until <= now)]
        if not ready:
            return None
        job = min(ready, key=lambda j: j.created_at)
        self._jobs[job.id] = claimed = job.model_copy(update={
            "status": JobStatus.PROCESSING, "attempts": job.attempts + 1, "started_at": now, "lease_until": now + timedelta(seconds=LEASE_SECONDS)})
        return claimed

    async def complete_job(self, job_id: str, proposals: list[Proposal], *, model: str, now: datetime) -> int:
        job = self._jobs.get(job_id)
        if job is None or job.status is not JobStatus.PROCESSING:
            return 0
        known = {p.fingerprint for p in self._proposals.values() if p.note_id == job.note_id}
        added = 0
        for proposal in proposals:
            if proposal.source_key:
                same = next((x for x in self._proposals.values() if x.source_key == proposal.source_key), None)
                if same is not None:
                    # The same transcript passage was already proposed (by this note's earlier job or by another note linked to the meeting): keep one proposal and tie this note to it.
                    self._assoc.setdefault((same.id, job.note_id), proposal.snapshot_hash)
                    if same.status is ProposalStatus.PENDING and RANK[proposal.sensitivity] > RANK[same.sensitivity]:
                        self._proposals[same.id] = same.model_copy(update={"sensitivity": proposal.sensitivity})
                    continue
            if proposal.fingerprint in known:
                continue  # already proposed, accepted or dismissed for this note: reprocessing never brings it back
            known.add(proposal.fingerprint)
            self._proposals[proposal.id] = proposal
            self._assoc[(proposal.id, job.note_id)] = proposal.snapshot_hash
            added += 1
        self._jobs[job_id] = job.model_copy(update={"status": JobStatus.SUCCEEDED, "model": model, "proposal_count": added, "finished_at": now, "lease_until": None, "error": None})
        return added

    async def fail_job(self, job_id: str, error: str, *, now: datetime) -> None:
        job = self._jobs.get(job_id)
        if job is not None and job.status is JobStatus.PROCESSING:
            self._jobs[job_id] = job.model_copy(update={"status": JobStatus.FAILED, "error": error, "finished_at": now, "lease_until": None})

    async def retry_job(self, job_id: str, *, now: datetime) -> tuple[Job | None, str]:
        job = self._jobs.get(job_id)
        if job is None:
            return None, "missing"
        if job.status is not JobStatus.FAILED:
            return job, "not_failed"
        if any(j.note_id == job.note_id and j.status in ACTIVE_JOBS for j in self._jobs.values()):
            return job, "active"
        self._jobs[job_id] = queued = job.model_copy(update={"status": JobStatus.QUEUED, "error": None, "finished_at": None})
        return queued, "queued"

    async def processed_note_ids(self) -> set[str]:
        return {j.note_id for j in self._jobs.values() if j.status is JobStatus.SUCCEEDED}

    def _hydrated(self, p: Proposal) -> Proposal:
        return p.model_copy(update={"associations": {n: h for (pid, n), h in self._assoc.items() if pid == p.id}})

    async def list_proposals(self, *, note_id: str | None = None, statuses: tuple[ProposalStatus, ...] | None = None) -> list[Proposal]:
        rows = [self._hydrated(p) for p in self._proposals.values()
                if (note_id is None or (p.id, note_id) in self._assoc) and (statuses is None or p.status in statuses)]
        return sorted(rows, key=lambda p: (p.created_at, p.span_start))

    async def get_proposal(self, proposal_id: str) -> Proposal | None:
        p = self._proposals.get(proposal_id)
        return self._hydrated(p) if p is not None else None

    async def claim_accept(self, proposal_id: str, *, kind: Kind, text: str, due_at: datetime | None, sensitivity: Privacy, edited: bool, now: datetime) -> Claim:
        p = self._proposals.get(proposal_id)
        if p is None:
            return Claim("missing")
        if p.status is ProposalStatus.ACCEPTED:
            return Claim("done", p)
        if p.status is ProposalStatus.ACCEPTING:
            if p.accepting_at is not None and (now - p.accepting_at).total_seconds() < ACCEPTING_STALE_SECONDS:
                return Claim("in_progress", p)
            self._proposals[proposal_id] = p = p.model_copy(update={"accepting_at": now})  # taken over: the values stored at the first claim are used
            return Claim("claimed", p)
        if p.status is not ProposalStatus.PENDING:
            return Claim("closed", p)
        self._proposals[proposal_id] = p = p.model_copy(update={
            "status": ProposalStatus.ACCEPTING, "final_kind": kind, "final_text": text, "final_due_at": due_at, "sensitivity": sensitivity, "edited": edited, "accepting_at": now})
        return Claim("claimed", p)

    async def finish_accept(self, proposal_id: str, record_kind: str | None, record_id: str | None, *, now: datetime) -> Proposal | None:
        p = self._proposals.get(proposal_id)
        if p is None:
            return None
        if p.status is ProposalStatus.ACCEPTED:
            return p
        if p.status is not ProposalStatus.ACCEPTING:
            return None
        self._proposals[proposal_id] = done = p.model_copy(update={"status": ProposalStatus.ACCEPTED, "record_kind": record_kind, "record_id": record_id, "decided_at": now})
        return done

    async def dismiss(self, proposal_id: str, *, now: datetime) -> Decision:
        p = self._proposals.get(proposal_id)
        if p is None:
            return Decision("missing")
        if p.status is ProposalStatus.DISMISSED:
            return Decision("already", p)
        if p.status is not ProposalStatus.PENDING:
            return Decision("closed", p)
        self._proposals[proposal_id] = done = p.model_copy(update={"status": ProposalStatus.DISMISSED, "decided_at": now})
        return Decision("done", done)

    async def close_for_note(self, note_id: str, *, now: datetime) -> int:
        """The note is gone: untie it from its proposals, and dismiss each pending one that no remaining note still backs."""
        n = 0
        for key in [k for k in self._assoc if k[1] == note_id]:
            del self._assoc[key]
            p = self._proposals.get(key[0])
            if p is not None and p.status is ProposalStatus.PENDING and not any(pid == p.id for (pid, _) in self._assoc):
                self._proposals[p.id] = p.model_copy(update={"status": ProposalStatus.DISMISSED, "decided_at": now})
                n += 1
        return n

    async def stale_accepting(self, now: datetime) -> list[str]:
        return [p.id for p in self._proposals.values()
                if p.status is ProposalStatus.ACCEPTING and (p.accepting_at is None or (now - p.accepting_at).total_seconds() >= ACCEPTING_STALE_SECONDS)]

    async def add_provenance(self, provenance: Provenance) -> None:
        self._provenance.setdefault((provenance.record_kind, provenance.record_id), provenance)

    async def get_provenance(self, record_kind: str, record_id: str) -> Provenance | None:
        return self._provenance.get((record_kind, record_id))

    async def suggest_link(self, link: MeetingLink) -> MeetingLink:
        return self._links.setdefault((link.note_id, link.meeting_id), link)  # a pair already suggested, confirmed or rejected is left as it is

    async def set_link(self, note_id: str, meeting_id: str, *, state: str, now: datetime) -> MeetingLink:
        current = self._links.get((note_id, meeting_id))
        if current is None:
            current = MeetingLink(note_id=note_id, meeting_id=meeting_id, source="explicit", state=state, created_at=now, updated_at=now, decided_at=now)
        else:
            current = current.model_copy(update={"state": state, "updated_at": now, "decided_at": now})
        self._links[(note_id, meeting_id)] = current
        return current

    async def list_links(self, *, note_id: str | None = None, meeting_id: str | None = None, states: tuple[str, ...] | None = None) -> list[MeetingLink]:
        rows = [link for link in self._links.values() if (note_id is None or link.note_id == note_id) and (meeting_id is None or link.meeting_id == meeting_id)
                and (states is None or link.state in states)]
        return sorted(rows, key=lambda link: (link.created_at, link.meeting_id))

    async def drop_links(self, *, note_id: str | None = None, meeting_id: str | None = None) -> int:
        gone = [k for k, link in self._links.items() if (note_id is not None and link.note_id == note_id) or (meeting_id is not None and link.meeting_id == meeting_id)]
        for k in gone:
            del self._links[k]
        return len(gone)

    async def close(self) -> None:
        return None
