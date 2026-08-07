# SPEC.md — Enterprise Intelligence Layer

**This file is the single source of truth. Every generated file must conform to it.
If code and SPEC disagree, SPEC wins. Do not invent field names not defined here.**

---

## 0. What we are building

A platform-agnostic intelligence layer that sits above existing enterprise systems and turns
fragmented service requests and policy exceptions into one coherent, policy-aware,
end-to-end employee service journey.

The seven-stage journey contract every request must traverse:

```
asked → clarified → classified → policy-checked → routed → decided → resolved → communicated → learned
```

### The three-layer decision model (non-negotiable)

| Layer | Owner | Does |
|---|---|---|
| 1. Interpretation | LLM | Extracts intent, entities, missing fields. Writes explanations. |
| 2. Governance | Deterministic engine | Evaluates rules, resolves ownership, decides approvals. |
| 3. Authorization | Humans | Approves anything above Tier 1. |

**An LLM never decides an outcome.** It extracts facts and narrates decisions the rule engine made.
Retrieval informs *explanation*; YAML rules produce *decisions*. If no rule matches with confidence,
the system escalates to a human and says so. Build that refusal path.

---

## 1. Tech stack — fixed, do not substitute

| Concern | Choice |
|---|---|
| Language | Python 3.11 |
| API | FastAPI + Uvicorn |
| Orchestration | LangGraph (`langgraph`), `SqliteSaver` checkpointer, `interrupt()` for approvals |
| LLM | Anthropic `claude-sonnet-4-6` via `anthropic` SDK, structured JSON output |
| DB | SQLite via SQLAlchemy 2.x |
| Lexical retrieval | `rank_bm25` |
| Vector retrieval | `chromadb` **in-memory client only** (`chromadb.EphemeralClient()`) |
| Graph reasoning | `networkx` |
| Config | `pyyaml` |
| Frontend | React + Vite + TypeScript + Tailwind |
| Tests | `pytest` |

**Hard rule: nothing that requires its own port, container, or credential.**
No Postgres, no Redis, no Neo4j, no Temporal, no Docker, no auth provider.

Identity is a persona switcher: a header dropdown sets `X-Persona-Id`, the API trusts it.

---

## 2. Repository layout

```
eil/
├── SPEC.md                     ← this file
├── BUILD_PLAN.md               ← prompt-by-prompt build order
├── backend/
│   ├── main.py                 FastAPI app + routes
│   ├── db.py                   SQLAlchemy engine, session, Base
│   ├── models.py               ORM models (§4)
│   ├── schemas.py              Pydantic request/response models
│   ├── seed.py                 loads /seed into SQLite
│   ├── graph/
│   │   ├── state.py            RequestState TypedDict (§5)
│   │   ├── build.py            LangGraph assembly + checkpointer
│   │   └── nodes/
│   │       ├── intent.py
│   │       ├── context.py
│   │       ├── clarifier.py
│   │       ├── policy.py
│   │       ├── exception.py
│   │       ├── router.py
│   │       ├── approval.py
│   │       └── communicate.py
│   ├── engine/
│   │   ├── rules.py            deterministic YAML rule evaluator (§6)
│   │   ├── ownership.py        NetworkX graph + cycle detection (§7)
│   │   ├── resolution.py       stuck-request diagnosis (§7.3)
│   │   ├── tiers.py            risk tiering + confidence gating (§8)
│   │   └── decisions.py        DecisionRecord writer (§4.6)
│   ├── rag/
│   │   ├── index.py            clause chunking + hybrid index (§9)
│   │   └── retrieve.py         BM25 + vector fusion, returns clause refs
│   ├── llm/
│   │   ├── client.py           Anthropic wrapper, JSON mode, retry
│   │   └── prompts.py          all prompts as named constants
│   ├── connectors/
│   │   ├── base.py             ServiceConnector ABC (§10)
│   │   └── internal.py         InternalConnector implementation
│   └── catalog.py              loads /seed/services/*.yaml at startup
├── frontend/                   (see §12)
├── seed/                       ← provided, do not regenerate
├── eval/golden_set.json        ← provided
└── tests/
```

