"""Drafts and the audit log in Postgres, behind the protocols in copilot_contracts.services.

Corpus data (assets, passage visibility, restricted procedures) is read only through `serving.*`.
Every method opens its own connection and runs in one transaction, so a draft change and its
audit event commit together. Refusals are audited after the rollback, in their own transaction.
"""
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Annotated, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints, ValidationError

from copilot_contracts.answer import Identity, PartLine, WorkOrderSuggestion
from copilot_contracts.services import (
    Forbidden,
    InvalidRequest,
    InvalidState,
    NotEditable,
    NotFound,
    NotVisible,
    ServiceError,
    SubmissionFailed,
)
from copilot_contracts.work_orders import AuditEvent, WorkOrderDraft
from copilot_workorders import rules
from copilot_workorders.directory import UsersFile
from copilot_workorders.outbox import FakeOutbox

_DRAFT_FIELDS = tuple(WorkOrderDraft.model_fields)
_EVENT_FIELDS = tuple(AuditEvent.model_fields)


class _Changes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                              max_length=2000)] = ""
    work_steps: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)] = ""
    priority: Literal["low", "medium", "high"] = "medium"
    fault_code: Annotated[str, StringConstraints(strip_whitespace=True,
                                                 max_length=64)] | None = None
    parts: list[PartLine] = []
    needs_specialist: StrictBool = False
    return_visit: StrictBool = False


def _clean(changes: dict) -> dict:
    """Validated, normalized values of just the given editable fields; InvalidRequest otherwise."""
    if not isinstance(changes, dict):
        raise InvalidRequest("changes must be an object")
    if unknown := sorted(set(changes) - rules.EDITABLE):
        raise InvalidRequest(f"not editable: {', '.join(unknown)}; editable fields are "
                             f"{', '.join(sorted(rules.EDITABLE))}")
    try:
        dumped = _Changes.model_validate(changes).model_dump()
        clean = {k: dumped[k] for k in changes}
    except ValidationError as e:
        raise InvalidRequest(_validation_text(e)) from None
    if "fault_code" in clean and not clean["fault_code"]:
        clean["fault_code"] = None
    if any(p["quantity"] < 1 for p in clean.get("parts", [])):
        raise InvalidRequest("parts: quantity must be at least 1")
    return clean


def _validation_text(e: ValidationError) -> str:
    """Validation errors as one `field: message; ...` line."""
    return "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())


def _now() -> datetime:
    """Current time in UTC."""
    return datetime.now(UTC)


