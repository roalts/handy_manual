---

description: "Tasks for 005 work-order drafts and the audit log"
---

# Tasks: Work-Order Drafts

**Input**: `specs/005-work-order-drafts/` (spec.md, plan.md), `specs/contracts/work-orders-audit.md`,
`specs/contracts/services.md`

**Tests**: required by the brief (every acceptance scenario, against scratch schemas).

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [x] T001 Create package `src/copilot_workorders/` and add it to the hatch `packages` list in `pyproject.toml`
- [x] T002 Create `tests/workorders/` with a scratch-schema fixture (`conftest.py`) that never touches `app`

## Phase 2: Foundational

- [x] T003 Schema `src/copilot_workorders/db/app_schema.sql`: `drafts`, `audit_events`, append-only triggers
- [x] T004 `migrate(conn, schema="app")`, idempotent, under an advisory lock, in `src/copilot_workorders/__init__.py`
- [x] T005 [P] Pure rules in `src/copilot_workorders/rules.py` (approval reasons, target system, keys, outbox record)
- [x] T006 [P] `users.json` lookup in `src/copilot_workorders/directory.py`
- [x] T007 [P] Fake outbox in `src/copilot_workorders/outbox.py` (atomic, write-once per key)
- [x] T008 `build_services(database_url)` returning `(PgWorkOrders, PgAuditLog)`
- [x] T009 Draft visibility, eligible approvers and audit insert in `src/copilot_workorders/service.py` (`_Store`)
- [x] T010 [P] Test that both classes match the `copilot_contracts.services` protocol signatures exactly (`tests/workorders/test_rules.py`)

## Phase 3: User Story 1 - Draft from an answer (P1)

- [x] T011 [US1] `create` from a suggestion with edits, asset and region checks, citation visibility, certification from restricted procedures
- [x] T012 [US1] `get`, `list_visible`, `edit` (editable fields only, creator only, before/after audited)
- [x] T013 [US1] Tests: restricted example as u03 (compressor technician without high-voltage certification); edit audited; non-editable fields refused

## Phase 4: User Story 2 - Approval when needed (P1)

- [x] T014 [US2] `request_approval`, `approve`, `reject` with region-lead and not-creator rules, `decision_note`
- [x] T015 [US2] Tests: refused submit then pending; u08 (NA team lead) approves; u07 (EU team lead) refused; creator refused; rejection kept and re-requested

## Phase 5: User Story 3 - Submit exactly once (P1)

- [x] T016 [US3] `submit` with `confirm`, the draft's key, row lock, outbox write-once, `SubmissionFailed`
- [x] T017 [US3] Tests: MaintPro once; same key same reference and one file; 8 concurrent submits one file; RTM-H-0007 (Rotterdam NK-600 chiller) to Servio; no confirm; wrong key; outbox failure then safe retry

## Phase 6: User Story 4 - Drafts respect access (P2)

- [x] T018 [US4] Visibility re-checked on every read and action; audit entries under the same rule (`visible_events`)
- [x] T019 [US4] Tests: u05 (EU refrigeration engineer) SOP-020 (chiller leak test and recharge, restricted) draft hidden from u11 (NA chiller technician with refrigerant certification) and u07; "no eligible approver"; cited passage gone in a new dataset; creator loses a group

## Phase 7: Polish

- [x] T020 Audit tests: full flow, append-only enforced, duplicate event IDs ignored
- [x] T021 `specs/005-work-order-drafts/plan.md`; report in `specs/coordination/work-orders.md`
- [ ] T022 Switch 003 (answer API) from fakes to `copilot_workorders.build_services` (owned by 003)
- [x] T023 Specialist and return-visit approval reasons from `needs_specialist` and `return_visit` (columns added by `migrate`, editable, in the outbox record)
- ~~T024 Let the creator remove citations~~: dropped (orchestrator declined; citations are not editable)

## Phase 8: Orchestrator review 2026-10-12 22:30

- [x] T025 Use `copilot_contracts.services.SubmissionFailed`; drop the local class
- [x] T026 Keep only `cert-*` groups in `required_certification` (suggestion and rule)
- [x] T027 Tests: specialist and return visit, citations not editable, `cert-*` only, unknown region refused with 422, migration of an earlier `drafts` table
