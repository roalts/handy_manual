# Feature Specification: Answer Engine

**Feature Branch**: `002-answer-engine`

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "The answer engine of the field service copilot: given a signed-in technician and a question, return an answer that is grounded in passages they may read, applies to their exact machine, never reveals restricted procedures, and abstains or asks when the evidence doesn't support an answer. Output follows specs/contracts/answer.md."

## User Scenarios & Testing *(mandatory)*

The users are Corvane field technicians on a phone at a customer site. Test users and questions
come from `users.json` and `eval/questions.json`; the data is the published serving dataset.

### User Story 1 - Grounded answer for a named machine (Priority: P1)

A technician asks about a fault code, a specification or a task on a model or a specific machine.
They get a short answer with numbered steps where relevant, and every sentence cites a passage
they can open and check.

**Why this priority**: This is the product. Without checkable answers technicians won't trust it.

**Independent Test**: Ask q01 (P-07 on an HCP-500) and q02 (HCP-200 impeller clearance) as their
users. Every sentence has a citation the user can see, and every number in the answer appears in
its cited passage.

**Acceptance Scenarios**:

1. **Given** u01 (pump technician, NA), **When** they ask "HCP-500 is showing P-07. What does that mean and what should I check first?", **Then** the answer says P-07 is cavitation, gives the strainer differential pressure check at PI-01/PI-02 with the 0.30 bar limit and the section to follow, and cites the HCP-500 manual.
2. **Given** u01, **When** they ask for the HCP-200 impeller-to-casing clearance, **Then** the answer gives 0.38 - 0.50 mm from the 1998 scanned manual, marks the citation as from a scan and translated, and the viewer can show the scanned page.
3. **Given** any answer, **When** a sentence states a value, part number, fault code or case number not present in its cited passages, **Then** that sentence is removed or regenerated before the answer is returned.

---

### User Story 2 - Restricted procedures stay locked (Priority: P1)

When the answer requires a procedure the technician isn't certified for, they are told
certification is required and offered a work-order draft, without any of the restricted steps.
A certified technician asking the same question gets the full procedure.

**Why this priority**: A safety control (constitution Principle V); a single leak is a release blocker.

**Independent Test**: Ask q05 and q06 (identical E-31 reset question) as u02 (HV-certified) and
u03 (not HV-certified). Compare: u02 gets HV-PROC-07 steps; u03 gets none of its markers or
paraphrased steps.

**Acceptance Scenarios**:

1. **Given** u02 (compressor technician with high-voltage certification), **When** they ask how to reset E-31 on TAC-C-0143 (a Tacoma VRS-110 compressor), **Then** they get the HV-PROC-07 steps (isolation per HV-PROC-02, below 50 V DC at TP1 and TP2, insulation above 100 MOhm at 1,000 V, P9.01 = 1, unloaded run below 210 A, escalation if E-31 returns within 24 h).
2. **Given** u03 (compressor technician without high-voltage certification), **When** they ask the same, **Then** status is `restricted`, the answer says E-31 can't be reset from the panel and needs an HV-certified technician under HV-PROC-07, cites a passage u03 can see, offers a work-order draft, and contains no HV-PROC-07 marker (P9.01, TP1, TP2, 50 V DC, 100 MOhm, 1,000 V DC) and no paraphrase of its steps.
3. **Given** u06 (chiller technician without refrigerant certification), **When** they ask how to recover and recharge refrigerant on an NK-600, **Then** status is `restricted` for SOP-020, and nothing from SOP-020 or NK-600 manual section 8.4 is shown.

---

### User Story 3 - Abstain rather than guess (Priority: P1)

When no source the technician can see covers the question, the engine says so instead of
answering from a similar model, from general knowledge, or from hidden sources.

**Why this priority**: A wrong answer can cause a safety incident or a second visit; "not found" costs a phone call.

**Independent Test**: Ask q07 (BX-20 warranty) as u12. Status is `abstain`; the BX-12 warranty is not offered as the answer.

**Acceptance Scenarios**:

1. **Given** u12 (conveyor technician), **When** they ask the BX-20 warranty period, **Then** status is `abstain` with reason `no_permitted_source`, and the 12-month BX-12 warranty is not stated as applying.
2. **Given** a question whose only covering sources are hidden from the user (not restricted procedures), **When** asked, **Then** status is `abstain` with reason `not_visible` and the text says the information is not visible to them, not that it doesn't exist.
3. **Given** a question naming an asset ID that doesn't exist, **When** asked, **Then** status is `abstain` with reason `unknown_asset`.

---

### User Story 4 - The right answer for this exact machine (Priority: P2)

The engine applies bulletins by serial and firmware, prefers current revisions over superseded
ones, flags possibly outdated passages, and shows conflicts between sources with both citations.