class _Store:
    """Shared reads: serving lookups, draft access rule, audit insert."""

    def __init__(self, database_url: str, schema: str, users: UsersFile):
        """`schema` holds the drafts and audit tables; `users` is the approver directory."""
        self.url = database_url
        self.schema = schema
        self.users = users

    def connect(self) -> psycopg.Connection:
        """New connection returning rows as dicts."""
        return psycopg.connect(self.url, row_factory=dict_row)

    # --- serving.* ---------------------------------------------------------------------------

    @staticmethod
    def hidden(conn, groups: Iterable[str], passage_ids: Iterable[str]) -> set[str]:
        """Passages among `passage_ids` that `groups` can't see now (fail closed: unknown IDs)."""
        ids = list(dict.fromkeys(passage_ids))
        if not ids:
            return set()
        rows = conn.execute(
            "SELECT p FROM unnest(%s::text[]) p"
            " WHERE NOT serving.can_see('passage', p, %s::text[])",
            [ids, sorted(groups)]).fetchall()
        return {r["p"] for r in rows}

    @staticmethod
    def asset(conn, asset_id: str) -> dict | None:
        """Fleet register row of the asset, or None if unknown."""
        return conn.execute(
            "SELECT asset_id, model, serial, site, site_name, region FROM serving.assets"
            " WHERE asset_id = %s", [asset_id]).fetchone()

    @staticmethod
    def dataset_version(conn) -> str | None:
        """Dataset version serving holds, or None when it reports none."""
        row = conn.execute("SELECT dataset_version FROM serving.dataset_info()").fetchone()
        return row["dataset_version"] if row else None

    @staticmethod
    def procedure_certifications(conn, groups: Iterable[str], citations: list[str]) -> list[str]:
        """Certification groups needed by restricted procedures tagged on the cited passages."""
        if not citations:
            return []
        rows = conn.execute(
            "SELECT r.name, r.required_groups FROM serving.restricted_procedures r"
            " WHERE r.name IN (SELECT unnest(p.restricted_tags)"
            "                  FROM serving.passages_for(%s::text[]) p"
            "                  WHERE p.passage_id = ANY(%s::text[]))",
            [sorted(groups), citations]).fetchall()
        alternatives: dict[str, list[frozenset[str]]] = {}
        for r in rows:
            alternatives.setdefault(r["name"], []).append(frozenset(r["required_groups"]))
        needed: set[str] = set()
        for alts in alternatives.values():
            needed |= rules.required_groups_of(alts)
        return sorted(rules.certifications(needed))

    # --- drafts ------------------------------------------------------------------------------

    def draft_rows(self, conn, where: str, params: list, *, lock: bool = False) -> list[dict]:
        """Drafts matching `where`, newest first; `lock` locks the rows for an update."""
        sql = f"SELECT * FROM {self.schema}.drafts WHERE {where} ORDER BY created_at DESC"
        return conn.execute(sql + (" FOR UPDATE" if lock else ""), params).fetchall()

    def viewable(self, conn, identity: Identity, row: dict) -> bool:
        """Creator or the region's team lead, and only while every cited passage is visible."""
        role_ok = (identity.user_id == row["created_by"]
                   or rules.is_lead_for(identity.groups, row["region"]))
        return role_ok and not self.hidden(conn, identity.groups, row["citations"])

    def eligible_approvers(self, conn, row: dict) -> list[str]:
        """Team leads of the region, other than the creator, who can see every cited passage."""
        return [u.user_id for u in self.users.users()
                if u.user_id != row["created_by"] and rules.is_lead_for(u.groups, row["region"])
                and not self.hidden(conn, u.groups, row["citations"])]

    def to_model(self, conn, row: dict) -> WorkOrderDraft:
        """Draft with approval reasons and approvers computed now; NO_APPROVER if none qualifies."""
        needs = rules.approval_needs(row["parts"], row["required_certification"],
                                     row["campaign_code"], row["needs_specialist"],
                                     row["return_visit"])
        eligible = self.eligible_approvers(conn, row) if needs else []
        reasons = needs + ([rules.NO_APPROVER] if needs and not eligible else [])
        return WorkOrderDraft(**{k: row[k] for k in _DRAFT_FIELDS if k in row},
                              approval_reasons=reasons, eligible_approvers=eligible)

    # --- audit -------------------------------------------------------------------------------

    def insert_event(self, conn, event: AuditEvent) -> None:
        """Insert an audit event; a repeated event ID is ignored."""
        conn.execute(
            f"INSERT INTO {self.schema}.audit_events (event_id, at, user_id, kind, answer_id,"
            " draft_id, dataset_version, passage_ids, outcome, details)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING",
            [event.event_id, event.at, event.user_id, event.kind, event.answer_id,
             event.draft_id, event.dataset_version, event.passage_ids, event.outcome,
             Jsonb(event.details)])

    def event(self, conn, identity: Identity, kind: str, outcome: str, *,
              draft_id: str | None = None, answer_id: str | None = None,
              passage_ids: Iterable[str] = (), details: dict | None = None) -> None:
        """Audit an action by `identity`, stamped with a new ID, the time and dataset version."""
        self.insert_event(conn, AuditEvent(
            event_id=f"ev_{uuid.uuid4().hex}", at=_now(), user_id=identity.user_id, kind=kind,
            answer_id=answer_id, draft_id=draft_id, dataset_version=self.dataset_version(conn),
            passage_ids=list(passage_ids), outcome=outcome, details=details or {}))