---

## 3. Core domain vocabulary

| Term | Meaning |
|---|---|
| **Service** | A request type the enterprise offers. Defined purely in YAML. |
| **Request** | A persistent object with a lifecycle. The conversation is one interface to it, never the source of truth. |
| **Policy** | A prose document, versioned, owned by a department. |
| **Clause** | An addressable fragment of a policy (`POL-SEC-204§4.2`). Citations point here. |
| **Rule** | A machine-readable, deterministic condition derived from a clause. |
| **Exception** | A first-class object created when a request violates a rule but may still be permitted. |
| **Decision Record** | Immutable provenance row for every consequential step. |
| **Ownership edge** | "Department X says approval belongs to Y for request type Z." |

---

## 4. Data model

SQLAlchemy models in `backend/models.py`. All IDs are strings.

### 4.1 employees

| Column | Type | Notes |
|---|---|---|
| `id` | str PK | `EMP-101` |
| `name` | str | |
| `email` | str | |
| `title` | str | |
| `department_id` | str FK | |
| `manager_id` | str FK nullable | |
| `location` | str | `Mumbai` |
| `city_tier` | int | 1 or 2 |
| `cost_center` | str | |
| `grade` | str | `G5` .. `G9` |
| `leave_balance_days` | float | |
| `roles` | JSON list | `["employee","approver","policy_owner","admin"]` |

### 4.2 departments

`id` (`DEPT-SEC`), `name`, `head_employee_id`.

### 4.3 policies

| Column | Notes |
|---|---|
| `id` | `POL-SEC-204` |
| `title` | |
| `owner_department_id` | |
| `policy_class` | `SECURITY` \| `FINANCIAL` \| `HR` \| `OPERATIONAL` |
| `version` | `3.1` |
| `effective_date` | ISO date |
| `supersedes` | JSON list of clause refs this overrides |
| `body_md` | full prose |

### 4.4 clauses

`id` (`POL-SEC-204§4.2`), `policy_id`, `ref` (`4.2`), `heading`, `text`, `tags` (JSON list).
Populated by chunking `policies.body_md` at `### ` headings.

### 4.5 requests

| Column | Notes |
|---|---|
| `id` | `REQ-10234` |
| `employee_id` | |
| `service_id` | `SVC-TRAVEL` |
| `intent` | `TRAVEL_BOOKING` |
| `status` | see §11 state machine |
| `channel` | `WEB` \| `TEAMS` \| `SLACK` \| `EMAIL` |
| `payload` | JSON — collected field values |
| `missing_fields` | JSON list |
| `assigned_department_id` | current queue |
| `pending_approver_id` | nullable |
| `tier` | 0–4 |
| `thread_id` | LangGraph checkpoint thread id |
| `created_at`, `updated_at` | |
| `closed_at` | nullable |
| `stuck_reason_code` | nullable, set by resolution engine |

### 4.6 decision_records — **the central primitive**

Every consequential step writes exactly one row. Immutable, append-only.

| Column | Notes |
|---|---|
| `id` | uuid |
| `request_id` | |
| `stage` | `INTENT` \| `CONTEXT` \| `CLARIFY` \| `POLICY` \| `EXCEPTION` \| `ROUTE` \| `APPROVAL` \| `COMMUNICATE` \| `RESOLUTION` |
| `actor` | `AI` \| `RULE_ENGINE` \| `HUMAN` |
| `actor_id` | model name, rule id, or employee id |
| `inputs_used` | JSON — what the step read |
| `rule_fired` | nullable rule id |
| `clause_refs` | JSON list of citations |
| `policy_versions` | JSON `{POL-SEC-204: "3.1"}` |
| `output` | JSON — the decision |
| `confidence` | float 0–1, nullable for deterministic steps |
| `rationale` | short human-readable string |
| `latency_ms` | int |
| `created_at` | |

This one table powers: the audit view, the request timeline, the agent trace viewer,
bottleneck analytics, and every "why did this happen?" answer. **Build it in the first hour.**

### 4.7 exceptions

