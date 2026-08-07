# CLAUDE.md

Enterprise Intelligence Layer — a policy-aware service request platform.

## Ground rules

- **@SPEC.md is the single source of truth.** Read it before writing anything. If code and
  SPEC disagree, SPEC wins. Never invent or rename a field, ID, enum, status or file path
  defined there.
- **@BUILD_PLAN.md defines the order.** Build only the step I name. Do not run ahead.
- **Never modify anything under `seed/`.** It is fixed demo data; IDs are referenced by the
  presentation script. If seeding fails, fix the loader, not the data.
- **Do not add dependencies** beyond the stack in SPEC §1, and nothing that needs its own
  port, container or credential. No Postgres, Redis, Neo4j, Temporal, Docker or auth provider.

## Architecture invariants — do not violate these

1. **The LLM never decides an outcome.** It extracts facts, asks for missing fields, and
   narrates decisions the rule engine already made. Approvers, tiers, limits and outcomes
   come from YAML rules evaluated in pure Python.
2. **Retrieval informs explanation; rules produce decisions.** Never let a RAG hit be the
   basis for an outcome.
3. **Rules load from YAML at startup only.** There must be no runtime path that disables
   or overrides a rule (see golden case G19).
4. **Every consequential step writes a DecisionRecord** (SPEC §4.6). The timeline, audit
   view, trace viewer and analytics all read from that one table.
5. **Ownership conflicts are found algorithmically** with `networkx.simple_cycles` and
   broken by the documented precedence ladder — never by asking a model.
6. **These four rule outcomes are distinct** and must not collapse into one boolean:
   `exceptionable`, `hard_block`, `adds_approval`, `routing_correction`.
   `adds_approval` and `routing_correction` are *not* policy breaches.
7. **A request is a persistent object.** The conversation is one interface to it, never
   the source of truth.

## Commands

```bash
uvicorn backend.main:app --reload    # run API
python -m backend.seed               # rebuild SQLite from seed/ (idempotent)
pytest tests/                        # all tests
pytest tests/test_eval.py            # golden set — false auto-approvals MUST be 0
```

## Working style

- Write only the files named in the current step. Leave everything else untouched.
- After each step, tell me the verification command to run. Do not claim it passes —
  I will run it.
- If a request conflicts with SPEC, say so and quote the section rather than complying.
- Prefer small focused files over large ones. No file over ~300 lines.
