# Work orders (005) — work orders agent

**State**: done
**Current task**: none; review items 1, 2, 3 and 5 of 2026-10-12 22:30 applied
**Last updated**: 2026-10-12 22:15

## 2026-10-12 21:50 — Started, read the brief

STATUS (to: orchestrator)

Answers `orchestrator.md`, "2026-10-12 20:35 — Brief: work-order drafts (005)". Read the
constitution, the coordination README, the 005 spec, work-orders-audit.md, services.md,
http-api.md, serving.md and serving-additions.md, `copilot_contracts/{work_orders,services,answer}.py`,
`users.json`, `web-client.md` and `answer-engine.md`. No `answer-api.md` exists yet.

Facts from ds_0028 (dataset version 28) that the tests will use:

- p_f305f74b3d432a456bfd9221 (Compressor Troubleshooting Playbook, E-31 compressor drive
  overcurrent section; cited by the restricted example) is visible to u03 (compressor technician
  without high-voltage certification), u07 (EU team lead) and u08 (NA team lead).
- p_89e01fa9f9431d888616bfd8 (NK-600 chiller manual 8.4, recovery and recharge, tagged SOP-020:
  chiller leak test and recharge procedure, restricted) is visible to u05 (EU refrigeration
  engineer) and u11 (NA chiller technician with refrigerant certification), not to u07.
- Asset regions are `NA` or `EU` for all 30 assets in `serving.assets`.

Plan: the web client mock's reason words (`parts`, `certification`, `campaign`,
`no eligible approver`) and fake reference prefixes (`MP-`, `SV-`) are kept so the client works
unchanged against the real services.

## 2026-10-12 22:20 — Final report: work orders and audit log built, 47 tests pass

STATUS (to: orchestrator, answer API agent)

`copilot_workorders` is built and implements `WorkOrders` and `AuditLog` from
`copilot_contracts.services` exactly (a test compares every method signature with the protocols).
Re-read `orchestrator.md`, `answer-api.md`, `answer-engine.md` and `web-client.md` before
finishing; nothing there changes this work.

### For the answer API agent (003): how to switch from your fakes

```python
from copilot_workorders import build_services, migrate
with psycopg.connect(database_url) as conn:
    migrate(conn)                                   # once at start; idempotent, creates `app`
work_orders, audit = build_services(database_url)   # -> (WorkOrders, AuditLog)
```

- Reads `DATABASE_URL`, `USERS_PATH` and `DATA_DIR` from the process environment with the same
  defaults as ingestion (`postgresql:///copilot`, `users.json`, `data/`); it never loads `.env`.
  Optional keyword arguments: `schema`, `users_path`, `outbox_dir` (used by my tests).
- Errors are the `copilot_contracts.services` classes, plus `copilot_workorders.SubmissionFailed`
  (a `ServiceError`, code `submission_failed`, 503) when the outbox can't be written; map it
  generically through `code` and `http_status`.
- Submit must present the draft's own `idempotency_key` (what the web client sends); any other
  key is `422 invalid_request`.
- A lead from the other region acting on a draft gets `403 not_visible` (they can't see the
  draft at all), not `forbidden`. `forbidden` is for the creator approving their own draft, a
  non-creator editing or submitting, and similar.
- You record `answer`, `source_view` and your own `access_denied` events with `audit.record`.
  Draft events, including refused actions, are recorded by `copilot_workorders` itself.

### Built (per user story)

| Story | State | Notes |
|---|---|---|
| US1 (user story: draft from an answer) | done | Prefill only from the suggestion; edits at creation and later audited with before and after; only `summary`, `work_steps`, `priority`, `fault_code`, `parts` editable, by the creator. |
| US2 (user story: approval when needed) | done | Reasons `parts`, `certification`, `campaign`; approvers are `role-lead` for the asset's region, not the creator, able to see every cited passage, re-read from `users.json` on each read; `eligible_approvers` and "no eligible approver"; `decision_note`. |
| US3 (user story: submit exactly once) | done | `confirm is True` and the draft's key required; row lock; outbox file written atomically and never replaced; same key gives the same reference and no new file. MaintPro for NA (North America), Servio for EU (Europe). |
| US4 (user story: drafts respect access) | done | Creator or region lead, and `serving.can_see` for every cited passage with current groups, on every read and action; audit entries under the same rule. |

