import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RULES_DIR = Path(__file__).resolve().parent.parent.parent / "seed" / "rules"

_OPS = {
    "eq": lambda a, v: a == v,
    "neq": lambda a, v: a != v,
    "lt": lambda a, v: a is not None and a < v,
    "lte": lambda a, v: a is not None and a <= v,
    "gt": lambda a, v: a is not None and a > v,
    "gte": lambda a, v: a is not None and a >= v,
    "in": lambda a, v: a in v,
    "not_in": lambda a, v: a not in v,
    "matches": lambda a, v: a is not None and re.search(str(v), str(a)) is not None,
}


@dataclass
class RuleResult:
    rule_id: str
    service_id: str
    policy_id: str
    clause_ref: str
    description: str
    applicable: bool
    actual: Any
    limit: Any
    passed: bool = True
    severity: str | None = None
    exceptionable: bool = False
    hard_block: bool = False
    tier_override: int | None = None
    adds_approval: bool = False
    routing_correction: bool = False
    approver_department_id: str | None = None
    approver_role: str | None = None
    approver_clause_ref: str | None = None
    sequence_after: str | None = None
    compensating_controls: list = field(default_factory=list)
    required_evidence: list = field(default_factory=list)
    message: str | None = None


def _resolve(field_name: str, payload: dict, context: dict) -> Any:
    if field_name.startswith("context."):
        key = field_name[len("context."):]
        if key in context:
            return context[key]
        if "employee" in context and isinstance(context["employee"], dict) and key in context["employee"]:
            return context["employee"][key]
        return None
    return payload.get(field_name)


def _condition_value(cond: dict, payload: dict, context: dict) -> Any:
    if "value_by" in cond:
        value_by = cond["value_by"]
        key_value = _resolve(value_by["key"], payload, context)
        if "map" in value_by:
            return value_by["map"].get(key_value)
        return key_value
    return cond.get("value")


def _eval_condition(cond: dict, payload: dict, context: dict) -> tuple[bool, Any, Any]:
    actual = _resolve(cond["field"], payload, context)
    op = cond["op"]
    if op == "exists":
        return actual is not None, actual, None
    value = _condition_value(cond, payload, context)
    return _OPS[op](actual, value), actual, value


def _evaluate_rule(rule: dict, payload: dict, context: dict) -> RuleResult:
    when = rule.get("when")
    applicable = True
    if when:
        applicable, _, _ = _eval_condition(when, payload, context)

    assert_cond = rule["assert"]
    holds, actual, limit = _eval_condition(assert_cond, payload, context)

    result = RuleResult(
        rule_id=rule["id"],
        service_id=rule["service_id"],
        policy_id=rule["policy_id"],
        clause_ref=rule["clause_ref"],
        description=rule.get("description", ""),
        applicable=applicable,
        actual=actual,
        limit=limit,
    )

    if not applicable or holds:
        return result

    result.passed = False
    ov = rule.get("on_violation", {})
    result.severity = ov.get("severity")
    result.exceptionable = bool(ov.get("exceptionable", False))
    result.hard_block = bool(ov.get("hard_block", False))
    result.tier_override = ov.get("tier_override")
    result.adds_approval = bool(ov.get("adds_approval", False))
    result.routing_correction = bool(ov.get("routing_correction", False))
    result.approver_department_id = ov.get("approver_department_id")
    result.approver_role = ov.get("approver_role")
    result.approver_clause_ref = ov.get("approver_clause_ref")
    result.sequence_after = ov.get("sequence_after")
    result.compensating_controls = ov.get("compensating_controls", [])
    result.required_evidence = ov.get("required_evidence", [])
    result.message = ov.get("message")
    return result


def _load_rules() -> list[dict]:
    rules: list[dict] = []
    for path in sorted(RULES_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        rules.extend(data.get("rules", []))
    return rules


_RULES = _load_rules()


def evaluate(service_id: str, payload: dict, context: dict) -> list[RuleResult]:
    context = context or {}
    return [
        _evaluate_rule(rule, payload, context)
        for rule in _RULES
        if rule["service_id"] == service_id
    ]