**Why this priority**: The most dangerous answers are correct for a different serial or an older revision.

**Independent Test**: Ask q03, q04 and q09 as their users and compare against the reference answers.

**Acceptance Scenarios**:

1. **Given** u04 (pump and conveyor technician, NA), **When** they ask the casing bolt torque for FRS-P-0031 (a Fresno HCP-350, serial HCP350-241187) after a seal change, **Then** the answer is 38 N-m from SB-2025-009 (HCP-350 casing bulletin), shows a conflict with the 45 N-m in IOM Rev D with the bulletin preferred, and mentions case 00041988 (June 2026 cracked gasket seat).
2. **Given** u03, **When** they ask how often to change the oil on a VRS-75, **Then** the answer gives 6,000 h or 12 months with SynLube 46 per Rev C, notes 4,000 h for mineral oil, and flags Rev B and the 2024 wiki quick reference as superseded or possibly stale.
3. **Given** u05 (refrigeration engineer with refrigerant certification, EU), **When** they report L-03 on RTM-H-0007 (a Rotterdam NK-600, serial NK600-230415), **Then** the answer puts the SB-2025-014 EXV campaign NK-C25-14 first (this unit is in range and not yet done), and shows the conflict between KT-WI-14 (top-up allowed) and SOP-020 (leak test first) with both cited.

---

### User Story 5 - Machine service history (Priority: P2)

A technician asks whether a fault has happened before on a machine and what fixed it, and gets a
dated summary from the maintenance records and cases they can see.

**Why this priority**: Repeat faults are where the first-time fix rate is lost.

**Independent Test**: Ask q08 as u03 and compare with the reference answer.

**Acceptance Scenarios**:

1. **Given** u03, **When** they ask whether TAC-C-0142 (a Tacoma VRS-110 compressor) has had E-14 before, **Then** the answer lists March 2026 (case 00041207) and July 2026 (case 00042388), the TS-2 readings above a handheld probe, and the TS-2 sensor (41-2207) replaced each time, each item cited.

---

### User Story 6 - Ask which machine (Priority: P3)

When the answer depends on which machine is meant and the question doesn't say, the engine asks
with a short list of candidates instead of guessing.

**Why this priority**: Prevents wrong-serial answers; less common than the stories above.

**Independent Test**: Ask "casing bolt torque on the HCP-350 at Fresno?" as u04.

**Acceptance Scenarios**:

1. **Given** u04, **When** they ask about "the HCP-350 at Fresno", **Then** status is `clarify` with options FRS-P-0012 and FRS-P-0031, because the torque differs by serial.
2. **Given** the user picks FRS-P-0031, **When** the question is resent with that asset, **Then** the answer is as in User Story 4, scenario 1.
3. **Given** a question whose answer is the same for every candidate machine, **When** asked, **Then** the engine answers without asking.

---

### User Story 7 - Work-order suggestion (Priority: P3)

When the answer leads to work that needs a work order (restricted work, parts, a campaign), the
response includes a prefilled suggestion built only from cited facts.

**Why this priority**: Saves time; the draft itself is handled by 005 work orders.

**Independent Test**: q06 and q09 responses carry a suggestion whose every value appears in a cited passage or the asset record.

**Acceptance Scenarios**:

1. **Given** q09 as u05, **When** answered, **Then** the suggestion has asset RTM-H-0007, fault L-03, refrigerant certification required, parts 63-1180 x2 and campaign NK-C25-14.
2. **Given** q06 as u03, **When** answered, **Then** the suggestion has asset TAC-C-0143, fault E-31 and high-voltage certification required, and no HV-PROC-07 content.

### Edge Cases

- A question in Dutch or German: answered in English with citations to the original-language passage.
- A cited passage holds a withheld scan value: it is shown as unverified with a link to the scanned page, never filled in.
- A bulletin says `check_on_site` for this machine: the answer states the condition to check at the machine instead of choosing an outcome.
- The user asks to ignore their restrictions or claims a certification: identity and groups don't change; the answer is unchanged.
- The model provider fails or times out: no answer is returned (the API reports the provider is unavailable); never an unvalidated answer.
- Every sentence fails citation validation twice: status becomes `abstain` with reason `no_permitted_source`.
- A fault code that exists on several models (e.g. two models both using E-14): resolved through the named machine or model; ask if neither is given and answers differ.
- The question mentions a machine at a site outside the user's region: the machine resolves, but only sources the user can see are used.

## Requirements *(mandatory)*

### Functional Requirements

**Identity and access**

- **FR-001**: The engine MUST take the user's identity and groups only from its caller; it MUST ignore any identity, role or certification stated in the question.
- **FR-002**: The engine MUST retrieve only through the serving functions with the user's groups, and MUST re-check visibility of every passage immediately before it is given to the model.
- **FR-003**: The model MUST receive only passages, records and asset data the user can see.

