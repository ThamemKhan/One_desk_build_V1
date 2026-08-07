from dataclasses import dataclass
from typing import Sequence

from backend.engine.rules import RuleResult

CONFIDENCE_PROCEED_THRESHOLD = 0.75
CONFIDENCE_DISAMBIGUATE_THRESHOLD = 0.45

_EXCEPTIONABLE_TIER = 3
_ADDS_APPROVAL_TIER = 2


def compute_tier(base_tier: int, rule_results: Sequence[RuleResult]) -> int:
    """Deterministic risk tier (SPEC §8). Never LLM-assigned.

    Starts from the service's base_tier and escalates per violated rule:
    - hard_block   -> the rule's own tier_override (defaults to 4)
    - exceptionable -> at least tier 3 ("High risk / policy exception")
    - adds_approval -> at least tier 2 ("Standard approval")
    - routing_correction -> no tier change; it is not a risk outcome
    The final tier is the maximum across base_tier and every violated rule.
    """
    tier = base_tier
    for result in rule_results:
        if not result.applicable or result.passed:
            continue
        if result.hard_block:
            tier = max(tier, result.tier_override or 4)
        elif result.exceptionable:
            tier = max(tier, _EXCEPTIONABLE_TIER)
        elif result.adds_approval:
            tier = max(tier, _ADDS_APPROVAL_TIER)
    return min(tier, 4)


@dataclass
class ConfidenceGate:
    band: str  # PROCEED | DISAMBIGUATE | HALT
    halt_reason: str | None = None


def gate_intent_confidence(confidence: float) -> ConfidenceGate:
    """Three intent-confidence bands (SPEC §8). Never LLM-assigned."""
    if confidence >= CONFIDENCE_PROCEED_THRESHOLD:
        return ConfidenceGate(band="PROCEED")
    if confidence >= CONFIDENCE_DISAMBIGUATE_THRESHOLD:
        return ConfidenceGate(band="DISAMBIGUATE")
    return ConfidenceGate(band="HALT", halt_reason="LOW_CONFIDENCE_INTENT")