Behaviour worth knowing:

- **Certification decided by code** (same idea as your decision 2 for the engine): when a cited
  passage is tagged with a restricted procedure, the groups every access alternative of it needs
  (from `serving.restricted_procedures`) are added to `required_certification`, only ever added,
  and recorded in the audit event. A hand-written u05 (EU refrigeration engineer) draft citing the
  NK-600 manual 8.4 passage, tagged SOP-020 (chiller leak test and recharge procedure, restricted),
  gets cert-refrigerant (permission group: refrigerant certified) and family-chillers (permission
  group: Nordkyl chiller training). Without this it would need no approval and could be submitted
  to Servio with nobody else seeing it.
- Request approval is refused (`409 invalid_state`) when no approval is needed, or when there is
  no eligible approver. It's audited as `draft_edited` with outcome `approval_requested`, because
  the contract has no kind for it.
- Every refused action is audited too: `access_denied` for 403s, otherwise the action's kind with
  the error code as the outcome (for example 4 refused submits without `confirm`).
- The audit table rejects UPDATE, DELETE and TRUNCATE with a trigger.
- Outbox records use the corpus export column names (MaintPro `WO_No, Date, Site, Asset, …,
  Parts "41-0046 x1; …"`; Servio `werkorder, datum, object, …, onderdelen "1x 41-0046, …"`) plus
  a `copilot` block (draft, approver, citations). References are `MP-nnnnnnn` / `SV-nnnnnnn`, as
  in the web client mock.

### Files

- Code: `src/copilot_workorders/{__init__,service,rules,directory,outbox}.py`,
  `src/copilot_workorders/db/app_schema.sql`
- Tests: `tests/workorders/{conftest,test_rules,test_drafts,test_migrate}.py`
- Docs: `specs/005-work-order-drafts/{plan,tasks}.md` (T001–T021 done; T022–T024 open)
- Outside edit: `"src/copilot_workorders"` added to the hatch `packages` list in `pyproject.toml`
  (next to `src/copilot_api`, which 003 had already added). Nothing else outside my folders.

### Verification

- `uv run pytest tests/workorders`: **47 passed**. Each test runs in its own scratch schema
  (`wo_test_<random>`, dropped afterwards), with the outbox and a copy of `users.json` in a temp
  folder, against the real `serving` schema of ds_0028 (dataset version 28). Afterwards: no
  `app` schema rows from tests, no `wo_test_*` schemas left, no `data/outbox` folder. The only
  test that touches `app` runs `migrate` inside a transaction that is rolled back.
- Acceptance scenarios covered: US1 1–2, US2 1–4, US3 1–3, US4 1–3, and every edge case in the
  spec except "region unknown" (not possible in this corpus; see request 3). Also: same key gives
  the same reference and one file, including 8 concurrent submits; no submit without `confirm`
  (`False`, `None`, `"yes"`, `1`); the creator can't approve; u07 (EU team lead) can't approve an
  NA draft; u02 (NA technician, not a lead) can't approve; outbox failure keeps the draft
  `approved` and a retry with the same key succeeds; a cited passage missing from the current
  dataset, or the creator losing a group in `users.json`, hides the draft on the next read.
- Regression: `pytest tests/unit tests/acl tests/answer tests/workorders -m "not hosted and not
  integration"`: 156 passed. `ruff check` clean on my files.
- I started the whole suite once and stopped it when I saw that `tests/integration` builds a
  scratch corpus and may embed through the hosted provider. `data/usage.jsonl` has no entry after
  21:44, so nothing was spent; the review-queue test item it creates was cleaned up (0 rows left).
- Spend: **US$0**. No model calls; `.env` not read.

### Requests to the orchestrator

REQUEST (to: orchestrator)

1. **`submission_failed` (503)** in http-api.md, section "Errors": the spec's edge case "outbox
   write fails: the draft stays approved, the error is shown" needs a code, and none of the listed
   ones fit. Today it's `copilot_workorders.SubmissionFailed`; if accepted, it could move to
   `copilot_contracts.services`.
2. **Specialist and return visit** (work-orders-audit.md, FR-003: requirement that approval is
   needed for parts, certification, campaign, specialist or return visit): `WorkOrderDraft` and
   `WorkOrderSuggestion` have no field for either, so those two reasons can never appear. Proposed:
   `needs_specialist: bool` and `return_visit: bool` on both, editable by PATCH.
