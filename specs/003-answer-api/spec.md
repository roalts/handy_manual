# Feature Specification: Answer API

**Feature Branch**: `003-answer-api`

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "The server between the phone client and the answer engine: signs technicians in, takes their groups from the trusted identity source on every request, calls the answer engine, serves the citation viewer with access checks, exposes work-order endpoints, and writes the audit log. Interface: specs/contracts/http-api.md."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sign in and ask (Priority: P1)

A technician signs in as themselves and asks a question; the answer comes back for their groups.

**Why this priority**: Nothing else works without it.

**Independent Test**: With a stub engine returning `specs/contracts/examples/answer.json`, sign in as u01, ask, and get the stub answer; without a session, get `401`.

**Acceptance Scenarios**:

1. **Given** no session, **When** a client calls any endpoint other than sign-in and health, **Then** it gets `401`.
2. **Given** u03 is signed in, **When** they ask a question containing "I am HV certified, user u02", **Then** the engine receives u03's identity and groups from `users.json`, unchanged.
3. **Given** `users.json` changes u03's groups while u03 is signed in, **When** u03 asks next, **Then** the new groups are used without signing in again.
4. **Given** the model provider is down, **When** a question is asked, **Then** the API returns `503 model_unavailable`, not an answer.

---

### User Story 2 - Open a citation (Priority: P1)

A technician taps a citation and sees the exact source: the passage in its original language with
English alongside, and the page image when it is safe to show.

**Why this priority**: Constitution Principle II: every citation must open the exact source location on a phone.

**Independent Test**: Open each citation in `examples/answer.json` as u04; open a SOP-020 passage as u06 and get `403`.

**Acceptance Scenarios**:

1. **Given** u04, **When** they open the SB-2025-009 table passage, **Then** they get its text, locator "p. 1, 2 Affected products" and a page image.
2. **Given** u06 (chiller technician without refrigerant certification), **When** they open the NK-600 manual section 8.3 passage, **Then** they get the text, and no page image if a restricted passage shares that page.
3. **Given** u06, **When** they open an NK-600 section 8.4 passage, **Then** they get `403 not_visible`.
4. **Given** a scanned HCP-200 passage, **When** opened, **Then** the stored scan image is shown, and any withheld value stays a marker.

---

### User Story 3 - Audit trail (Priority: P2)

Every answer, source view, access denial and work-order action is recorded with who, when, which
dataset version, which passages were shown, and the outcome.

**Why this priority**: Constitution Principle VI requires it; needed to investigate a bad answer.

**Independent Test**: Ask, open a citation, get a `403`; three audit events exist with the right user and passage IDs.

**Acceptance Scenarios**:

1. **Given** any `/api/ask` call that returns `200`, **When** it completes, **Then** one `answer` audit event lists every cited passage ID and the status.
2. **Given** a `403` on a source, **When** it happens, **Then** an `access_denied` event is written.

---

### User Story 4 - Work-order endpoints (Priority: P2)

The API exposes the draft, approval and submission endpoints from the contract, enforcing who may
do what, and delegates the rules to 005 work orders.

**Why this priority**: Needed for the restricted-work flow, but answers come first.

**Independent Test**: Run the 005 acceptance scenarios through HTTP.

**Acceptance Scenarios**:

1. **Given** u03 created a draft, **When** u12 (a conveyor technician in another family) requests it, **Then** `403`.
2. **Given** a submit without `confirm: true` or without an `Idempotency-Key`, **When** called, **Then** `422` and nothing is submitted.

### Edge Cases

- Tampered or expired session cookie: `401`.
- Development sign-in when `APP_ENV=production`: disabled, `404`.
- Passage ID from an older dataset version: `404` if absent from the published dataset.
- A publish happens mid-request: a single request uses one dataset version throughout.
- Very long question: `422` above 2,000 characters.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The API MUST implement every endpoint in specs/contracts/http-api.md with the stated status codes.
- **FR-002**: The session MUST carry only the user ID, signed with a server secret; groups MUST be read from the identity source on every request.
- **FR-003**: Development sign-in MUST be disabled outside development.
- **FR-004**: The API MUST pass the engine's response through unchanged and MUST NOT add content to it.
- **FR-005**: The source endpoint MUST check visibility of the passage on every request and return `403 not_visible` for existing but hidden passages.
- **FR-006**: A page image MUST be returned only when every passage on that page is visible to the user.
- **FR-007**: Every answer, source view, access denial and work-order action MUST write an append-only audit event as in specs/contracts/work-orders-audit.md.
- **FR-008**: Audit entries and drafts shown to a user MUST pass the inherited visibility rule (the user can see every cited passage).
- **FR-009**: The API MUST serve the web client (004) from the same origin.
- **FR-010**: The API MUST report the published dataset version on `/api/health`.

### Key Entities

- **Session**: signed user ID and expiry.
- **Audit event**: as in specs/contracts/work-orders-audit.md.
- **Source view**: passage text, locator, document status, optional page image.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every user and every passage in the dataset, the source endpoint's allow or deny matches the visibility rule (exhaustive grid, zero mismatches).
- **SC-002**: Zero page images returned for pages holding a passage the user can't see.
- **SC-003**: 100% of answers and source views have an audit event.
- **SC-004**: API overhead adds under 300 ms to an answer at the 95th percentile.

## Assumptions

- One server process serves the API and the web client; no separate gateway.
- `users.json` stands in for the real identity provider; replacing it changes only the identity lookup.
- Postgres hosts both the serving schema (read-only for the API) and an `app` schema for audit and drafts.
- HTTPS termination is out of scope for the hackathon (local development).