| Column | Notes |
|---|---|
| `id` | `EXC-4401` |
| `request_id` | |
| `violated_rule_id` | |
| `clause_refs` | JSON |
| `requested_value` / `policy_limit` / `delta` | |
| `justification` | employee text |
| `evidence` | JSON list |
| `risk_score` | 0–100 |
| `risk_band` | `LOW` \| `MEDIUM` \| `HIGH` |
| `compensating_controls` | JSON list of strings |
| `approver_id` | |
| `status` | `DRAFT` \| `PENDING` \| `APPROVED` \| `REJECTED` \| `ACTIVE` \| `EXPIRED` \| `REVOKED` |
| `expires_at` | |
| `review_due_at` | |

### 4.8 ownership_edges

`id`, `source_department_id`, `service_id`, `asserts_approver_department_id`,
`clause_ref`, `note`. Loaded from `seed/ownership_matrix.yaml`. This is what NetworkX consumes.

### 4.9 routing_rules

`id`, `service_id`, `condition` (JSON), `target_department_id`, `active` (bool),
`source` (`SEED` \| `PROPOSED` \| `APPROVED`), `proposed_by_resolution_id` nullable.
The learning loop writes `PROPOSED` rows; a policy owner flips them to `APPROVED`.

### 4.10 approvals

`id`, `request_id`, `approver_id`, `sequence` (int), `reason`, `required_by_clause_ref`,
`status` (`PENDING`/`APPROVED`/`REJECTED`), `decided_at`, `comment`.

---

## 5. LangGraph state

`backend/graph/state.py`:

```python
class RequestState(TypedDict, total=False):
    request_id: str
    employee_id: str
    channel: str
    messages: list[dict]          # {role, content}
    intent: str | None
    intent_confidence: float
    service_id: str | None
    entities: dict                # extracted slot values
    context: dict                 # employee, manager, balances, history
    missing_fields: list[str]
    clause_hits: list[dict]       # {clause_ref, score, text}
    rule_results: list[dict]      # {rule_id, passed, actual, limit, clause_ref}
    exception_draft: dict | None
    tier: int
    route: dict | None            # {department_id, approver_id, reason, clause_ref}
    approvals: list[dict]
    outcome: str | None
    explanation: str | None
    halt_reason: str | None       # set when escalating to human
```

### Graph topology

```
START → intent → context → clarifier ─┐
                              ▲       │ (missing_fields non-empty → END, await user)
                              └───────┘
        clarifier (complete) → policy
        policy ──[all rules pass]──→ router
        policy ──[violation, exceptionable]──→ exception → router
        policy ──[violation, hard block]──→ communicate
        router ──[tier <= 1]──→ communicate
        router ──[tier >= 2]──→ approval ──interrupt()──→ communicate
        communicate → END
```

- Conditional edges only. No node calls another node directly.
- Every node returns a partial state dict **and** writes a DecisionRecord.
- `approval` uses LangGraph `interrupt()` so the graph checkpoints to SQLite and
  resumes when a human posts a decision. This is how approvals survive process restart.
- `resolution` runs **off-graph**, as a service over the stuck-request queue.

---

## 6. Rule engine (`engine/rules.py`)

Rules live in `seed/rules/*.yaml`. Schema:

```yaml
- id: RULE-TRV-HOTEL-CAP
  service_id: SVC-TRAVEL
  policy_id: POL-TRV-101
  clause_ref: POL-TRV-101§5.3
  description: Nightly lodging must not exceed the destination city-tier cap.
  when:                          # rule is applicable only if this matches
    field: destination_city_tier
    op: in
    value: [1, 2]
  assert:                        # the condition that must hold
    field: hotel_rate_per_night
    op: lte
    value_by:                    # limit selected from another field
      key: destination_city_tier
      map: { 1: 10000, 2: 8000 }
  on_violation:
    exceptionable: true
    severity: MEDIUM
    approver_department_id: DEPT-TRV
    approver_clause_ref: POL-TRV-101§5.7
    compensating_controls:
      - "Attach dated evidence of no compliant inventory within 5 km"
      - "Approved nights capped at the requested trip duration"
      - "Exception expires at end of travel period"
```

