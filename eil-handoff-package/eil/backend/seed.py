import json
import re
from datetime import datetime
from pathlib import Path

import yaml

from backend.catalog import load_catalog
from backend.db import Base, SessionLocal, engine
from backend.models import Clause, Department, Employee, OwnershipEdge, Policy, Request

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
HEADING_RE = re.compile(r"^### (\S+)\s+(.+)$", re.MULTILINE)


def _load_json(name: str) -> list[dict]:
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def _parse_policy_file(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(raw)
    front_matter = yaml.safe_load(match.group(1))
    body_md = match.group(2).strip()
    return front_matter, body_md


def _split_clauses(policy_id: str, body_md: str, tags: list) -> list[dict]:
    matches = list(HEADING_RE.finditer(body_md))
    clauses = []
    for i, m in enumerate(matches):
        ref = m.group(1)
        heading = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body_md)
        clauses.append(
            {
                "id": f"{policy_id}§{ref}",
                "policy_id": policy_id,
                "ref": ref,
                "heading": heading,
                "text": body_md[start:end].strip(),
                "tags": tags,
            }
        )
    return clauses


def seed() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        for row in _load_json("departments.json"):
            session.add(
                Department(
                    id=row["id"],
                    name=row["name"],
                    head_employee_id=row.get("head_employee_id"),
                )
            )

        for row in _load_json("employees.json"):
            session.add(
                Employee(
                    id=row["id"],
                    name=row["name"],
                    email=row["email"],
                    title=row["title"],
                    department_id=row["department_id"],
                    manager_id=row.get("manager_id"),
                    location=row["location"],
                    city_tier=row["city_tier"],
                    cost_center=row["cost_center"],
                    grade=row["grade"],
                    leave_balance_days=row["leave_balance_days"],
                    roles=row["roles"],
                )
            )

        for path in sorted((SEED_DIR / "policies").glob("*.md")):
            front_matter, body_md = _parse_policy_file(path)
            session.add(
                Policy(
                    id=front_matter["id"],
                    title=front_matter["title"],
                    owner_department_id=front_matter["owner_department_id"],
                    policy_class=front_matter["policy_class"],
                    version=front_matter["version"],
                    effective_date=front_matter["effective_date"],
                    supersedes=front_matter.get("supersedes", []),
                    body_md=body_md,
                )
            )
            for clause in _split_clauses(
                front_matter["id"], body_md, front_matter.get("tags", [])
            ):
                session.add(Clause(**clause))

        ownership_matrix = yaml.safe_load(
            (SEED_DIR / "ownership_matrix.yaml").read_text(encoding="utf-8")
        )
        for edge in ownership_matrix["edges"]:
            session.add(
                OwnershipEdge(
                    id=edge["id"],
                    source_department_id=edge["source_department_id"],
                    service_id=edge["service_id"],
                    asserts_approver_department_id=edge["asserts_approver_department_id"],
                    clause_ref=edge["clause_ref"],
                    note=edge.get("note"),
                )
            )

        for row in _load_json("requests.json"):
            session.add(
                Request(
                    id=row["id"],
                    employee_id=row["employee_id"],
                    service_id=row["service_id"],
                    intent=row["intent"],
                    status=row["status"],
                    channel=row["channel"],
                    payload=row.get("payload", {}),
                    missing_fields=row.get("missing_fields", []),
                    assigned_department_id=row.get("assigned_department_id"),
                    pending_approver_id=row.get("pending_approver_id"),
                    tier=row["tier"],
                    thread_id=None,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    closed_at=datetime.fromisoformat(row["closed_at"])
                    if row.get("closed_at")
                    else None,
                    stuck_reason_code=row.get("stuck_reason_code"),
                )
            )

        session.commit()
    finally:
        session.close()

    catalog = load_catalog()
    enabled = sum(1 for s in catalog.values() if s.get("enabled"))
    print(f"Seeded database. Loaded {len(catalog)} service definitions ({enabled} enabled).")


if __name__ == "__main__":
    seed()
