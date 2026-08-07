# Enterprise Intelligence Layer — code generation handoff package

Everything needed to generate this project. Hand the whole folder to Claude Code and work
through `BUILD_PLAN.md` one step at a time.

## What's here

| File | Purpose |
|---|---|
| `SPEC.md` | **Single source of truth.** Architecture, data model, graph topology, rule schema, resolution precedence, API surface, LLM contracts. Read first, cite constantly. |
| `BUILD_PLAN.md` | 13 steps, one prompt each, with a verification command per step and a fallback ladder. |
| `seed/departments.json` | 8 departments |
| `seed/employees.json` | 17 employees — demo personas flagged with `demo_note` |
| `seed/policies/*.md` | 8 policy documents with YAML front-matter, chunked at `### ` clause headings |
| `seed/rules/*.yaml` | Machine-readable deterministic rules, each citing a clause |
| `seed/services/*.yaml` | Service definitions — **the framework artifact.** New service = new YAML, no code |
| `seed/ownership_matrix.yaml` | Ownership edges, including the deliberate 4-node approval deadlock |
| `seed/generate_requests.py` | Deterministic backlog generator (already run) |
| `seed/requests.json` | 50 historical requests; 12 blocked on the deadlock |
| `eval/golden_set.json` | 25 cases including prompt injection, ambiguity, and no-governing-policy |

## Quick start

```bash
pip install fastapi uvicorn sqlalchemy langgraph langgraph-checkpoint-sqlite \
            anthropic rank_bm25 chromadb networkx pyyaml pydantic pytest
export ANTHROPIC_API_KEY=...
# then work through BUILD_PLAN.md from Step 0
```

## The seed data is load-bearing — do not regenerate it

The demo depends on specific IDs and on relationships that look like accidents but are not:

- `POL-DG-090§2.2` delegates approval onward; `POL-SEC-204` v3.1 **explicitly supersedes it**.
  That supersession is what breaks the deadlock deterministically. Without it you are guessing.
- `POL-SEC-204§4.3` states HR approval is not required for technical access, while
  `POL-HR-118§7.1` says access is subject to Security review. Both are true. Neither is wrong.
  The system must resolve which one *confers approval authority*.
- Travel triggers **two** policies that **compound** rather than conflict — a lodging cap
  exception (Travel Ops) plus a spend threshold (Finance). Judges will assume any overlap is
  a conflict; showing that your engine distinguishes the two is worth more than the conflict demo.
- `EMP-107` is grade G3 specifically so a privileged-access request hard-blocks at Tier 4.
- `SVC-SOFTWARE.yaml` ships `enabled: false` for the live service-addition demo.

## The three claims this package is built to prove

1. **Deterministic where it matters.** Every outcome traces to a YAML rule and a clause
   reference. The LLM extracts and narrates; it never decides. Golden-set false auto-approvals: 0.
2. **Genuine cross-policy reasoning.** The approval deadlock is found by `nx.simple_cycles`
   and broken by a documented precedence ladder — not by asking a model what it thinks.
3. **Reusable by construction.** Adding a service type is a YAML file. Demonstrated live.

## Still missing — build these outside the code

The scoring rubric is 65% framing, impact, scaling and articulation. This package covers
the 25% prototype. Before demo day you still need:

- **Stakeholder map** — six roles: employee, manager/approver, service desk agent,
  **policy owner**, compliance/audit, platform admin
- **Baseline journey** — the current-state access request: days elapsed, handoffs, wrong queues
- **Business case** — first-time-right routing %, touches per request, exception cycle time,
  rework rate, and the value model built on them
- **The learning loop on a slide** — bottleneck detected → rule proposed → human ratified →
  behaviour changed. This is the brief's "learned from" stage and most teams will skip it.
