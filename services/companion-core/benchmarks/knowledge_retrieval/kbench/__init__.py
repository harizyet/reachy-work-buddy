"""Phase 44 retrieval benchmark harness (docs/phase-44.md section 7). It scores any retrieval system that implements
`adapters.RetrievalAdapter` against frozen, synthetic fixtures. The harness knows nothing about the knowledge index, hybrid
retrieval or entities: those arrive in 44B to 44D as new adapters, judged by cases written before they existed."""

HARNESS_VERSION = "1.0.0"
