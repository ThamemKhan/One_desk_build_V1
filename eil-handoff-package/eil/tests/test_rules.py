from backend.engine.rules import evaluate


def _find(results, rule_id):
    return next(r for r in results if r.rule_id == rule_id)


def test_hotel_cap_violates_at_12000():
    results = evaluate(
        "SVC-TRAVEL",
        {"destination_city_tier": 1, "hotel_rate_per_night": 12000},
        {},
    )
    result = _find(results, "RULE-TRV-HOTEL-CAP")
    assert result.applicable is True
    assert result.passed is False
    assert result.exceptionable is True
    assert result.actual == 12000
    assert result.limit == 10000


def test_hotel_cap_passes_at_9000():
    results = evaluate(
        "SVC-TRAVEL",
        {"destination_city_tier": 1, "hotel_rate_per_night": 9000},
        {},
    )
    result = _find(results, "RULE-TRV-HOTEL-CAP")
    assert result.applicable is True
    assert result.passed is True


def test_high_value_spend_adds_approval_not_a_breach():
    results = evaluate(
        "SVC-TRAVEL",
        {"total_estimated_cost": 36000},
        {},
    )
    result = _find(results, "RULE-FIN-HIGH-VALUE")
    assert result.applicable is True
    assert result.passed is False
    assert result.adds_approval is True
    assert result.exceptionable is False
    assert result.hard_block is False
    assert result.routing_correction is False


def test_grade_g3_privileged_access_is_hard_block_tier_4():
    results = evaluate(
        "SVC-ACCESS",
        {"access_level": "PRIVILEGED", "employee_grade_rank": 3},
        {},
    )
    result = _find(results, "RULE-SEC-PRIV-GRADE")
    assert result.applicable is True
    assert result.passed is False
    assert result.hard_block is True
    assert result.tier_override == 4
    assert result.exceptionable is False
