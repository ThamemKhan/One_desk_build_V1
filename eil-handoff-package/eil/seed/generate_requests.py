"""
Deterministic generator for the seeded historical request backlog.

Run once:  python seed/generate_requests.py
Output:    seed/requests.json

Seeded so the demo is reproducible. DO NOT regenerate after you have written
the demo script — request IDs are referenced by the presentation.

The backlog is shaped to make three things true:
  1. 12 SVC-ACCESS requests are BLOCKED on the DEPT-HR -> DEPT-SEC -> DEPT-DG ->
     DEPT-IT -> DEPT-HR ownership cycle. These are the demo climax.
  2. SVC-ACCESS shows a clear bottleneck signature: most requests enter at
     DEPT-HR and are later reassigned, so the resolution engine can propose a
     routing rule change that is statistically justified, not anecdotal.
  3. SVC-TRAVEL and SVC-LEAVE mostly flow cleanly, so the contrast is visible.
"""

import json
import random
from datetime import datetime, timedelta

random.seed(20260807)

NOW = datetime(2026, 8, 7, 9, 30)

EMPLOYEES = ["EMP-101", "EMP-102", "EMP-103", "EMP-104",
             "EMP-105", "EMP-106", "EMP-107", "EMP-108"]

TIER1 = ["Bengaluru", "Delhi", "Hyderabad", "Chennai", "Kolkata"]
SYSTEMS = ["production database", "customer data warehouse", "billing system"]

requests = []
counter = 10200


def new_id():
    global counter
    counter += 1
    return f"REQ-{counter}"


def ts(days_ago, hour=10):
    return (NOW - timedelta(days=days_ago)).replace(hour=hour).isoformat()


# ---------------------------------------------------------------------------
# 1. Twelve BLOCKED access requests — the ownership deadlock cohort
# ---------------------------------------------------------------------------
for i in range(12):
    days_ago = random.randint(4, 26)
    rid = new_id()
    requests.append({
        "id": rid,
        "employee_id": random.choice(EMPLOYEES),
        "service_id": "SVC-ACCESS",
        "intent": "ACCESS_REQUEST",
        "status": "BLOCKED",
        "channel": random.choice(["WEB", "TEAMS", "EMAIL"]),
        "tier": 3,
        "assigned_department_id": random.choice(["DEPT-HR", "DEPT-SEC", "DEPT-IT"]),
        "pending_approver_id": None,
        "stuck_reason_code": "OWNERSHIP_CYCLE",
        "payload": {
            "target_system": random.choice(SYSTEMS),
            "target_environment": "PRODUCTION",
            "access_level": random.choice(["READ", "WRITE"]),
            "access_duration_days": random.choice([30, 60, 90]),
            "business_justification": "Incident investigation and data reconciliation",
        },
        "missing_fields": [],
        "created_at": ts(days_ago),
        "updated_at": ts(max(0, days_ago - random.randint(1, 3))),
        "closed_at": None,
        "age_days": days_ago,
        "history": [
            {"at": ts(days_ago), "event": "ROUTED", "to": "DEPT-HR",
             "note": "Initial routing per ACCESS intake rule"},
            {"at": ts(days_ago - 1), "event": "REASSIGNED", "from": "DEPT-HR", "to": "DEPT-SEC",
             "note": "HR: security review required (POL-HR-118§7.1)"},
            {"at": ts(max(0, days_ago - 2)), "event": "REASSIGNED", "from": "DEPT-SEC", "to": "DEPT-DG",
             "note": "Security: data custodian approves production data (POL-SEC-204§4.2)"},
            {"at": ts(max(0, days_ago - 3)), "event": "REASSIGNED", "from": "DEPT-DG", "to": "DEPT-IT",
             "note": "Data Governance: delegated to application owner (POL-DG-090§2.2)"},
            {"at": ts(max(0, days_ago - 3)), "event": "REASSIGNED", "from": "DEPT-IT", "to": "DEPT-HR",
             "note": "IT: access requests must be raised via HR (POL-IT-330§3.4)"},
            {"at": ts(max(0, days_ago - 3)), "event": "BLOCKED",
             "note": "No department accepted approval ownership"},
        ],
        "reassignment_count": 4,
        "demo_note": "Deadlock cohort. Reroutes to DEPT-DG when the proposed rule is approved.",
    })

# ---------------------------------------------------------------------------
# 2. Eight access requests that eventually completed — but slowly and messily
# ---------------------------------------------------------------------------
for i in range(8):
    days_ago = random.randint(30, 75)
    reassigns = random.randint(2, 3)
    requests.append({
        "id": new_id(),
        "employee_id": random.choice(EMPLOYEES),
        "service_id": "SVC-ACCESS",
        "intent": "ACCESS_REQUEST",
        "status": "CLOSED",
        "channel": random.choice(["WEB", "TEAMS"]),
        "tier": 3,
        "assigned_department_id": "DEPT-DG",
        "pending_approver_id": None,
        "stuck_reason_code": None,
        "payload": {
            "target_system": random.choice(SYSTEMS),
            "target_environment": "PRODUCTION",
            "access_level": "READ",
            "access_duration_days": 30,
            "business_justification": "Reporting and analysis",
        },
        "missing_fields": [],
        "created_at": ts(days_ago),
        "updated_at": ts(days_ago - random.randint(6, 14)),
        "closed_at": ts(days_ago - random.randint(6, 14)),
        "age_days": random.randint(6, 14),
        "history": [
            {"at": ts(days_ago), "event": "ROUTED", "to": "DEPT-HR"},
            {"at": ts(days_ago - 2), "event": "REASSIGNED", "from": "DEPT-HR", "to": "DEPT-SEC"},
            {"at": ts(days_ago - 5), "event": "REASSIGNED", "from": "DEPT-SEC", "to": "DEPT-DG"},
            {"at": ts(days_ago - 8), "event": "APPROVED", "by": "EMP-203"},
            {"at": ts(days_ago - 9), "event": "CLOSED"},
        ],
        "reassignment_count": reassigns,
        "demo_note": "Eventually correct, but only after manual escalation. Evidence for the bottleneck claim.",
    })

