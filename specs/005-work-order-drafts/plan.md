# Implementation Plan: Work-Order Drafts

**Branch**: `005-work-order-drafts` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-work-order-drafts/spec.md`; rules in
`specs/contracts/work-orders-audit.md`; interfaces in `specs/contracts/services.md`.

## Summary

A Python package, `copilot_workorders`, implementing the `WorkOrders` and `AuditLog` protocols of
`copilot_contracts.services` over Postgres (schema `app` in database `copilot`). The answer API
(003) calls it in-process; there is no HTTP here. Drafts are prefilled from an answer's
`work_order_suggestion`, edited, approved by a team lead of the asset's region when needed, and
submitted after explicit confirmation to a fake MaintPro or Servio outbox, exactly once per key.
Every action and every refusal writes an audit event in an append-only table.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: psycopg 3, pydantic 2, `copilot_contracts` (no new dependencies)

**Storage**: Postgres `copilot`, schema `app` (`drafts`, `audit_events`); corpus data only through
`serving.*` (`assets`, `can_see`, `passages_for`, `restricted_procedures`, `dataset_info`);
outbox files in `data/outbox/<system>/<idempotency_key>.json`

**Testing**: pytest against the real `serving` schema, each test in its own scratch schema
(`wo_test_<random>`, dropped afterwards); outbox and a copy of `users.json` in `tmp_path`

**Target Platform**: in-process library for the FastAPI app (003)

**Project Type**: library

**Performance Goals**: interactive; one short transaction per call (SC-004: draft and send for
approval in under a minute is a UI target, not a load target)

**Constraints**: no model calls; never read `.env`; never write `app` from tests

**Scale/Scope**: 12 users, 30 assets; tens of drafts

## Constitution Check

| Principle | How this design satisfies it |
|---|---|
| I. Authorization outside the model | Draft visibility is decided by code on every read: creator or region lead, **and** `serving.can_see` true for every cited passage with the caller's current groups. Groups come from the `Identity` the API builds from `users.json`; other users' groups (for eligible approvers) are re-read from `users.json` on every computation. Unknown passage IDs fail closed. Audit entries shown to users follow the same rule. |
| II. Grounded and verifiable | Drafts keep the suggestion's citations; a draft can't be created citing a passage the creator can't see. |
| III. Abstain rather than guess | No asset, an unknown asset or an unknown region refuses creation instead of guessing a target system. |
| IV. Applicability by code | Target system from the asset's region in `serving.assets`; required groups of restricted procedures from `serving.restricted_procedures`. |
| V. Restricted procedures are safety controls | When a cited passage is tagged with a restricted procedure, the groups every access alternative of that procedure needs are added to `required_certification` (only ever added). An EU draft citing SOP-020 (chiller leak test and recharge procedure, restricted) therefore needs approval, and with no EU lead able to see it, reports "no eligible approver" and can't be submitted. |
| VI. The assistant drafts, humans commit | Submit requires `confirm is True` and the draft's idempotency key; approval by a region lead other than the creator when parts, certification or a campaign are involved; outbox writes are atomic and keyed; every action and refusal is audited with user, dataset version, passages and outcome. |
| VII. Measured before shipped | 47 tests cover every acceptance scenario and edge case of the spec; no retrieval, prompt or model change. |
| VIII. Simplest architecture | One package, two tables, a connection per call, row locks for concurrency, files for the outbox. No queue, no pool, no extra service. |

No violations; Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/005-work-order-drafts/
├── spec.md
├── plan.md      # this file
└── tasks.md
```

### Source Code

```text
src/copilot_workorders/
├── __init__.py        # build_services(database_url) -> (WorkOrders, AuditLog); migrate(conn)
├── db/app_schema.sql  # drafts, audit_events, append-only triggers; {schema} = app outside tests
├── service.py         # PgWorkOrders, PgAuditLog, SubmissionFailed
├── rules.py           # pure rules: approval reasons, target system, keys, outbox record shape
├── directory.py       # users.json lookup for eligible approvers
└── outbox.py          # fake MaintPro / Servio adapters (one file per key, written atomically)

tests/workorders/
├── conftest.py        # scratch schema per test, tmp outbox, tmp users.json
├── test_rules.py      # pure rules; signatures match the protocols exactly
├── test_drafts.py     # US1–US4 acceptance scenarios, edge cases, audit log
└── test_migrate.py    # idempotent migration; `app` only inside a rolled-back transaction
```

