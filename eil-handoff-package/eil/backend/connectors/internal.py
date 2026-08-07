from datetime import datetime, timezone

from backend.catalog import load_catalog
from backend.connectors.base import (
    CommonApproval,
    CommonRequest,
    CommonRequestState,
    ExternalRef,
    ServiceConnector,
)
from backend.db import SessionLocal
from backend.models import Approval as ApprovalModel
from backend.models import Request


class InternalConnector(ServiceConnector):
    """Fulfils requests inside this platform's own SQLite store, so a service
    with `connector: internal` needs no external system at all.
    """

    name = "internal"

    def create_request(self, common: CommonRequest) -> ExternalRef:
        session = SessionLocal()
        try:
            external_id = common.external_hints.get("request_id")
            request = session.get(Request, external_id) if external_id else None
            now = datetime.now(timezone.utc)

            if request is None:
                external_id = external_id or f"REQ-{int(now.timestamp())}"
                session.add(
                    Request(
                        id=external_id,
                        employee_id=common.employee_ref,
                        service_id=common.service_id,
                        intent=common.external_hints.get("intent", ""),
                        status=common.external_hints.get("status", "DRAFT"),
                        channel=common.external_hints.get("channel", "WEB"),
                        payload=common.fields,
                        missing_fields=common.external_hints.get("missing_fields", []),
                        assigned_department_id=common.external_hints.get("assigned_department_id"),
                        pending_approver_id=common.external_hints.get("pending_approver_id"),
                        tier=common.tier,
                        thread_id=common.external_hints.get("thread_id"),
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                request.payload = common.fields
                request.tier = common.tier
                request.updated_at = now

            for approval in common.approvals:
                self._upsert_approval(session, external_id, approval)

            session.commit()
        finally:
            session.close()

        return ExternalRef(connector=self.name, external_id=external_id)

    def update_status(self, ref: ExternalRef, status: str) -> None:
        session = SessionLocal()
        try:
            request = session.get(Request, ref.external_id)
            if request is None:
                return
            request.status = status
            request.updated_at = datetime.now(timezone.utc)
            if status in ("CLOSED", "REJECTED", "CANCELLED"):
                request.closed_at = datetime.now(timezone.utc)
            session.commit()
        finally:
            session.close()

    def add_approval(self, ref: ExternalRef, approval: CommonApproval) -> None:
        session = SessionLocal()
        try:
            self._upsert_approval(session, ref.external_id, approval)
            session.commit()
        finally:
            session.close()

    def fetch_state(self, ref: ExternalRef) -> CommonRequestState:
        session = SessionLocal()
        try:
            request = session.get(Request, ref.external_id)
            if request is None:
                return CommonRequestState(ref=ref, status="UNKNOWN")

            rows = (
                session.query(ApprovalModel)
                .filter_by(request_id=ref.external_id)
                .order_by(ApprovalModel.sequence)
                .all()
            )
            approvals = [
                CommonApproval(
                    approver_ref=row.approver_id,
                    sequence=row.sequence,
                    status=row.status,
                    reason=row.reason,
                    required_by_clause_ref=row.required_by_clause_ref,
                    comment=row.comment,
                    decided_at=row.decided_at.isoformat() if row.decided_at else None,
                )
                for row in rows
            ]
            return CommonRequestState(
                ref=ref, status=request.status, approvals=approvals, fields=request.payload or {}
            )
        finally:
            session.close()

    @staticmethod
    def _upsert_approval(session, request_id: str, approval: CommonApproval) -> None:
        approval_id = f"APR-{request_id}-{approval.sequence}"
        row = session.get(ApprovalModel, approval_id)
        decided_at = (
            datetime.fromisoformat(approval.decided_at) if approval.decided_at else None
        )
        if row is None:
            session.add(
                ApprovalModel(
                    id=approval_id,
                    request_id=request_id,
                    approver_id=approval.approver_ref,
                    sequence=approval.sequence,
                    reason=approval.reason,
                    required_by_clause_ref=approval.required_by_clause_ref,
                    status=approval.status,
                    decided_at=decided_at,
                    comment=approval.comment,
                )
            )
        else:
            row.approver_id = approval.approver_ref
            row.status = approval.status
            row.reason = approval.reason
            row.required_by_clause_ref = approval.required_by_clause_ref
            row.comment = approval.comment
            row.decided_at = decided_at


_REGISTRY: dict[str, ServiceConnector] = {InternalConnector.name: InternalConnector()}


def get_connector(service_id: str) -> ServiceConnector:
    """Connector selection is per-service via `connector:` in the service YAML
    (SPEC §10). Adding another backend means registering it here and changing
    that one line of YAML — no call site changes.
    """
    service = load_catalog().get(service_id, {})
    connector_name = service.get("connector", InternalConnector.name)
    connector = _REGISTRY.get(connector_name)
    if connector is None:
        raise ValueError(
            f"Service {service_id} requests connector '{connector_name}', which is not registered."
        )
    return connector
