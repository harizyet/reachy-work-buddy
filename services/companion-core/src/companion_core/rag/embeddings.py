"""Local embedding model — same graceful-degradation-without-cloud-keys
pattern as Phase 8's local STT/TTS: no cloud embeddings key was available,
so RAG embeds with a small local sentence-transformers model instead of an
external API. Loaded lazily (not at import time), since it's real ML
weights (~90MB, downloaded on first use) — same reason faster-whisper and
Silero VAD are loaded lazily elsewhere in this codebase, and why any test
that actually calls `embed`/`embed_one` is marked `slow`.
"""

from __future__ import annotations

from functools import lru_cache

EMBEDDING_DIM = 384
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return _model().encode(list(texts), normalize_embeddings=True).tolist()


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