Supported ops: `eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `in`, `not_in`, `exists`, `matches`.

`value_by` selects the limit from another field: `{key: <field>, map: {...}}`, or
`{key: context.<field>}` to read a live value such as `context.leave_balance_days`.

`on_violation` flags and their meaning — **these are distinct outcomes, do not collapse them**:

| Flag | Meaning |
|---|---|
| `exceptionable: true` | Creates an Exception object; may proceed with approval + controls |
| `hard_block: true` | Terminal. No exception path. Usually with `tier_override: 4` |
| `adds_approval: true` | **Not a breach.** An additional approver is appended, optionally `sequence_after` |
| `routing_correction: true` | **Not a breach.** The request is in the wrong queue; reassign |

Evaluation is pure Python — **never an LLM call.** Rules load from YAML at startup only;
there must be no runtime path that disables a rule (see golden case G19).

Evaluator contract:

```python
def evaluate(service_id: str, payload: dict, context: dict) -> list[RuleResult]
# RuleResult = {rule_id, applicable, passed, actual, limit, clause_ref, policy_id, severity, exceptionable}
```

---

## 7. Ownership graph & resolution (`engine/ownership.py`, `engine/resolution.py`)

### 7.1 Graph construction

Build a `networkx.DiGraph` from `ownership_edges`:

- Nodes: `DEPT-*`, `SVC-*`, `POL-*`
- Edge `DEPT-A → DEPT-B` labelled `{service_id, clause_ref}` means
  "Department A asserts that approval for this service belongs to Department B."

### 7.2 Conflict detection — deterministic, not LLM

```python
cycles = list(nx.simple_cycles(subgraph_for_service))
```

A cycle is an **approval deadlock**: each department points at the next, and the last points back.
This is exactly the seeded production-access conflict (`DEPT-HR → DEPT-SEC → DEPT-DG → DEPT-IT → DEPT-HR`).

### 7.3 Governing-authority resolution

When a cycle exists, break it with deterministic precedence, in this order:

1. **Policy class precedence:** `SECURITY` > `FINANCIAL` > `HR` > `OPERATIONAL`
2. **Explicit supersession:** a clause listed in another policy's `supersedes`
3. **Recency:** later `effective_date` wins
4. **Specificity:** a clause naming the specific `service_id` beats a general one

The winner becomes the governing clause; its `asserts_approver_department_id` is the correct owner.
Emit a `RESOLUTION` DecisionRecord containing the cycle, the losing edges, the precedence rule applied,
and a `PROPOSED` routing_rule. Only *then* call the LLM — to narrate the finding in plain English.

### 7.4 Bottleneck detection

Aggregate over `decision_records` + `requests`:
requests per service stuck > SLA, reassignment counts, most common wrong first queue.
Surface as an admin insight with a one-click `PROPOSED → APPROVED` routing rule change.
**That click is the "learned from" stage.** Demonstrate it.

---

## 8. Risk tiers & confidence gating (`engine/tiers.py`)

| Tier | Meaning | Behaviour |
|---|---|---|
| 0 | Informational | Answer, no request created |
| 1 | Low risk, within policy | Auto-execute, notify |
| 2 | Standard approval | Manager or owning dept approves |
| 3 | High risk / policy exception | Named approver + risk record + expiry |
| 4 | Restricted | Never AI-executed; hand to human queue with full context |

Tier is computed deterministically from: service `base_tier`, rule violations, exception severity,
and monetary value bands. **Never LLM-assigned.**

Confidence gating on intent:

- `>= 0.75` → proceed
- `0.45 – 0.75` → ask one disambiguating question
- `< 0.45` → `halt_reason = LOW_CONFIDENCE_INTENT`, route to human service desk

If retrieval returns no clause above threshold for a service, set
`halt_reason = NO_GOVERNING_POLICY` and escalate. **Do not let the model improvise policy.**

---

## 9. Hybrid RAG (`rag/`)

- **Chunk at clause level**, never document level. One chunk = one `clauses` row.
- Each chunk carries metadata `{clause_ref, policy_id, version, effective_date, owner_dept, policy_class, tags}`.
- Index both: BM25 over clause text (`rank_bm25`), and vectors in an **ephemeral** Chroma collection.
- Fuse with Reciprocal Rank Fusion: `score = Σ 1/(60 + rank_i)`.
- Filter by `service_id` tags before ranking.
- Return `[{clause_ref, score, text}]` — **clause references, never free text for decisions.**

Retrieval feeds the *explanation* prompt and helps select applicable rules.
It must never be the sole basis for an outcome.

---

## 10. Connector abstraction (`connectors/base.py`)

The seam that makes this platform-agnostic. Implement `InternalConnector` now;
ServiceNow/Jira are a later config change, not a rewrite.

```python
class ServiceConnector(ABC):
    name: str
    @abstractmethod
    def create_request(self, common: CommonRequest) -> ExternalRef: ...
    @abstractmethod
    def update_status(self, ref: ExternalRef, status: str) -> None: ...
    @abstractmethod
    def add_approval(self, ref: ExternalRef, approval: CommonApproval) -> None: ...
    @abstractmethod
    def fetch_state(self, ref: ExternalRef) -> CommonRequestState: ...
