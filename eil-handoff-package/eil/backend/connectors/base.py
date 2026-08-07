from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# The platform-neutral seam (SPEC §10). Nothing in this file may name or assume
# a specific downstream system — swapping in another connector is a config
# change (`connector:` in the service YAML), not a rewrite.


@dataclass
class ExternalRef:
    """Opaque handle to the request as it exists in the downstream system."""

    connector: str
    external_id: str
    url: str | None = None


@dataclass
class CommonApproval:
    approver_ref: str
    sequence: int
    status: str
    reason: str | None = None
    required_by_clause_ref: str | None = None
    comment: str | None = None
    decided_at: str | None = None


@dataclass
class CommonRequest:
    service_id: str
    employee_ref: str
    fields: dict
    tier: int
    approvals: list[CommonApproval] = field(default_factory=list)
    clause_refs: list[str] = field(default_factory=list)
    external_hints: dict = field(default_factory=dict)


@dataclass
class CommonRequestState:
    ref: ExternalRef
    status: str
    approvals: list[CommonApproval] = field(default_factory=list)
    fields: dict = field(default_factory=dict)


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
