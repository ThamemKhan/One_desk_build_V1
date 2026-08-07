# BUILD_PLAN.md — how to drive the code generation

**How to use this file.** Work through the steps in order. Each step is one prompt.
Start every prompt with the same preamble, run the verification command before moving on,
and commit when it passes. Do not skip a verification — a failure caught at step 4 costs
minutes; the same failure caught at step 11 costs an hour.

### Standard preamble — paste at the start of every prompt

> Read `SPEC.md` in full before writing anything. It is the single source of truth.
> Use exactly the field names, IDs, enums and file paths defined there — do not invent
> or rename any. Do not add dependencies beyond the stack in SPEC §1. Do not create
> anything requiring a separate port, container or credential. Write only the files
> I name in this step; leave everything else untouched.

### Rules for the whole build

- **One step, one prompt.** Never ask for "the backend" in a single request.
- **Paste real errors,** not descriptions of them. Full traceback.
- **Never regenerate `seed/`.** It is fixed and the demo script depends on the IDs.
- **Commit after every green verification.** At step 12 you want a tag to fall back to.
- If output contradicts SPEC, say so explicitly: *"SPEC §4.6 defines `clause_refs` as a
  JSON list; you used `citations`. Fix to match SPEC."* Drift on field names between files
  is the single biggest failure mode in a long generated build.

---

## Step 0 — Scaffold

> Create the repo skeleton per SPEC §2: directory tree, `requirements.txt`,
> `.gitignore`, `README.md`, and an empty `backend/main.py` with a FastAPI app and a
> `GET /api/health` route. Nothing else.

**Verify:** `uvicorn backend.main:app --reload` then `curl localhost:8000/api/health`

---

## Step 1 — Data model and seeding

> Write `backend/db.py`, `backend/models.py` and `backend/seed.py`.
> Implement every table in SPEC §4 exactly. `seed.py` must load `seed/departments.json`,
> `seed/employees.json`, `seed/requests.json`, all `seed/policies/*.md` (parsing YAML
> front-matter into the policies table and splitting the body at `### ` headings into the
> clauses table, with `id = "{policy_id}§{ref}"`), `seed/ownership_matrix.yaml` into
> ownership_edges, and `seed/services/*.yaml` via a catalog loader.
> Running `python -m backend.seed` must be idempotent — drop and rebuild.

**Verify:** seed runs clean; assert 8 policies, ≥50 clauses, 16+ employees, 50 requests,
12 with `status == "BLOCKED"`, 9 ownership edges.

*This is the step where a hidden mismatch does the most damage. Check the counts.*

---

## Step 2 — Rule engine

> Write `backend/engine/rules.py` per SPEC §6. Load all `seed/rules/*.yaml` at startup.
> Implement `evaluate(service_id, payload, context) -> list[RuleResult]` in pure Python.
> Support every op and both `value_by` forms. Handle the four distinct `on_violation`
> outcomes as separate result flags — `exceptionable`, `hard_block`, `adds_approval`,
> `routing_correction` — they must not be collapsed into a single "failed" boolean.
> No LLM call anywhere in this file. Also write `tests/test_rules.py` covering:
> Tier-1 hotel at 12000 violates, at 9000 passes; total 36000 triggers
> `RULE-FIN-HIGH-VALUE` as `adds_approval` not as a breach; grade G3 privileged access
> is `hard_block` with `tier_override: 4`.

**Verify:** `pytest tests/test_rules.py`

---

## Step 3 — Decision records and tiering

> Write `backend/engine/decisions.py` (append-only writer for SPEC §4.6, with a
> `@record(stage=...)` decorator or context manager that captures `latency_ms`
> automatically) and `backend/engine/tiers.py` (SPEC §8: deterministic tier computation
> and the three intent-confidence bands). Tier must never be LLM-assigned.

**Verify:** a unit test asserting a decision record is written with populated
`clause_refs`, `policy_versions` and `latency_ms`.

---

## Step 4 — Ownership graph and resolution

> Write `backend/engine/ownership.py` and `backend/engine/resolution.py` per SPEC §7.
> Build a `networkx.DiGraph` from ownership_edges. Detect cycles with `nx.simple_cycles`
> on the per-service subgraph. Break the cycle using the precedence ladder in
> `seed/ownership_matrix.yaml` (policy_class → explicit supersession → effective_date →
> specificity). Emit a RESOLUTION decision record containing the cycle, the invalidated
> edges, the precedence rule applied, and a `PROPOSED` routing_rule.
> Also implement bottleneck aggregation per SPEC §7.4.
> No LLM in this file — the cycle is found algorithmically.
> Write `tests/test_resolution.py` asserting the result matches the
> `expected_resolution` block in `seed/ownership_matrix.yaml`.

**Verify:** `pytest tests/test_resolution.py` — must yield governing clause
`POL-SEC-204§4.2`, approver `DEPT-DG`/`EMP-203`, `hr_approval_required: false`.

*This is your differentiator. Get it green before writing any UI.*

---

## Step 5 — Hybrid retrieval

> Write `backend/rag/index.py` and `backend/rag/retrieve.py` per SPEC §9.
> Index the clauses table with `rank_bm25` and an **ephemeral** Chroma collection.
> Fuse with Reciprocal Rank Fusion (k=60). Filter by service tags before ranking.
> Return `[{clause_ref, score, text}]`. If nothing scores above threshold, return empty —
> the caller sets `halt_reason = NO_GOVERNING_POLICY`.

