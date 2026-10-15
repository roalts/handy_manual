# Feature Specification: Mobile Web Client

**Feature Branch**: `004-mobile-web-client`

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "A mobile web page for technicians at customer sites: sign in, ask a question, read a short answer with numbered steps, tap any citation to see the source, see conflicts, warnings and unverified values clearly, pick a machine when asked, and turn a suggestion into a work-order draft. Built against specs/contracts/http-api.md and the example responses."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask and read on a phone (Priority: P1)

A technician signs in, types or pastes a question, and reads an answer that fits a phone screen:
short statements, numbered steps, warnings that stand out, and a small citation marker after each sentence.

**Why this priority**: The core experience.

**Independent Test**: Against a stub API returning each file in specs/contracts/examples/, every status renders correctly on a 375 px wide screen.

**Acceptance Scenarios**:

1. **Given** `answer.json`, **When** shown, **Then** steps are numbered, the warning is visually distinct, each sentence has tappable citation markers, and the machine (FRS-P-0031, HCP-350, serial HCP350-241187) is shown above the answer.
2. **Given** `restricted.json`, **When** shown, **Then** the screen says certification is required (cert-hv, high-voltage certification), names HV-PROC-07, shows no steps, and offers "Draft a work order".
3. **Given** `abstain.json`, **When** shown, **Then** the screen says no permitted source covers it, distinct from an error.
4. **Given** `clarify.json`, **When** shown, **Then** the user taps FRS-P-0031 and the question is resent with that asset.

---

### User Story 2 - Check the source (Priority: P1)

The technician taps a citation and sees the source: document title, revision, location, the
passage (original language and English), and the page image when available.

**Why this priority**: Technicians only trust answers they can check.

**Independent Test**: Tap every citation in the examples; each opens its viewer; a `403` shows "not visible to you".

**Acceptance Scenarios**:

1. **Given** a citation flagged superseded or possibly stale, **When** shown in the answer and viewer, **Then** a clear label says so.
2. **Given** a translated passage, **When** opened, **Then** the original text is shown with the English translation labelled as machine-translated.
3. **Given** `unverified.json`, **When** shown, **Then** the withheld value reads "value unverified, see scanned page 3" and links to the scanned page image; no value is displayed.
4. **Given** a source with no page image, **When** opened, **Then** the passage text is shown without an image and without an error.

---

### User Story 3 - Conflicts and notices (Priority: P2)

When sources disagree, the technician sees both sides with citations and which one applies to
their machine and why.

**Why this priority**: Silent resolution of conflicts is forbidden by the constitution (Principle IV).

**Independent Test**: `answer.json` shows the casing torque conflict (38 N-m bulletin vs 45 N-m manual) with the bulletin marked as applying.

**Acceptance Scenarios**:

1. **Given** a conflict with `preferred` set, **When** shown, **Then** both sides are visible, the preferred one is marked, and the reason is shown.
2. **Given** a conflict with `preferred: null`, **When** shown, **Then** both sides appear with no side marked and a note to check with a lead.

---

### User Story 4 - Draft a work order (Priority: P3)

From a suggestion, the technician opens a prefilled draft, edits it, and either submits it or
sends it for approval.

**Why this priority**: Completes the restricted-work flow; depends on 005.

**Independent Test**: From `restricted.json`, create a draft, edit the summary, request approval.

**Acceptance Scenarios**:

1. **Given** a suggestion, **When** "Draft a work order" is tapped, **Then** a form opens prefilled with asset, fault code, summary, certification, parts and campaign.
2. **Given** a draft that needs approval, **When** shown, **Then** it says who must approve and why, and "Submit" is replaced by "Request approval".
3. **Given** submit, **When** tapped, **Then** a confirmation step names the target system (MaintPro or Servio) before anything is sent.

### Edge Cases

- Slow or dropped connection: a pending state with the question kept; retry resends the same question without losing it.
- `503 model_unavailable`: a clear "the assistant is unavailable, nothing was answered" message.
- Session expired: return to sign-in and keep the typed question.
- Very long passages in the viewer: scrollable, with the cited location at the top.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The client MUST render every status and field in specs/contracts/answer.md.
- **FR-002**: The client MUST render unverified segments only as "value unverified, see scanned page N" with a link, and MUST NOT display a value in their place.
- **FR-003**: The client MUST show both sides of every conflict.
- **FR-004**: The client MUST label superseded, possibly stale, scanned and machine-translated sources.
- **FR-005**: The client MUST show "not visible to you" for `403` responses.
- **FR-006**: The client MUST require an explicit confirmation before submitting a work order.
- **FR-007**: The client MUST be usable one-handed on a 375 px wide screen, with tap targets at least 44 px.
- **FR-008**: The client MUST NOT store answers or sources on the device beyond the current session.
- **FR-009**: The client MUST offer development sign-in as a list of test users (users.json) while the API is in development mode.

### Key Entities

- **Screen states**: sign-in, ask, answer (by status), source viewer, draft form.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A technician can go from sign-in to reading an answer and opening its first citation in under 30 seconds plus answer time.
- **SC-002**: All five example responses render without errors on a 375 px wide phone screen.
- **SC-003**: Zero cases where an unverified value or a hidden passage is displayed.
- **SC-004**: The first screen loads in under 2 seconds on a slow mobile connection.

## Assumptions

- A single-page web app served by the answer API (003); no native app, no offline mode in v1.
- English user interface only; source text may be Dutch or German.
- No front-end build step is required if a plain HTML, CSS and JavaScript page meets the requirements; that choice belongs to the plan.
