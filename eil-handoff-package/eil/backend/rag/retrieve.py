from backend.rag.index import HybridIndex, hash_embed, tokenize

RRF_K = 60

# SPEC gives no numeric cutoff. With k=60 dominating the small per-service
# clause counts in this corpus, every fused RRF score for a service that has
# ANY eligible clauses lands in a narrow band close to 2/(60+N) .. 2/61 — the
# threshold can't meaningfully discriminate "relevant" from "irrelevant"
# within that set. The threshold is kept as a low sanity floor (an eligible
# clause set can never score below this); the real trigger for an empty
# result is having zero clauses tagged with the service_id at all.
MIN_SCORE_THRESHOLD = 1 / (RRF_K + RRF_K)


def _rank_bm25(index: HybridIndex, query_tokens: list[str], eligible_refs: set[str]) -> dict[str, int]:
    if index.bm25 is None:
        return {}
    scores = index.bm25.get_scores(query_tokens)
    scored = [
        (clause.clause_ref, scores[i])
        for i, clause in enumerate(index.clauses)
        if clause.clause_ref in eligible_refs
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return {clause_ref: rank + 1 for rank, (clause_ref, _) in enumerate(scored)}


def _rank_vector(index: HybridIndex, query: str, eligible_refs: set[str]) -> dict[str, int]:
    if not eligible_refs:
        return {}
    result = index.collection.query(
        query_embeddings=[hash_embed(query)],
        n_results=len(eligible_refs),
        where={"clause_ref": {"$in": sorted(eligible_refs)}},
    )
    ids = result["ids"][0] if result["ids"] else []
    return {clause_ref: rank + 1 for rank, clause_ref in enumerate(ids)}


def retrieve(index: HybridIndex, query: str, service_id: str, top_k: int = 5) -> list[dict]:
    """Hybrid BM25 + vector retrieval fused with Reciprocal Rank Fusion, k=60
    (SPEC §9). Clauses are filtered to those tagged with service_id BEFORE
    ranking — only that filtered set ever competes for a rank in either
    retriever. Returns [{clause_ref, score, text}], or [] if nothing scores
    above threshold; the caller sets halt_reason = NO_GOVERNING_POLICY (§8).
    """
    eligible = {c.clause_ref: c for c in index.clauses if service_id in (c.tags or [])}
    if not eligible:
        return []

    eligible_refs = set(eligible)
    bm25_ranks = _rank_bm25(index, tokenize(query), eligible_refs)
    vector_ranks = _rank_vector(index, query, eligible_refs)
    worst_rank = len(eligible)

    fused = []
    for clause_ref, clause in eligible.items():
        rank_bm25 = bm25_ranks.get(clause_ref, worst_rank)
        rank_vector = vector_ranks.get(clause_ref, worst_rank)
        score = 1 / (RRF_K + rank_bm25) + 1 / (RRF_K + rank_vector)
        fused.append({"clause_ref": clause_ref, "score": score, "text": clause.text})

    fused.sort(key=lambda item: item["score"], reverse=True)
    fused = [item for item in fused if item["score"] >= MIN_SCORE_THRESHOLD]
    return fused[:top_k]