```

`CommonRequest` is the platform-neutral model: `{service_id, employee_ref, fields, tier,
approvals, clause_refs, external_hints}`. Connector selection is per-service via
`connector:` in the service YAML.

---

## 11. Request state machine

```
DRAFT → CLARIFYING → CLASSIFIED → POLICY_CHECKED
   ├─→ EXCEPTION_DRAFTED → EXCEPTION_PENDING → (APPROVED | REJECTED)
   ├─→ ROUTED → PENDING_APPROVAL → (APPROVED | REJECTED)
   └─→ AUTO_APPROVED
APPROVED → EXECUTING → FULFILLED → CLOSED
Any state → BLOCKED (with stuck_reason_code) → ROUTED (after resolution)
Any state → CANCELLED
```

Transitions are validated in one place. Illegal transitions raise. Every transition
writes a DecisionRecord.

`stuck_reason_code` ∈ `OWNERSHIP_CYCLE`, `NO_GOVERNING_POLICY`, `APPROVER_UNAVAILABLE`,
`AWAITING_EVIDENCE`, `WRONG_QUEUE`.

---

## 12. API surface

```
GET    /api/personas                          → list of switchable employees
POST   /api/chat                              → {message, employee_id, request_id?}
                                              → {reply, request_id, state, decision_records[]}
