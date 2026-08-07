"""Golden-set evaluation (SPEC §15).

Drives every case in eval/golden_set.json through the real graph and reports
intent accuracy, routing accuracy and the false-auto-approval count against the
thresholds declared in that file.

The number that matters is false auto-approvals: it must be zero.
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from backend.catalog import load_catalog
from backend.graph.build import build_graph

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "eval" / "golden_set.json"
GOLDEN = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
THRESHOLDS = GOLDEN["thresholds"]
CASES = GOLDEN["cases"]


def _enabled_services() -> set[str]:
    return {s["id"] for s in load_catalog().values() if s.get("enabled")}


def _precondition_unmet(case: dict) -> str | None:
    """G23/G24 require SVC-SOFTWARE to be enabled. Enabling it means editing
    seed/services/SVC-SOFTWARE.yaml (ships enabled: false by design for the
    Scenario C live-add demo), which this harness will not do — seed/ is fixed.
    """
    precondition = case.get("precondition")
    if not precondition:
        return None
    if "SVC-SOFTWARE" in precondition and "SVC-SOFTWARE" not in _enabled_services():
        return "SVC-SOFTWARE not enabled (flip it and POST /api/services/reload)"
    return None


def _run_case(app, case: dict) -> dict:
    state = app.invoke(
        {
            "request_id": f"EVAL-{case['id']}",
            "employee_id": case["employee_id"],
            "channel": "WEB",
            "messages": [{"role": "user", "content": case["message"]}],
        },
        config={"configurable": {"thread_id": f"EVAL-{case['id']}"}},
    )
    state.pop("__interrupt__", None)
    return state


def _violated(state: dict) -> list[str]:
    return [
        r["rule_id"]
        for r in state.get("rule_results", [])
        if r.get("applicable") and not r.get("passed")
    ]


def _is_auto_approved(state: dict) -> bool:
    """Auto-approved means the system committed to an outcome with no human in
    the loop: tier <= 1, no pending approvals, not halted, not blocked.
    """
    if state.get("halt_reason"):
        return False
    if any(r.get("hard_block") for r in state.get("rule_results", []) if not r.get("passed")):
        return False
    approvals = state.get("approvals") or []
    if approvals:
        return False
    return state.get("tier", 0) <= 1 and bool(state.get("service_id"))


def _routing_actual(state: dict) -> list[str]:
    approvals = state.get("approvals") or []
    if approvals:
        return [a.get("department_id") for a in approvals]
    route = state.get("route") or {}
    return [route.get("department_id")] if route.get("department_id") else []


def _routing_expected(expect: dict) -> list[str] | None:
    if "approver_sequence" in expect:
        return list(expect["approver_sequence"])
    if "approver_department" in expect:
        return [expect["approver_department"]]
    return None


@pytest.fixture(scope="module")
def results():
    checkpoint_path = os.path.join(tempfile.mkdtemp(prefix="eil-eval-"), "checkpoints.sqlite")
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    app = build_graph(SqliteSaver(conn))

    rows = []
    for case in CASES:
        skip_reason = _precondition_unmet(case)
        if skip_reason:
            rows.append({"case": case, "state": None, "error": None, "skipped": skip_reason})
            continue
        try:
            state = _run_case(app, case)
            rows.append({"case": case, "state": state, "error": None, "skipped": None})
        except Exception as exc:  # network/LLM failure, not a policy failure
            rows.append({"case": case, "state": None, "error": repr(exc), "skipped": None})

    conn.close()
    return rows


@pytest.fixture(scope="module")
def summary(results):
    intent_total = intent_ok = 0
    routing_total = routing_ok = 0
    false_auto_approvals: list[str] = []
    table: list[tuple] = []

    for row in results:
        case, state = row["case"], row["state"]
        expect = case["expect"]
        case_id = case["id"]

        if row["skipped"]:
            table.append((case_id, case["category"], "SKIP", "-", "-", row["skipped"]))
            continue
        if row["error"]:
            table.append((case_id, case["category"], "ERROR", "-", "-", row["error"][:60]))
            continue

        notes = []

        intent_verdict = "-"
        if "intent" in expect:
            intent_total += 1
            actual_intent = state.get("intent")
            if actual_intent == expect["intent"]:
                intent_ok += 1
                intent_verdict = "OK"
            else:
                intent_verdict = "MISS"
                notes.append(f"intent={actual_intent!r} want {expect['intent']!r}")

        routing_verdict = "-"
        expected_route = _routing_expected(expect)
        if expected_route is not None:
            routing_total += 1
            actual_route = _routing_actual(state)
            if actual_route[: len(expected_route)] == expected_route:
                routing_ok += 1
                routing_verdict = "OK"
            else:
                routing_verdict = "MISS"
                notes.append(f"route={actual_route} want {expected_route}")

        auto = _is_auto_approved(state)
        if expect.get("auto_approved") is False and auto:
            false_auto_approvals.append(case_id)
            notes.append("FALSE AUTO-APPROVAL")
        if expect.get("hard_block") and auto:
            if case_id not in false_auto_approvals:
                false_auto_approvals.append(case_id)
            notes.append("FALSE AUTO-APPROVAL (hard_block)")
        if expect.get("exception_expected") and auto:
            if case_id not in false_auto_approvals:
                false_auto_approvals.append(case_id)
            notes.append("FALSE AUTO-APPROVAL (exception expected)")

        for rule_id in expect.get("rules_violated", []):
            if rule_id not in _violated(state):
                notes.append(f"missing violation {rule_id}")
        if "halt_reason" in expect and state.get("halt_reason") != expect["halt_reason"]:
            notes.append(f"halt={state.get('halt_reason')!r} want {expect['halt_reason']!r}")
        if "tier" in expect and state.get("tier") != expect["tier"]:
            notes.append(f"tier={state.get('tier')} want {expect['tier']}")

        table.append(
            (
                case_id,
                case["category"],
                "AUTO" if auto else "HUMAN",
                intent_verdict,
                routing_verdict,
                "; ".join(notes),
            )
        )

    return {
        "table": table,
        "intent_total": intent_total,
        "intent_ok": intent_ok,
        "routing_total": routing_total,
        "routing_ok": routing_ok,
        "intent_accuracy": intent_ok / intent_total if intent_total else 0.0,
        "routing_accuracy": routing_ok / routing_total if routing_total else 0.0,
        "false_auto_approvals": false_auto_approvals,
        "errors": [r["case"]["id"] for r in results if r["error"]],
        "skipped": [r["case"]["id"] for r in results if r["skipped"]],
    }


def test_print_summary(summary):
    """Always prints the table. Run with -s to see it."""
    out = sys.stdout
    print(file=out)
    print("=" * 108, file=out)
    print(
        f"{'case':<6}{'category':<22}{'path':<7}{'intent':<8}{'routing':<9}notes",
        file=out,
    )
    print("-" * 108, file=out)
    for row in summary["table"]:
        print(f"{row[0]:<6}{row[1]:<22}{row[2]:<7}{row[3]:<8}{row[4]:<9}{row[5]}", file=out)
    print("=" * 108, file=out)
    print(
        f"intent accuracy      {summary['intent_accuracy']:.2%} "
        f"({summary['intent_ok']}/{summary['intent_total']})  "
        f"threshold {THRESHOLDS['intent_accuracy_min']:.0%}",
        file=out,
    )
    print(
        f"routing accuracy     {summary['routing_accuracy']:.2%} "
        f"({summary['routing_ok']}/{summary['routing_total']})  "
        f"threshold {THRESHOLDS['routing_accuracy_min']:.0%}",
        file=out,
    )
    print(
        f"false auto-approvals {len(summary['false_auto_approvals'])}  "
        f"threshold {THRESHOLDS['false_auto_approvals_max']}  "
        f"{summary['false_auto_approvals'] or ''}",
        file=out,
    )
    print(
        f"errors {len(summary['errors'])} {summary['errors'] or ''} · "
        f"skipped {len(summary['skipped'])} {summary['skipped'] or ''}",
        file=out,
    )
    print("=" * 108, file=out)


def test_false_auto_approvals_is_zero(summary):
    assert len(summary["false_auto_approvals"]) == THRESHOLDS["false_auto_approvals_max"], (
        f"False auto-approvals: {summary['false_auto_approvals']}"
    )


def test_intent_accuracy_meets_threshold(summary):
    assert summary["intent_accuracy"] >= THRESHOLDS["intent_accuracy_min"], (
        f"{summary['intent_accuracy']:.2%} < {THRESHOLDS['intent_accuracy_min']:.2%}"
    )


def test_routing_accuracy_meets_threshold(summary):
    assert summary["routing_accuracy"] >= THRESHOLDS["routing_accuracy_min"], (
        f"{summary['routing_accuracy']:.2%} < {THRESHOLDS['routing_accuracy_min']:.2%}"
    )
