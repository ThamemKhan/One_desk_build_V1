"""
Knowledge Base Store — singleton that holds the live RAG index in memory.

Lifecycle:
  - Built once at startup from the seeded SQLite clauses.
  - Rebuilt in-place whenever /api/policies/upload ingests new documents.
  - All policy-check and exception-check callers read from _STORE.index.

SPEC §9: Retrieval is Hybrid BM25 + vector (hash_embed), fused via RRF k=60.
"""

from backend.rag.index import HybridIndex, build_index
from backend.db import SessionLocal

# Module-level singleton — replaced atomically on every upload.
_index: HybridIndex | None = None


def get_index() -> HybridIndex:
    """Return the live RAG index, building it lazily on first call."""
    global _index
    if _index is None:
        rebuild()
    return _index


def rebuild() -> HybridIndex:
    """Rebuild the RAG index from the current SQLite clauses table.
    Called at startup and after every admin document upload.
    Returns the new index (also sets the module-level singleton).
    """
    global _index
    session = SessionLocal()
    try:
        _index = build_index(session)
    finally:
        session.close()
    return _index