GET    /api/requests                          → filters: status, service_id, stuck=true
GET    /api/requests/{id}                     → request + timeline + decision records
POST   /api/requests/{id}/approve             → {approver_id, comment} resumes graph
POST   /api/requests/{id}/reject
GET    /api/requests/{id}/trace               → agent trace (decision records, ordered)
GET    /api/stuck                             → queue with cycle diagnosis
POST   /api/stuck/diagnose                    → run resolution engine over the queue
GET    /api/insights                          → bottleneck analytics
POST   /api/routing-rules/{id}/approve        → PROPOSED → APPROVED  (the learning loop)
GET    /api/policies /api/policies/{id}
POST   /api/policies/compile                  → prose → proposed rules (LLM drafts, human ratifies)
GET    /api/services                          → catalog from YAML
POST   /api/services/reload                   → hot-reload YAML  (the live-add demo)
GET    /api/exceptions
```

### Frontend views (React + Vite + Tailwind)

1. **Employee** — chat, active requests, timeline with clause citations
2. **Manager** — approval inbox with the *reason* and the clause that requires it
3. **Policy Owner** — policy list, compile-prose-to-rules review queue, proposed routing rules
4. **Admin** — stuck queue with the ownership-cycle visualization, bottleneck insights, agent trace viewer

Persona switcher in the header sets `X-Persona-Id`. No login.

---

## 13. LLM usage — the only four calls

Every prompt lives in `llm/prompts.py`. All return strict JSON. No prompt may ask the model
to decide an approver, an outcome, or a policy limit.

| # | Name | In | Out |
|---|---|---|---|
| 1 | `EXTRACT_INTENT` | message, service catalog summary | `{intent, service_id, confidence, entities{}, ambiguity_note}` |
| 2 | `GENERATE_CLARIFICATION` | missing_fields, field metadata, context already known | `{question, fields_asked[]}` — must ask **only** for genuinely missing fields |
| 3 | `EXPLAIN_DECISION` | decision records, clause texts | `{explanation}` — plain English, must cite clause refs, must not add rules |
| 4 | `NARRATE_RESOLUTION` | cycle, losing edges, precedence applied, proposed rule | `{summary, recommendation}` |

Plus one optional fifth for the differentiator:

| 5 | `COMPILE_POLICY` | prose clause | `{proposed_rules[]}` in the §6 YAML schema — **status `PROPOSED`, requires human ratification before it can fire** |

Client requirements: `temperature=0`, JSON extraction with fence stripping, one retry on parse
failure, hard timeout, and every call logged to `decision_records` with `latency_ms` and `confidence`.

---

## 14. Seeded demo scenarios — the code must make these work

### Scenario A — Travel with a policy exception (compound approval)
Aarav Sharma (EMP-101, Mumbai, G6) requests Bangalore travel, hotel ₹12,000/night × 3 nights.
- `RULE-TRV-HOTEL-CAP` fires: Tier-1 cap is ₹10,000 → violation, exceptionable, MEDIUM.
- `RULE-FIN-HIGH-VALUE` fires: total ₹36,000 > ₹25,000 → Finance approval also required.
- Correct outcome: **two sequential approvals** — Travel Operations, then Finance — plus an
  Exception record with compensating controls and `expires_at` = trip end date. Tier 3.
- This proves overlapping policies compounding rather than conflicting.

### Scenario B — Production DB access, ownership deadlock
Ishita Rao (EMP-104) requests production database access.
Seeded ownership edges form a 4-cycle:
`DEPT-HR → DEPT-SEC → DEPT-DG → DEPT-IT → DEPT-HR`.
- `nx.simple_cycles` detects it deterministically.
- Precedence resolution: `POL-SEC-204` is `SECURITY` class, v3.1, effective 2026-04-01, and
  explicitly supersedes `POL-DG-090§2.2`. Governing approver = **Data Custodian (Priya Nair, DEPT-DG)**.
- HR approval is *not* required. System emits a `PROPOSED` routing rule.
- 12 seeded historical requests are stuck on this same cycle → the admin approves one rule
  change and all 12 reroute. **This is the demo's climax.**

### Scenario C — Live service addition
`seed/services/SVC-SOFTWARE.yaml` is provided but **not** loaded at startup
(`enabled: false`). During the demo, flip it to `true`, POST `/api/services/reload`,
and the same intelligence layer handles software licence requests with correct policy,
tiering, and routing — **with no code change.** This is the reusability proof.

---

## 15. Evaluation (`eval/golden_set.json`)

25 cases. Each: `{id, message, employee_id, expect: {intent, service_id, missing_fields, rules_fired, tier, approver_department, exception_expected, halt_reason}}`.

Includes adversarial cases: ambiguous intent, out-of-scope request, prompt injection attempt,
a request with no governing policy, and a Tier-4 restricted request.

`pytest tests/test_eval.py` reports intent accuracy, routing accuracy, and
false-auto-approval count. **False auto-approvals must be zero.** Put that number on a slide.

---

## 16. Definition of done

- [ ] `python -m backend.seed` builds the SQLite DB from `/seed` with zero manual steps
- [ ] Scenario A runs end to end in the UI, including both approvals
- [ ] Scenario B detects the cycle via NetworkX, cites the governing clause, and reroutes all 12
- [ ] Scenario C adds a service from YAML with no code change
- [ ] Every request has a complete, citation-bearing timeline from decision_records
- [ ] Approval survives a backend restart (checkpointer proof)
- [ ] Golden set passes with 0 false auto-approvals
- [ ] Low-confidence and no-governing-policy paths visibly escalate to a human