# ---------------------------------------------------------------------------
# 3. Two access requests correctly declined under the privileged-grade rule
# ---------------------------------------------------------------------------
for _ in range(2):
    days_ago = random.randint(10, 40)
    requests.append({
        "id": new_id(),
        "employee_id": "EMP-107",
        "service_id": "SVC-ACCESS",
        "intent": "ACCESS_REQUEST",
        "status": "REJECTED",
        "channel": "WEB",
        "tier": 4,
        "assigned_department_id": "DEPT-SEC",
        "pending_approver_id": None,
        "stuck_reason_code": None,
        "payload": {
            "target_system": "production database",
            "target_environment": "PRODUCTION",
            "access_level": "PRIVILEGED",
            "access_duration_days": 30,
            "business_justification": "Schema change for feature work",
        },
        "missing_fields": [],
        "created_at": ts(days_ago),
        "updated_at": ts(days_ago),
        "closed_at": ts(days_ago),
        "age_days": 0,
        "history": [
            {"at": ts(days_ago), "event": "HARD_BLOCK",
             "note": "Grade G3 below G5 threshold (POL-SEC-311§2.4). Referred to manager."},
        ],
        "reassignment_count": 0,
        "demo_note": "Tier 4. Proves the system declines correctly and instantly, without an LLM judgement call.",
    })

# ---------------------------------------------------------------------------
# 4. Fourteen travel requests — mostly clean, four with lodging exceptions
# ---------------------------------------------------------------------------
for i in range(14):
    days_ago = random.randint(3, 60)
    dest = random.choice(TIER1)
    exception = i % 4 == 0
    rate = random.choice([11500, 12000, 13000]) if exception else random.choice([6500, 8200, 9400])
    nights = random.randint(2, 4)
    total = rate * nights + 9000
    status = "PENDING_APPROVAL" if days_ago < 5 else "CLOSED"
    requests.append({
        "id": new_id(),
        "employee_id": random.choice(EMPLOYEES),
        "service_id": "SVC-TRAVEL",
        "intent": "TRAVEL_BOOKING",
        "status": status,
        "channel": random.choice(["WEB", "TEAMS", "SLACK"]),
        "tier": 3 if exception else 2,
        "assigned_department_id": "DEPT-TRV",
        "pending_approver_id": "EMP-206" if status == "PENDING_APPROVAL" else None,
        "stuck_reason_code": None,
        "payload": {
            "destination_city": dest,
            "destination_city_tier": 1,
            "nights": nights,
            "hotel_rate_per_night": rate,
            "total_estimated_cost": total,
            "trip_type": "DOMESTIC",
            "purpose": "Client meeting",
        },
        "missing_fields": [],
        "created_at": ts(days_ago),
        "updated_at": ts(max(0, days_ago - 1)),
        "closed_at": ts(max(0, days_ago - 2)) if status == "CLOSED" else None,
        "age_days": 2 if status == "CLOSED" else days_ago,
        "history": [
            {"at": ts(days_ago), "event": "ROUTED", "to": "DEPT-TRV"},
            {"at": ts(max(0, days_ago - 1)), "event": "APPROVED", "by": "EMP-206"},
        ],
        "reassignment_count": 0,
        "has_exception": exception,
    })

# ---------------------------------------------------------------------------
# 5. Fourteen leave requests — the clean, fast control group
# ---------------------------------------------------------------------------
for i in range(14):
    days_ago = random.randint(2, 50)
    days = random.choice([1, 2, 3, 3, 5, 7])
    auto = days <= 3
    requests.append({
        "id": new_id(),
        "employee_id": random.choice(EMPLOYEES),
        "service_id": "SVC-LEAVE",
        "intent": "LEAVE_REQUEST",
        "status": "CLOSED",
        "channel": random.choice(["WEB", "TEAMS", "SLACK"]),
        "tier": 1 if auto else 2,
        "assigned_department_id": "DEPT-ENG",
        "pending_approver_id": None,
        "stuck_reason_code": None,
        "payload": {"leave_type": "ANNUAL", "requested_days": days},
        "missing_fields": [],
        "created_at": ts(days_ago),
        "updated_at": ts(days_ago),
        "closed_at": ts(days_ago if auto else days_ago - 1),
        "age_days": 0 if auto else 1,
        "history": [
            {"at": ts(days_ago), "event": "AUTO_APPROVED" if auto else "ROUTED", "to": "DEPT-ENG"},
            {"at": ts(days_ago), "event": "CLOSED"},
        ],
        "reassignment_count": 0,
    })

with open("seed/requests.json", "w") as f:
    json.dump(requests, f, indent=2)

blocked = [r for r in requests if r["status"] == "BLOCKED"]
print(f"total: {len(requests)}")
print(f"blocked on ownership cycle: {len(blocked)}")
print(f"first blocked id: {blocked[0]['id']}  last: {blocked[-1]['id']}")
print(f"access requests entering via DEPT-HR: "
      f"{sum(1 for r in requests if r['service_id']=='SVC-ACCESS' and any(h.get('to')=='DEPT-HR' for h in r['history']))}")