**Verify:** a test asserting a production-access query returns `POL-SEC-204§4.2` in the top 3.

---

## Step 6 — LLM client and prompts

> Write `backend/llm/client.py` and `backend/llm/prompts.py` per SPEC §13.
> Exactly the five prompts, `temperature=0`, strict JSON with fence stripping, one retry
> on parse failure, hard timeout, every call logged to decision_records with `latency_ms`
> and `confidence`. No prompt may ask the model for an approver, an outcome, or a limit —
> the model extracts facts and narrates decisions the rule engine already made.
> `GENERATE_CLARIFICATION` must receive the already-known context and be instructed to
> ask **only** for fields with `source: ask` that are still missing.

**Verify:** a script that runs `EXTRACT_INTENT` over the 25 golden messages and prints
intent + confidence. Eyeball it before moving on.

---

## Step 7 — LangGraph assembly

> Write `backend/graph/state.py`, `backend/graph/build.py` and all eight nodes in
> `backend/graph/nodes/` per SPEC §5. Conditional edges only — no node calls another
> directly. Every node returns a partial state dict and writes a decision record.
> Use `SqliteSaver` as the checkpointer, keyed on `thread_id`.
> `approval` must use LangGraph `interrupt()` so the graph checkpoints and resumes on a
> later human decision. Stub `communicate` to return raw state for now.

**Verify:** a script that drives Scenario A end to end from a Python call and prints the
state at each node. Kill the process at the approval interrupt, restart it, resume from
the checkpoint, and confirm the request completes. **That restart is the proof.**

---

## Step 8 — Connector seam

> Write `backend/connectors/base.py` (the `ServiceConnector` ABC per SPEC §10) and
> `backend/connectors/internal.py`. Selection is per-service via `connector:` in the
> service YAML. Keep `CommonRequest` strictly platform-neutral — no ServiceNow or Jira
> vocabulary anywhere in `base.py`.

**Verify:** requests execute through `InternalConnector`; grep confirms `base.py`
contains no vendor-specific terms.

*Small step, high value. This is what makes "the next connector is config, not a rewrite"
a claim you can show rather than assert.*

---

## Step 9 — API layer

> Write `backend/schemas.py` and complete `backend/main.py` with every route in SPEC §12.
> `POST /api/chat` drives the graph and returns reply + request state + decision records.
> `POST /api/requests/{id}/approve` resumes the interrupted graph.
> `POST /api/services/reload` hot-reloads `seed/services/*.yaml` and rebuilds the catalog,
> rule set and retrieval index **without a process restart** — this is the Scenario C demo.
> Persona comes from the `X-Persona-Id` header; no auth.

**Verify:** walk Scenarios A and B entirely through `curl`. Do not open the UI yet.

---

## Step 10 — Frontend

> Build the React + Vite + Tailwind app with the four views in SPEC §12.
> Persona switcher in the header sets `X-Persona-Id`.
> The **Admin stuck queue** is the most important screen: list the 12 blocked requests,
> render the ownership cycle as a small directed graph, show the governing clause and the
> precedence reason, and provide one button that approves the proposed routing rule and
> reroutes all 12.
> The **request timeline** must render decision records with clause citations, each
> expandable to the clause text.
> The **trace viewer** renders decision records as an agent hop sequence with latency.
> Keep it visually plain and information-dense. No animations, no gradients.

**Verify:** click through Scenario A, then Scenario B, without touching a terminal.

---

## Step 11 — Evaluation harness

> Write `tests/test_eval.py` driving `eval/golden_set.json`. Report intent accuracy,
> routing accuracy, and false auto-approval count against the thresholds in the file.
> Print a summary table.

**Verify:** `pytest tests/test_eval.py`. **False auto-approvals must be zero.**
Put that number on a slide — it is the answer to "how do you know the AI won't approve
something it shouldn't?"

---

## Step 12 — Policy compilation (the differentiator, build only if the above is green)

> Add `POST /api/policies/compile` and the Policy Owner review queue per SPEC §13 prompt 5.
> The LLM drafts candidate rules in the SPEC §6 YAML schema from pasted prose.
> They are written with `status: PROPOSED` and **cannot fire until a policy owner ratifies
> them** in the UI. AI drafts, human ratifies, engine executes.

**Verify:** paste a clause from `seed/policies/POL-FAC-060.md`, review the proposed rule,
approve it, and confirm it then evaluates on a matching request.

---

## Step 13 — Freeze

Stop building. Set `SVC-SOFTWARE` back to `enabled: false`. Re-run seeding from scratch.
Walk the full demo three times end to end. Tag the commit.

**Do not refactor after this point.** The most common way a working project fails is a
late change that breaks the demo path with no time left to notice.

---

## Fallback ladder

If time runs short, cut in this order — each cut leaves a coherent demo standing:

1. Step 12 (policy compilation) — describe it as roadmap
2. Trace viewer — the timeline already carries the provenance story
3. Policy Owner view — fold the routing-rule approval into the Admin view
4. Hybrid RAG → BM25 only — drop Chroma, keep clause-level citation
5. Scenario C live-add — show the YAML on a slide instead

**Never cut:** the ownership cycle detection (step 4), the decision records (step 3), or
the deterministic rule engine (step 2). Those three are the project.