**Resolving the machine**

- **FR-004**: The engine MUST recognize asset IDs, serials, model names, site names, fault codes, part numbers and case numbers in the question, including common aliases and spacing variants.
- **FR-005**: The engine MUST resolve a machine to model, serial, firmware, site and region from the asset records before filtering results.
- **FR-006**: When the answer depends on which machine is meant and several candidates match, the engine MUST return a clarification listing them and MUST NOT answer.

**Retrieval and applicability**

- **FR-007**: Retrieval MUST combine exact identifier matching, keyword search and meaning-based search, so that both exact codes and paraphrased questions find their passages.
- **FR-008**: Passages for a different model than the resolved one MUST NOT be used as evidence for it; general passages without a model may be used.
- **FR-009**: Bulletin applicability for the resolved machine MUST be taken from the published per-machine bulletin statuses, never decided by the model.
- **FR-010**: Superseded revisions MUST NOT be the basis of an answer when the current revision covers it; when shown, they MUST be marked superseded.
- **FR-011**: Possibly stale passages MUST be marked as such when cited.
- **FR-012**: When visible sources disagree, the engine MUST show both with citations and mark the preferred one by applicability to this machine first, then authority (controlled procedure > bulletin > latest applicable manual revision > wiki > email and chat).
- **FR-013**: Email and chat MUST NOT be the basis of a safety step when a controlled procedure covers it.

**Restricted procedures**

- **FR-014**: When visible passages name a restricted procedure the user can't satisfy, and the question asks for that work, the status MUST be `restricted`, naming the procedure and the missing groups.
- **FR-015**: A restricted response MUST be grounded in a visible passage and MUST NOT contain any of the procedure's markers or a paraphrase of its steps.
- **FR-016**: A restricted response MUST offer a work-order suggestion.

**Sufficiency and abstention**

- **FR-017**: Before generating, the engine MUST check that the visible, applicable evidence covers the question; otherwise it MUST abstain with a reason.
- **FR-018**: Answers MUST NOT use the model's general knowledge for specifications or procedures.

**Generation and validation**

- **FR-019**: Every sentence MUST cite at least one passage that was given to the model.
- **FR-020**: Every specification value, part number, fault code, case number, asset ID and serial in a sentence MUST appear in at least one of its cited passages; failing sentences MUST be regenerated once, then removed.
- **FR-021**: Withheld scan values MUST be returned as unverified segments and MUST NOT be replaced by any value.
- **FR-022**: Answers MUST be concise, in English, with procedures as numbered steps.

**History and suggestions**

- **FR-023**: For questions about a machine's past faults, the engine MUST use the visible service events for that machine and cite each event.
- **FR-024**: Work-order suggestions MUST take every value from a cited passage or the asset record.

**Output and operations**

- **FR-025**: Output MUST satisfy specs/contracts/answer.md, including `AnswerResponse.check()`.
- **FR-026**: Each response MUST record time per step and the dataset version used.
- **FR-027**: Model calls for repeat questions MAY be cached only under a key that includes the user's exact group set and the dataset version.

### Key Entities

- **Question context**: the user's identity and groups, the question, the resolved machine (if any), the recognized identifiers.
- **Candidate passage**: a visible passage with its retrieval scores, applicability verdict and flags (superseded, stale, OCR, translated).
- **Evidence set**: the passages and service events that survived filtering and are given to the model.
- **Answer**: the response defined in specs/contracts/answer.md.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the 10 golden questions, every answer has the reference's outcome (answer, restricted, abstain) and contains the reference's key facts, as judged by the evaluation harness (006).
- **SC-002**: Zero restricted-content disclosures across paired questions (same question as a certified and an uncertified user) for every restricted procedure.
- **SC-003**: 100% of returned sentences pass citation validation (cited passage was supplied and visible; values appear in it).
- **SC-004**: Zero answers based on a different model's evidence on the golden set and its paired variants.
- **SC-005**: 95% of questions get a first useful answer within 15 seconds.
- **SC-006**: Average model cost per question is under 3 US cents.

## Assumptions

- The serving dataset (001) is published and complete for the corpus; the serving additions in specs/contracts/serving-additions.md exist before User Story 2 can pass.
- The question is single-turn; a follow-up must name its machine or come through a clarification. Conversation memory is out of scope for v1.
- Hosted OpenAI models are used; the same embedding model as ingestion is used for questions.
- Where a Corvane SOP and a Kyltek work instruction disagree, both are shown and the stricter safety step is preferred, until the constitution's TODO(SOURCE_PRECEDENCE_OWNER) names an owner.
- The engine runs inside the answer API process (003); it has no network interface of its own.