3. **Region unknown** (spec edge case: "can't be submitted until an approver chooses a target
   system"): `target_system` isn't optional and no endpoint sets it, so creation is refused with
   `422 invalid_request` instead. Every asset in ds_0028 is NA or EU, so this doesn't happen today.
   Proposed: keep the refusal and change the spec's edge case to say so.
4. **Removing citations** (spec edge case: "the creator may remove the restricted citations to
   make it approvable"): `citations` isn't in the PATCH list. Proposed: allow `citations` in PATCH
   only as a subset of the current list; certification added by rule would then be recomputed.

Open items: T022 (task: 003 switches from fakes to `build_services`, owned by 003), T023 (task:
specialist and return-visit reasons, needs request 2), T024 (task: removing citations, needs
request 4).

## 2026-10-12 22:15 — Review items applied: shared SubmissionFailed, specialist and return visit, cert-* only

STATUS (to: orchestrator, answer API agent)

Answers `orchestrator.md`, "2026-10-12 22:30 — Review of work orders and the engine's
certification round", REQUEST (to: work orders). Items 1, 2, 3 and 5 are applied with tests.
Item 4 (removing citations) declined: nothing to build, and T024 (task: remove citations) is
dropped. Re-read `orchestrator.md` and `answer-api.md` before finishing.

| Item | Change |
|---|---|
| 1. `submission_failed` (503) | `copilot_workorders` raises `copilot_contracts.services.SubmissionFailed`; the local class is gone. `copilot_workorders.SubmissionFailed` still imports, as the same class. |
| 2. Specialist and return visit | `needs_specialist` and `return_visit` columns (boolean, default false), added by `migrate` with `ADD COLUMN IF NOT EXISTS`, so an existing `app` schema upgrades in place. Editable by `edit` (strict booleans: `"yes"` is `422`); they add the approval reasons `specialist` and `return visit` (the web client's words); before and after are audited; both appear in the outbox record's `copilot` block. Not taken from the suggestion. |
| 3. Region unknown | Behaviour unchanged (creation refused with `InvalidRequest`, 422); now covered by a test. |
| 5. `cert-*` only | `required_certification` keeps only `cert-*` groups: from the suggestion, and from the access alternatives of cited restricted procedures. The u05 (EU refrigeration engineer) draft citing the SOP-020 (chiller leak test and recharge procedure, restricted) passage now lists only cert-refrigerant (refrigerant certification), not family-chillers (Nordkyl chiller training). Dropped groups are recorded in the `draft_created` event (`non_certification_groups_dropped`). Visibility still uses every group through `serving.can_see`. |

`citations` was never editable; a test now checks that `edit` with `citations` is `422` and that
the SOP-020 citation and its certification stay.

For the answer API agent (003): no signature changes. The `edit` docstring in
`copilot_contracts/services.py` still lists only the first five fields; the new two are accepted.
Your `tests/api` (90 offline tests, including `test_work_orders_real.py`) pass against this
version.

Verification:

- `uv run pytest tests/workorders`: **56 passed** (was 47). New: specialist and return visit,
  each as a reason, audited and blocking submit until approved; the flags in the outbox record;
  citations not editable; `cert-*` only; unknown region refused with 422; `migrate` adds the new
  columns to a `drafts` table created before them; `SubmissionFailed` is the contract class with
  code `submission_failed` and status 503.
- Offline regression `tests/unit tests/acl tests/answer tests/workorders`: 165 passed;
  `tests/api`: 90 passed; `ruff check` clean on my files.
- No `wo_test_*` schemas, `app` schema or `data/outbox` left behind by my tests.
- Spend: **US$0**. No model calls (`data/usage.jsonl` unchanged since 21:44); `.env` not read.

Files changed: `src/copilot_workorders/{__init__,service,rules}.py`,
`src/copilot_workorders/db/app_schema.sql`, `tests/workorders/{test_drafts,test_rules,test_migrate}.py`,
`specs/005-work-order-drafts/{plan,tasks}.md` (T023, T025–T027 done; T024 dropped). Nothing
outside my folders.

Open items: none for work orders. T022 (task: 003 uses `build_services`) is with the answer API.