**Structure Decision**: single library package beside `copilot_answer`, added to the hatch
`packages` list in `pyproject.toml`.

## Design decisions

1. **Visibility** (FR-007): `viewable = (creator or lead for the draft's region) and no cited
   passage hidden`. Checked on `get`, `list_visible`, every mutation and audit reads. A non-viewer
   gets `NotVisible` (403) before any other check, so a lead from the other region trying to
   approve sees 403 `not_visible`, not `forbidden`.
2. **Eligible approvers**: users in `users.json` with `role-lead` and the region group, not the
   creator, who can see every cited passage now. Computed on every read, so a `users.json` change
   shows on the next call. Empty, with "no eligible approver" in `approval_reasons`, when approval
   is needed and nobody qualifies; empty when no approval is needed (as in the web client mock).
3. **Approval reasons**: `parts`, `certification`, `campaign`, `specialist`, `return visit` (the
   words the web client already maps). The last two come from the draft's `needs_specialist` and
   `return_visit` flags (default false, editable by PATCH; not on the suggestion).
   `required_certification` holds `cert-*` groups only: non-certification groups from the
   suggestion are dropped (recorded in the audit event), and only the `cert-*` groups of cited
   restricted procedures are added by rule. Citations are not editable, so nothing added by rule
   can be removed.
4. **Who does what**: only the creator edits, requests approval and submits; only a region lead
   other than the creator approves or rejects, and only in `pending_approval`. Requesting approval
   is refused when no approval is needed or when there is no eligible approver.
5. **Lifecycle**: as in the contract. Editing a `rejected` draft returns it to `draft`; the
   decision note is kept. A `rejected` draft may also go straight back to `pending_approval`.
   `submitted` and `approved` drafts are not editable (`NotEditable`).
6. **Idempotency**: the server issues `idempotency_key` at creation; submit must present that
   key (the web client already sends it). The row is locked (`FOR UPDATE`) for the whole submit,
   so concurrent retries serialize. The outbox file is created by hard-linking a complete temp
   file, so it is never partial and never replaced. The fake reference is derived from the key,
   so a retry after "file written, commit lost" finds the file and completes with the same
   reference. A repeat after success returns the stored draft and writes nothing (audited as
   `duplicate`).
7. **Outbox failure**: `copilot_contracts.services.SubmissionFailed` (code `submission_failed`,
   503); the transaction rolls back, the draft stays `approved`, and a retry is safe.
   **Unknown region**: creation is refused with `InvalidRequest` (422), as the spec now says.
8. **Outbox record**: `{system, idempotency_key, external_ref, work_order, copilot}` where
   `work_order` uses the column names of the corpus exports (MaintPro: `WO_No, Date, Site, Asset,
   Model, Serial, Event_Type=CM, Fault, Tech, Notes, Parts "41-0046 x1; …", Status=OPEN`; Servio:
   `werkorder, datum, object, locatie, type=Storing, storingscode, omschrijving, monteur,
   onderdelen "1x 41-0046, …", status=Open`). References start `MP-` / `SV-`, as in the mock.
9. **Audit**: one event per action in the same transaction as the change. Refusals are audited
   after the rollback: `access_denied` for `NotVisible` / `Forbidden`, otherwise the action's
   kind with the error code as outcome. Request approval has no kind of its own and is recorded
   as `draft_edited` with outcome `approval_requested`. Draft events carry the draft's citations
   as `passage_ids`; refusals carry none. The table rejects UPDATE, DELETE and TRUNCATE by
   trigger.
10. **Audit visibility**: an event with a draft goes to whoever may view that draft now; any other
    event only to its own user; and in both cases only if every passage in it is visible now.
11. **Storage access**: one connection and one transaction per call (no pool; FastAPI's thread
    pool is the only concurrency). `DATABASE_URL`, `USERS_PATH` and `DATA_DIR` are read from the
    process environment with the ingest defaults; `.env` is never loaded here.
