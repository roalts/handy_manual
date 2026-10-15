"""In-process service interfaces between 003 (answer API) and 005 (work orders)
(specs/contracts/services.md). The API owns HTTP; work orders own drafts and the audit log."""
from typing import Protocol

from copilot_contracts.answer import Identity, PartLine, WorkOrderSuggestion
from copilot_contracts.work_orders import AuditEvent, WorkOrderDraft


class ServiceError(Exception):
    """Base for errors the API maps to the codes in http-api.md, section Errors."""
    code = "invalid_request"
    http_status = 422


class NotFound(ServiceError):
    code, http_status = "not_found", 404


class NotVisible(ServiceError):
    code, http_status = "not_visible", 403


class Forbidden(ServiceError):
    code, http_status = "forbidden", 403


class InvalidState(ServiceError):
    code, http_status = "invalid_state", 409


class NotEditable(ServiceError):
    code, http_status = "not_editable", 409


class InvalidRequest(ServiceError):
    code, http_status = "invalid_request", 422


class SubmissionFailed(ServiceError):
    """The target system (or its fake outbox) could not be written; the draft stays approved."""
    code, http_status = "submission_failed", 503


class AuditLog(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Append only. Never raises for a duplicate event_id; ignores it."""

    def visible_events(self, identity: Identity, *, answer_id: str | None = None,
                       draft_id: str | None = None) -> list[AuditEvent]: ...


class WorkOrders(Protocol):
    def create(self, identity: Identity, answer_id: str | None,
               suggestion: WorkOrderSuggestion, *, summary: str | None = None,
               work_steps: str | None = None, priority: str | None = None,
               fault_code: str | None = None, parts: list[PartLine] | None = None,
               asset_id: str | None = None) -> WorkOrderDraft: ...

    def get(self, identity: Identity, draft_id: str) -> WorkOrderDraft: ...

    def list_visible(self, identity: Identity, *, mine: bool = False) -> list[WorkOrderDraft]: ...

    def edit(self, identity: Identity, draft_id: str, changes: dict) -> WorkOrderDraft:
        """changes: only summary, work_steps, priority, fault_code, parts, needs_specialist,
        return_visit (else InvalidRequest; citations are never editable)."""

    def request_approval(self, identity: Identity, draft_id: str) -> WorkOrderDraft: ...

    def approve(self, identity: Identity, draft_id: str, note: str | None) -> WorkOrderDraft: ...

    def reject(self, identity: Identity, draft_id: str, note: str | None) -> WorkOrderDraft: ...

    def submit(self, identity: Identity, draft_id: str, *, confirm: bool,
               idempotency_key: str) -> WorkOrderDraft: ...
