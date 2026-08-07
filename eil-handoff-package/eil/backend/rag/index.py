import hashlib
import re
from dataclasses import dataclass
from typing import Optional

import chromadb
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from backend.models import Clause, Policy

EMBEDDING_DIM = 256


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def hash_embed(text: str) -> list[float]:
    """A small, fully offline embedding: feature-hash tokens into a fixed-size
    bag-of-words vector, L2-normalised. Chroma's default embedding function
    downloads an ONNX model from the internet on first use; this environment's
    network access is unreliable (see winget failures earlier in this build),
    so retrieval must not depend on that download succeeding.
    """
    vector = [0.0] * EMBEDDING_DIM
    for token in tokenize(text):
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % EMBEDDING_DIM
        vector[bucket] += 1.0
    norm = sum(v * v for v in vector) ** 0.5
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector


@dataclass
class IndexedClause:
    clause_ref: str
    policy_id: str
    version: str
    effective_date: str
    owner_dept: str
    policy_class: str
    tags: list[str]
    text: str
    tokens: list[str]


@dataclass
class HybridIndex:
    clauses: list[IndexedClause]
    bm25: Optional[BM25Okapi]
    collection: "chromadb.Collection"


def build_index(session: Session) -> HybridIndex:
    """Indexes the clauses table (SPEC §9): one chunk per clause row, never
    per document. Builds a BM25 index over clause text and an ephemeral
    Chroma collection over the same clauses, keyed by clause_ref.
    """
    rows = session.query(Clause, Policy).join(Policy, Clause.policy_id == Policy.id).all()

    indexed = [
        IndexedClause(
            clause_ref=clause.id,
            policy_id=policy.id,
            version=policy.version,
            effective_date=policy.effective_date,
            owner_dept=policy.owner_department_id,
            policy_class=policy.policy_class,
            tags=clause.tags or [],
            text=clause.text,
            tokens=tokenize(clause.text),
        )
        for clause, policy in rows
    ]

    bm25 = BM25Okapi([c.tokens for c in indexed]) if indexed else None

    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(name="clauses")
    if indexed:
        collection.add(
            ids=[c.clause_ref for c in indexed],
            embeddings=[hash_embed(c.text) for c in indexed],
            documents=[c.text for c in indexed],
            metadatas=[
                {
                    "clause_ref": c.clause_ref,
                    "policy_id": c.policy_id,
                    "version": c.version,
                    "effective_date": c.effective_date,
                    "owner_dept": c.owner_dept,
                    "policy_class": c.policy_class,
                    "tags_csv": ",".join(c.tags),
                }
                for c in indexed
            ],
        )

    return HybridIndex(clauses=indexed, bm25=bm25, collection=collection)
