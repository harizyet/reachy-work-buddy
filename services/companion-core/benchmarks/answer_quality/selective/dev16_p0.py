"""The exact, predeclared P0 baseline configuration and its executor (Phase 44, acceptance infrastructure, 2026-10-10). P0 = today's retrieval and prompt plus the live 44H unclaimed-action boundary, answered by the
production 7B. It is the `b1a` arm of the dev15 pilot (`selective/pilot.py`) made explicit and checkable.

NO MODEL CALL IS MADE BY THIS MODULE AT IMPORT OR BY `effective()` / `verify_declared()`. `RealP0Executor` can call the model; the acceptance runner builds it only after every guard has passed and an explicit
execution authorisation exists. It has been exercised ONLY against a disposable mock HTTP service (health, model list, streamed completion) with a synthetic preparer; its production retrieval path (Postgres test corpus) and a real model server have not been exercised. `ReplayP0Executor` replays
already-consumed replies for rehearsals.

`DECLARED` holds every setting; `effective()` recomputes the same facts from the imported code (prompt texts, retrieval configuration, module source hashes, client constants). The runner refuses to run if they
differ, so the P0 that runs is the P0 that was declared.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AQ = HERE.parent
CORE = HERE.parents[1]
sys.path[:0] = [str(AQ), str(CORE / "knowledge_retrieval"), str(CORE / "src"), str(CORE.parents[1])]
CONFIG_PATH = HERE / "dev16_p0_config.json"

DECLARED = {
    "arm": "P0",
    "definition": "today's retrieval and prompt plus the 44H unclaimed-action boundary, production default model; the b1a arm of selective/pilot.py",
    "harness": {"class": "aq.conditions_g2.GConditions2", "condition": "b1a", "modifiers": [], "budget_tokens": 1500, "pilot_script": "selective/pilot.py (reference only; the acceptance runner calls the same steps)"},
    "model": {"client": "aq.llm.Local", "served_name": "reachy-local", "endpoint_default": "http://localhost:8003", "underlying": "Qwen2.5-7B (production default); the served name is verified from /v1/models at run time",
              "nothink": False, "stream": True, "stream_options": {"include_usage": True}},
    "decoding": {"temperature": 0, "seed": 44, "max_tokens": 350, "n": 1, "other": "server defaults; none overridden"},
    "retrieval": {"retriever": "companion_core.knowledge.retrieval.Retriever with RetrievalConfig B1A (lexical, no vector, no rerank)", "limit": 10, "temporal": "the case's temporal field",
                  "access": "the case's access profile through kbench.security.access_context", "revalidation": "retrieval-time revalidation (44B) as shipped", "index_prefilter": True,
                  "pinned_sources": "the case's attached meeting if any, else none", "sufficiency_gate": False, "conflict_flag": False, "coverage_note": False},
    "evidence_context": {"builder": "companion_core.knowledge.context.build_context", "header_version": "v1", "flag_instructions": True, "flag_conflicts": False, "note": None, "token_budget": 1500,
                         "token_counter": "the model server's /tokenize", "destination": "'cloud' if the profile allows it, else 'local'", "include_historical": "case.temporal == 'include_historical'", "clock_now": "2026-10-08T12:00:00+00:00",
                         "evidence_ids": "E1.. in the builder's order"},
    "input_order": {"messages": ["system: persona prompt", "system: action boundary instruction (44H)", "system: current date and time", "system: spoken-reply instruction (voice cases only)", "system/user: evidence block, immediately before the user turn", "user: the question"],
                    "evidence_order": "the builder's order of the retrieval bundle (no re-ranking by the harness)", "cases": "the frozen cases file order, one case at a time, no batching, no shuffling"},
    "output_schema": {"reply": "free text, at most 350 tokens, citing evidence ids as [E<n>]", "row": ["id", "family", "arm", "question", "reply", "manifest", "ms", "prompt_tokens", "completion_tokens", "finish_reason", "messages_sha256"],
                      "manifest": "{evidence id: {refs: [logical record refs], authorized: bool}} exactly as the builder rendered it", "labels": "none: P0 rows carry no outcome; flags come only from blinded human labels"},
    "runs": "exactly one P0 run per acceptance; no retries, no resumption, no second sample",
    "computed": "set by write_declared(): hashes of the prompt texts, the retrieval config and the source files below",
}

SOURCE_FILES = ["aq/conditions.py", "aq/conditions_g.py", "aq/conditions_g2.py", "aq/llm.py", "selective/pilot.py", "../knowledge_retrieval/kbench/security.py", "../knowledge_retrieval/kbench/fixtures.py",
                "../../src/companion_core/knowledge/retrieval.py", "../../src/companion_core/knowledge/context.py", "../../src/companion_core/knowledge/search.py", "../../src/companion_core/knowledge/revalidate.py",
                "../../src/companion_core/persona/context.py", "../../../../shared/models/persona.py"]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def effective() -> dict:
    """Recompute, from the imported code only, every fact the declaration pins. No network, no model."""
    from aq import llm
    from aq.conditions import NOW, base_messages
    from companion_core.knowledge.retrieval import B1A

    msgs = base_messages({"modality": "text", "question": "Q"})
    voice = base_messages({"modality": "voice", "question": "Q"})
    computed = {
        "system_message_sha256": [_sha(m["content"]) for m in msgs[:-1]], "voice_instruction_sha256": _sha(voice[-2]["content"]), "message_roles": [m["role"] for m in msgs],
        "clock_now": NOW.isoformat(), "retrieval_config_b1a": dataclasses.asdict(B1A),
        "client": {"model": llm.MODEL, "seed": llm.SEED, "nothink": llm.NOTHINK, "base_default_or_env": llm.BASE},
        "source_sha256": {rel: hashlib.sha256((AQ / rel).resolve().read_bytes() if not rel.startswith("selective/") else (HERE / rel.split("/", 1)[1]).read_bytes()).hexdigest() for rel in SOURCE_FILES},
    }
    return {**DECLARED, "computed": computed}


def write_declared() -> dict:
    cfg = effective()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=1, sort_keys=True) + "\n")
    return cfg


def verify_declared() -> list[str]:
    declared = json.loads(CONFIG_PATH.read_text())
    eff = json.loads(json.dumps(effective()))
    problems = [f"P0 configuration differs at {k}" for k in sorted(set(declared) | set(eff)) if declared.get(k) != eff.get(k) and k != "computed"]
    dc, ec = declared.get("computed", {}), eff["computed"]
    problems += [f"P0 computed fact differs: {k}" for k in sorted(set(dc) | set(ec)) if dc.get(k) != ec.get(k)]
    if dc.get("client", {}).get("nothink"):
        problems.append("P0 must run without the nothink switch")
    return problems


# --- executors --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

class ReplayP0Executor:
    """Replays already-consumed P0 replies (a rehearsal on development data). Makes no model call."""

    def __init__(self, rows: list[dict], config: dict | None = None):
        self.by_id = {r["id"]: r for r in rows}
        self._config = config
        self.calls = 0

    def effective_config(self) -> dict:
        return self._config if self._config is not None else json.loads(json.dumps(effective()))

    def open(self) -> None:
        pass

    def run_case(self, case: dict) -> dict:
        self.calls += 1
        r = self.by_id[case["id"]]
        return {"id": case["id"], "family": case["family"], "arm": "P0", "question": case["question"], "reply": r["reply"], "manifest": r["manifest"], "ms": r.get("ms", 0), "prompt_tokens": 0, "completion_tokens": 0,
                "finish_reason": "replay", "messages_sha256": "replay"}

    def close(self) -> None:
        pass


class RealP0Executor:
    """Calls the model server exactly as `selective/pilot.py` does for the `b1a` arm. Constructing it makes no call; `open()` and `run_case()` do.

    Two seams exist ONLY so the adapter can be exercised against a disposable mock service without production inference or a database; the defaults are the production path:
      `llm_factory`       builds the HTTP client (default `aq.llm.Local`, which reads `aq.llm.BASE` at construction)
      `preparer_factory`  builds the object whose async `prepare("b1a", case)` returns the messages and the evidence manifest (default: GConditions2 over the Postgres test corpus, as in pilot.py)
    `rehearsal_mock_port`, when given, makes `open()` REFUSE unless the client targets 127.0.0.1 on exactly that port, so a rehearsal can never reach a production or any other service."""

    def __init__(self, corpus_path: Path, *, llm_factory=None, preparer_factory=None, rehearsal_mock_port: int | None = None):
        self.corpus_path = Path(corpus_path)
        self.llm_factory, self.preparer_factory, self.rehearsal_mock_port = llm_factory, preparer_factory, rehearsal_mock_port
        self.llm = self.runner = self.env = self.loop = None
        self.served_models: list[str] = []
        self._env_before: str | None = None
        self._env_set = False

    def effective_config(self) -> dict:
        return json.loads(json.dumps(effective()))

    def _guard_target(self) -> None:
        if self.rehearsal_mock_port is None:
            return
        from urllib.parse import urlparse

        u = urlparse(str(self.llm.client.base_url))
        if u.hostname != "127.0.0.1" or u.port != self.rehearsal_mock_port:
            raise RuntimeError(f"rehearsal refused: the client targets {u.hostname}:{u.port}, not the disposable mock on 127.0.0.1:{self.rehearsal_mock_port}")

    def open(self) -> None:
        import asyncio
        import os

        self._env_before = os.environ.get("KBENCH_CORPUS", None)
        if self.preparer_factory is None:  # the production corpus builder reads this variable; it is restored in close()
            os.environ["KBENCH_CORPUS"] = str(self.corpus_path)
            self._env_set = True
        from aq import llm as llmlib

        self.loop = asyncio.new_event_loop()
        self.llm = self.llm_factory() if self.llm_factory else llmlib.Local()
        self._guard_target()
        if not self.llm.healthy():
            raise RuntimeError("the model server is not healthy")
        models = self.llm.client.get("/v1/models").json()
        served = {m.get("id") for m in models.get("data", [])}
        if DECLARED["model"]["served_name"] not in served:
            raise RuntimeError(f"the declared served model {DECLARED['model']['served_name']!r} is not served: {sorted(served)}")
        self.served_models = sorted(served)
        if self.preparer_factory is not None:
            self.runner = self.preparer_factory(self.llm)
            return
        from aq.conditions_g2 import GConditions2
        from companion_core.rag import embeddings
        from kbench.corpus import build_corpus
        from kbench.pg_env import build_pg_corpus
        from validate_scorer import PEOPLE

        spec = self.loop.run_until_complete(build_corpus()).spec
        embeddings.embed(["warm up"])
        self.env = self.loop.run_until_complete(build_pg_corpus(spec, embeddings.embed, embeddings._MODEL_NAME))
        self.runner = GConditions2(self.env, spec, self.llm, budget=DECLARED["harness"]["budget_tokens"], minilm_embed=embeddings.embed)
        self.runner.people = PEOPLE

    def run_case(self, case: dict) -> dict:
        prep = self.loop.run_until_complete(self.runner.prepare("b1a", case))
        done = self.llm.complete(prep.messages, max_tokens=DECLARED["decoding"]["max_tokens"])
        manifest = {eid: {"refs": list(e.refs), "authorized": e.authorized} for eid, e in prep.evidence.items()}
        return {"id": case["id"], "family": case["family"], "arm": "P0", "question": case["question"], "reply": done.text, "manifest": manifest, "ms": round(done.total_ms), "prompt_tokens": done.prompt_tokens,
                "completion_tokens": done.completion_tokens, "finish_reason": done.finish_reason, "messages_sha256": _sha(json.dumps(prep.messages, sort_keys=True))}

    def close(self) -> None:
        if self.env is not None and self.loop is not None:
            self.loop.run_until_complete(self.env.close())
        if self.llm is not None:
            self.llm.client.close()
        import os

        if self._env_set:
            self._env_set = False
            if self._env_before is None:
                os.environ.pop("KBENCH_CORPUS", None)
            else:
                os.environ["KBENCH_CORPUS"] = self._env_before