class PgAuditLog:
    def __init__(self, store: _Store):
        """Audit log over the shared store."""
        self._s = store

    def record(self, event: AuditEvent) -> None:
        """Store an event in its own transaction; a repeated event ID is ignored."""
        with self._s.connect() as conn:
            self._s.insert_event(conn, event)

    def visible_events(self, identity: Identity, *, answer_id: str | None = None,
                       draft_id: str | None = None) -> list[AuditEvent]:
        """Same rule as drafts: a draft's events go to whoever may view the draft now; other
        events only to their own user; and every event only if all its passages are visible."""
        s = self._s
        where, params = ["true"], []
        if answer_id is not None:
            where.append("answer_id = %s")
            params.append(answer_id)
        if draft_id is not None:
            where.append("draft_id = %s")
            params.append(draft_id)
        if answer_id is None and draft_id is None:
            where.append("(user_id = %s OR draft_id IS NOT NULL)")
            params.append(identity.user_id)
        with s.connect() as conn:
            rows = conn.execute(f"SELECT * FROM {s.schema}.audit_events"
                                f" WHERE {' AND '.join(where)} ORDER BY seq", params).fetchall()
            hidden = s.hidden(conn, identity.groups, (p for r in rows for p in r["passage_ids"]))
            draft_ids = sorted({r["draft_id"] for r in rows if r["draft_id"]})
            drafts = {d["draft_id"]: d for d in
                      s.draft_rows(conn, "draft_id = ANY(%s)", [draft_ids])} if draft_ids else {}
            can_view = {i: s.viewable(conn, identity, d) for i, d in drafts.items()}
        out = []
        for r in rows:
            if hidden.intersection(r["passage_ids"]):
                continue
            if r["draft_id"] and r["draft_id"] in drafts:
                if not can_view[r["draft_id"]]:
                    continue
            elif r["user_id"] != identity.user_id:
                continue
            out.append(AuditEvent(**{k: r[k] for k in _EVENT_FIELDS}))
        return out


