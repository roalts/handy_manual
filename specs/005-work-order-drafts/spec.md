# Feature Specification: Work-Order Drafts

**Feature Branch**: `005-work-order-drafts`

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "Technicians turn an answer's suggestion into a work-order draft, edit it, get approval when parts, certifications, campaigns or return visits are involved, and submit it to MaintPro (North America) or Servio (Europe) only after explicit confirmation, with no duplicates on retry and a full audit trail. Rules: specs/contracts/work-orders-audit.md."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Draft from an answer (Priority: P1)

A technician who can't do the work themselves (for example, not certified) turns the answer's
suggestion into a draft and edits it.

**Why this priority**: It's the offered alternative to restricted steps (constitution Principle V).

**Independent Test**: Create a draft from the suggestion in `specs/contracts/examples/restricted.json` as u03.

**Acceptance Scenarios**:

1. **Given** u03 and the E-31 suggestion for TAC-C-0143, **When** a draft is created, **Then** it has asset TAC-C-0143, fault E-31, cert-hv required, target system MaintPro, status `draft`, and the suggestion's citations.
2. **Given** a draft, **When** u03 edits the summary, **Then** the change is saved and audited with before and after.

---

### User Story 2 - Approval when needed (Priority: P1)

Drafts that commit parts, certified people, a campaign or a return visit wait for a lead's approval.

**Why this priority**: Constitution Principle VI: committing parts, people and visits needs authorization.

**Independent Test**: The E-31 draft requires approval; u08 (NA team lead) approves; u07 (EU team lead) can't.

**Acceptance Scenarios**:

1. **Given** the E-31 draft (cert-hv required), **When** u03 tries to submit, **Then** it is refused with the approval reasons; "request approval" moves it to `pending_approval`.
2. **Given** a pending NA draft, **When** u08 (NA team lead) approves, **Then** it becomes `approved` with u08 and the time recorded.
3. **Given** a pending NA draft, **When** u07 (EU team lead) tries to approve, **Then** it is refused.
4. **Given** u08 created a draft, **When** u08 tries to approve it, **Then** it is refused.

---

### User Story 3 - Submit exactly once (Priority: P1)

After explicit confirmation, the draft is sent to the right system and retries never create a second work order.

**Why this priority**: Duplicate work orders send two technicians to the same machine.

**Independent Test**: Submit an approved draft twice with the same key; one outbox file, the same external reference both times.

**Acceptance Scenarios**:

1. **Given** an approved NA draft, **When** submitted with confirmation and a key, **Then** one MaintPro outbox record is written and the draft is `submitted` with an external reference.
2. **Given** the same submit repeated with the same key, **When** called, **Then** the same reference is returned and nothing new is written.
3. **Given** a draft for RTM-H-0007 (Rotterdam chiller), **When** submitted, **Then** it goes to Servio.

---

### User Story 4 - Drafts respect access (Priority: P2)

A draft is visible only to its creator and the approvers for the region, and only while they can
see every passage it cites.

**Why this priority**: Drafts quote sources; they must not become a way around access rules.

**Independent Test**: A draft by u05 citing a SOP-020 passage is hidden from u11 (not creator, not approver) and from u07 (the EU approver, who lacks refrigerant certification), and is flagged as having no eligible approver.

**Acceptance Scenarios**:

1. **Given** a draft by u05 (EU refrigeration engineer) citing a SOP-020 passage, **When** u11 (NA chiller technician with refrigerant certification, not an approver) requests it, **Then** `403`.
2. **Given** the same draft, **When** u07 (the EU team lead, no refrigerant certification) requests it, **Then** `403`, and the draft shows "no eligible approver" to u05.
3. **Given** a cited passage becomes restricted in a new dataset version, **When** the creator opens the draft, **Then** access is re-evaluated and denied if they can no longer see it.

### Edge Cases

- The asset's region is unknown: the draft is refused at creation (`422`); every asset in the current fleet has a region.
- No approver for the region can see every cited passage (in this corpus: any EU draft citing SOP-020, since u07 lacks refrigerant certification): the draft is flagged "no eligible approver" and can't be submitted from the app; it must be escalated outside the app until the constitution's TODO(WORK_ORDER_APPROVERS) names approvers. Citations can't be removed to get around this.
- A draft with no citations (written by hand): allowed; approval rules still apply.
- The outbox write fails: the draft stays `approved`, the error is shown, and a retry with the same key is safe.
- Rejected drafts: editable and re-submittable for approval; the rejection note is kept.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Drafts MUST follow the lifecycle and fields in specs/contracts/work-orders-audit.md.
- **FR-002**: Prefilled values MUST come only from the answer's suggestion; any user edit MUST be audited.
- **FR-003**: Approval MUST be required when a draft has parts, a required certification, a campaign code, a specialist or a return visit.
- **FR-004**: Only `role-lead` users for the asset's region, other than the creator, MAY approve or reject.
- **FR-005**: Submission MUST require explicit confirmation and an idempotency key; the same key MUST return the same result without a second submission.
- **FR-006**: The target system MUST follow the asset's region: MaintPro for NA, Servio for EU.
- **FR-007**: A draft MUST be visible only to its creator and the region's approvers, and only while they can see every cited passage.
- **FR-008**: Every draft action MUST write an audit event.
- **FR-009**: Submission adapters in this build MUST be fakes that write to a local outbox and never call a real external system.

### Key Entities

- **Work-order draft** and **audit event**: as in specs/contracts/work-orders-audit.md.
- **Outbox record**: what would have been sent to MaintPro or Servio, keyed by idempotency key.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero duplicate outbox records across repeated submissions with the same key.
- **SC-002**: Zero submissions without explicit confirmation.
- **SC-003**: Zero approvals by the creator or by a lead outside the asset's region.
- **SC-004**: A technician can create and send a draft for approval in under 1 minute.

## Assumptions

- `role-lead` per region is a stand-in until the constitution's TODO(WORK_ORDER_APPROVERS) is settled.
- Real MaintPro and Servio integrations are out of scope; the outbox format mirrors their work-order fields as seen in the corpus exports.
- Storage is the `app` schema shared with the audit log (003).