class PgWorkOrders:
    def __init__(self, store: _Store, outbox: FakeOutbox):
        """Drafts over the shared store; submissions are written to `outbox`."""
        self._s = store
        self._outbox = outbox

    # --- plumbing ----------------------------------------------------------------------------

    def _act(self, identity: Identity, kind: str | None, action: str, draft_id: str | None,
             fn: Callable[[psycopg.Connection], WorkOrderDraft]):
        """Run `fn` in one transaction. Refusals are audited after the rollback, access refusals
        as `access_denied` and others as `kind` if given; NotFound is never audited."""
        try:
            with self._s.connect() as conn:
                return fn(conn)
        except NotFound:
            raise
        except (NotVisible, Forbidden) as e:
            self._refused(identity, "access_denied", action, draft_id, e)
            raise
        except ServiceError as e:
            if kind:
                self._refused(identity, kind, action, draft_id, e)
            raise

    def _refused(self, identity, kind, action, draft_id, e: ServiceError) -> None:
        """Audit a refused action in its own transaction."""
        with self._s.connect() as conn:
            self._s.event(conn, identity, kind, e.code, draft_id=draft_id,
                          details={"action": action, "detail": str(e)})

    def _load(self, conn, identity: Identity, draft_id: str, *, lock: bool = False) -> dict:
        """Draft row if `identity` may view it, else NotFound or NotVisible."""
        rows = self._s.draft_rows(conn, "draft_id = %s", [draft_id], lock=lock)
        if not rows:
            raise NotFound(f"no draft {draft_id}")
        if not self._s.viewable(conn, identity, rows[0]):
            raise NotVisible("this draft is not visible to you")
        return rows[0]

    def _update(self, conn, draft_id: str, values: dict) -> dict:
        """Set `values` and `updated_at` on a draft; returns the updated row."""
        values = {**values, "updated_at": _now()}
        cols = ", ".join(f"{k} = %s" for k in values)
        params = [Jsonb(v) if k == "parts" else v for k, v in values.items()]
        return conn.execute(f"UPDATE {self._s.schema}.drafts SET {cols} WHERE draft_id = %s"
                            " RETURNING *", [*params, draft_id]).fetchone()

    # --- WorkOrders protocol -----------------------------------------------------------------

    def create(self, identity: Identity, answer_id: str | None,
               suggestion: WorkOrderSuggestion, *, summary: str | None = None,
               work_steps: str | None = None, priority: str | None = None,
               fault_code: str | None = None, parts: list[PartLine] | None = None,
               asset_id: str | None = None) -> WorkOrderDraft:
        """Draft prefilled from the suggestion, with the given edits applied, adding certifications
        required by restricted procedures on the cited passages. Refused if a citation is hidden."""
        s = self._s

        def run(conn) -> WorkOrderDraft:
            """Validate, insert and audit the draft."""
            if suggestion.asset_id and asset_id and suggestion.asset_id != asset_id:
                raise InvalidRequest(f"the suggestion is for {suggestion.asset_id}, not {asset_id}")
            chosen = suggestion.asset_id or asset_id
            if not chosen:
                raise InvalidRequest("asset_id is required: choose the machine for this work order")
            asset = s.asset(conn, chosen)
            if asset is None:
                raise InvalidRequest(f"unknown asset {chosen}")
            system = rules.target_system(asset["region"])
            if system is None:
                raise InvalidRequest(f"asset {chosen} has no known region, so no target system")
            citations = rules.dedupe(suggestion.citations)
            if s.hidden(conn, identity.groups, citations):
                raise NotVisible("a cited passage is not visible to you")

            prefill = {"summary": suggestion.summary, "work_steps": "", "priority": "medium",
                       "fault_code": suggestion.fault_code,
                       "parts": [p.model_dump() for p in suggestion.parts],
                       "needs_specialist": False, "return_visit": False}
            given = {"summary": summary, "work_steps": work_steps, "priority": priority,
                     "fault_code": fault_code, "parts": parts}
            edits = _clean({k: v for k, v in given.items() if v is not None})
            values = {**_clean(prefill), **edits}
            suggested = rules.certifications(suggestion.required_certification)
            by_rule = [g for g in s.procedure_certifications(conn, identity.groups, citations)
                       if g not in suggested]
            now = _now()
            row = {
                "draft_id": f"wo_{uuid.uuid4().hex[:24]}", "created_by": identity.user_id,
                "created_at": now, "updated_at": now, "answer_id": answer_id,
                "asset_id": chosen, "region": asset["region"], "target_system": system,
                **values,
                "required_certification": rules.dedupe([*suggested, *by_rule]),
                "campaign_code": suggestion.campaign_code, "citations": citations,
                "status": "draft", "idempotency_key": f"wo-{uuid.uuid4().hex}",
            }
            cols = ", ".join(row)
            marks = ", ".join(["%s"] * len(row))
            params = [Jsonb(v) if k == "parts" else v for k, v in row.items()]
            stored = conn.execute(f"INSERT INTO {s.schema}.drafts ({cols}) VALUES ({marks})"
                                  " RETURNING *", params).fetchone()
            changed = {k: {"before": prefill[k], "after": values[k]}
                       for k in edits if values[k] != prefill[k]}
            s.event(conn, identity, "draft_created", "created", draft_id=row["draft_id"],
                    answer_id=answer_id, passage_ids=citations,
                    details={"prefill": suggestion.model_dump(mode="json"), "edits": changed,
                             "certification_added_by_rule": by_rule,
                             "non_certification_groups_dropped": [
                                 g for g in suggestion.required_certification
                                 if g not in suggested]})
            return s.to_model(conn, stored)

        return self._act(identity, "draft_created", "create", None, run)

    def get(self, identity: Identity, draft_id: str) -> WorkOrderDraft:
        """Draft if `identity` may view it; else NotFound, or NotVisible (audited as denied)."""
        def run(conn):
            """Load the draft as a model."""
            return self._s.to_model(conn, self._load(conn, identity, draft_id))
        return self._act(identity, None, "get", draft_id, run)

    def list_visible(self, identity: Identity, *, mine: bool = False) -> list[WorkOrderDraft]:
        """Own drafts and, unless `mine`, those of regions `identity` leads; viewable ones only."""
        s = self._s
        regions = [r for r in rules.REGION_GROUP if rules.is_lead_for(identity.groups, r)]
        with s.connect() as conn:
            if mine:
                rows = s.draft_rows(conn, "created_by = %s", [identity.user_id])
            else:
                rows = s.draft_rows(conn, "created_by = %s OR region = ANY(%s::text[])",
                                    [identity.user_id, regions])
            return [s.to_model(conn, r) for r in rows if s.viewable(conn, identity, r)]

    def edit(self, identity: Identity, draft_id: str, changes: dict) -> WorkOrderDraft:
        """Creator's edit of a draft or rejected draft, which returns it to `draft` status."""
        s = self._s

        def run(conn):
            """Apply and audit the edit, also when nothing changed."""
            row = self._load(conn, identity, draft_id, lock=True)
            if row["created_by"] != identity.user_id:
                raise Forbidden("only the creator can edit this draft")
            if row["status"] not in ("draft", "rejected"):
                raise NotEditable(f"a draft in {row['status']} can't be edited")
            clean = _clean(changes)
            diff = {k: v for k, v in clean.items() if row[k] != v}
            new = self._update(conn, draft_id, {**diff, "status": "draft"})
            s.event(conn, identity, "draft_edited", "edited" if diff else "unchanged",
                    draft_id=draft_id, answer_id=row["answer_id"], passage_ids=row["citations"],
                    details={"before": {k: row[k] for k in diff}, "after": diff,
                             "status_before": row["status"], "status_after": "draft"})
            return s.to_model(conn, new)

        return self._act(identity, "draft_edited", "edit", draft_id, run)

    def request_approval(self, identity: Identity, draft_id: str) -> WorkOrderDraft:
        """Creator sends a draft to `pending_approval`; refused if it needs no approval or no
        eligible approver exists."""
        s = self._s

        def run(conn):
            """Check the draft and move it to `pending_approval`."""
            row = self._load(conn, identity, draft_id, lock=True)
            if row["created_by"] != identity.user_id:
                raise Forbidden("only the creator can request approval")
            if row["status"] not in ("draft", "rejected"):
                raise InvalidState(f"a draft in {row['status']} can't be sent for approval")
            draft = s.to_model(conn, row)
            if not draft.approval_reasons:
                raise InvalidState("no approval needed; submit it directly")
            if rules.NO_APPROVER in draft.approval_reasons:
                raise InvalidState(f"{rules.NO_APPROVER}: no {row['region']} team lead other "
                                   "than you can see every cited passage")
            new = self._update(conn, draft_id, {"status": "pending_approval"})
            s.event(conn, identity, "draft_edited", "approval_requested", draft_id=draft_id,
                    answer_id=row["answer_id"], passage_ids=row["citations"],
                    details={"status_before": row["status"], "status_after": "pending_approval",
                             "approval_reasons": draft.approval_reasons,
                             "eligible_approvers": draft.eligible_approvers})
            return s.to_model(conn, new)

        return self._act(identity, "draft_edited", "request_approval", draft_id, run)

    def approve(self, identity: Identity, draft_id: str, note: str | None) -> WorkOrderDraft:
        """Approve a pending draft as a team lead of its region other than its creator."""
        return self._decide(identity, draft_id, note, "approved")

    def reject(self, identity: Identity, draft_id: str, note: str | None) -> WorkOrderDraft:
        """Reject a pending draft as a team lead of its region other than its creator."""
        return self._decide(identity, draft_id, note, "rejected")

    def _decide(self, identity: Identity, draft_id: str, note: str | None,
                outcome: str) -> WorkOrderDraft:
        """Record `outcome` (approved or rejected) on a pending draft and audit it with the note."""
        s = self._s
        kind = "draft_approved" if outcome == "approved" else "draft_rejected"
        verb = "approve" if outcome == "approved" else "reject"

        def run(conn):
            """Check the decider and the draft, then record the decision."""
            row = self._load(conn, identity, draft_id, lock=True)
            if row["created_by"] == identity.user_id:
                raise Forbidden(f"you can't {verb} your own draft")
            if not rules.is_lead_for(identity.groups, row["region"]):
                raise Forbidden(f"only a {row['region']} team lead can {verb} this draft")
            if row["status"] != "pending_approval":
                raise InvalidState(f"a draft in {row['status']} can't be {outcome}")
            if note is not None and not isinstance(note, str):
                raise InvalidRequest("note must be text")
            clean_note = (note or "").strip() or None
            new = self._update(conn, draft_id, {"status": outcome, "decided_by": identity.user_id,
                                                "decided_at": _now(),
                                                "decision_note": clean_note})
            s.event(conn, identity, kind, outcome, draft_id=draft_id,
                    answer_id=row["answer_id"], passage_ids=row["citations"],
                    details={"note": clean_note})
            return s.to_model(conn, new)

        return self._act(identity, kind, verb, draft_id, run)

    def submit(self, identity: Identity, draft_id: str, *, confirm: bool,
               idempotency_key: str) -> WorkOrderDraft:
        """Creator's confirmed submission to the region's system under the draft's own key; a
        repeat with that key returns the submitted draft and is audited as a duplicate."""
        s = self._s

        def run(conn):
            """Check readiness, write the outbox record once and mark the draft submitted."""
            row = self._load(conn, identity, draft_id, lock=True)
            if row["created_by"] != identity.user_id:
                raise Forbidden("only the creator can submit this draft")
            if confirm is not True:
                raise InvalidRequest("submitting needs explicit confirmation (confirm: true)")
            if not rules.valid_key(idempotency_key):
                raise InvalidRequest("missing or malformed Idempotency-Key")
            if idempotency_key != row["idempotency_key"]:
                raise InvalidRequest("Idempotency-Key doesn't match this draft's key")
            system = row["target_system"]
            if row["status"] == "submitted":
                s.event(conn, identity, "draft_submitted", "duplicate", draft_id=draft_id,
                        answer_id=row["answer_id"], passage_ids=row["citations"],
                        details={"target_system": system, "external_ref": row["external_ref"],
                                 "idempotency_key": idempotency_key})
                return s.to_model(conn, row)
            draft = s.to_model(conn, row)
            ready = row["status"] == "approved" or (row["status"] == "draft"
                                                    and not draft.approval_reasons)
            if not ready:
                why = (f"approval needed ({', '.join(draft.approval_reasons)})"
                       if row["status"] == "draft" else f"the draft is {row['status']}")
                raise InvalidState(f"can't submit yet: {why}")
            asset = s.asset(conn, row["asset_id"])
            if asset is None:
                raise InvalidState(f"asset {row['asset_id']} is no longer in the fleet register")
            now = _now()
            record = rules.outbox_record(
                system=system, key=idempotency_key, ref=rules.external_ref(system, idempotency_key),
                draft=row, asset=asset, submitted_by=identity.user_id, submitted_at=now)
            try:
                stored = self._outbox.write_once(system, idempotency_key, record)
            except OSError as e:
                raise SubmissionFailed(f"couldn't write to the {system} outbox ({e.strerror}); "
                                       "the draft is unchanged and a retry with the same key "
                                       "is safe") from e
            if stored["copilot"]["draft_id"] != draft_id:
                raise SubmissionFailed("the outbox already holds this key for another draft")
            new = self._update(conn, draft_id, {"status": "submitted",
                                                "external_ref": stored["external_ref"],
                                                "submitted_by": identity.user_id,
                                                "submitted_at": now})
            s.event(conn, identity, "draft_submitted", "submitted", draft_id=draft_id,
                    answer_id=row["answer_id"], passage_ids=row["citations"],
                    details={"target_system": system, "external_ref": stored["external_ref"],
                             "idempotency_key": idempotency_key})
            return s.to_model(conn, new)

        return self._act(identity, "draft_submitted", "submit", draft_id, run)
