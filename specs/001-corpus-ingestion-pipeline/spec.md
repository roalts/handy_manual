# Feature Specification: Corpus Ingestion Pipeline

**Feature Branch**: `001-corpus-ingestion-pipeline`

**Created**: 2026-10-11

**Status**: Draft

**Input**: User description: "build an ingestion pipeline that takes in different sources and build
the correct dataset which can be used while querying to answer any chat questions"

## Context

Corvane field technicians ask the copilot about machines that are down. Every answer must be
traceable to a source the technician is allowed to read, must apply to the specific machine
(model, serial, firmware), and must reflect the current revision of guidance. The ingestion
pipeline turns Corvane's heterogeneous exports into the dataset that makes those guarantees
possible. If ingestion is wrong, no amount of query-time logic can produce a safe answer.

The current corpus (42 files) contains manufacturer manuals and bulletins, controlled procedures,
wiki pages, email threads, a chat channel export, two maintenance-system exports (one per
region, from before and after the Kyltek acquisition), customer-case exports, a fleet register,
and an operations review. Known conditions in the corpus include an empty file, a partially
corrupted bulletin, an image-only scanned manual in German, an exact duplicate manual stored
under a different name, superseded revisions, bilingual documents, Dutch-language records with
regional date and number formats, legacy asset identifiers, cancelled work orders, records that
reference each other across systems, deleted and edited chat messages, and one document with no
access rule.

The primary consumer of this dataset is the copilot's question-answering capability. The
secondary users are the corpus operator (who runs ingestion and resolves flagged items) and
reviewers (who verify uncertain extractions).

## Clarifications

### Session 2026-10-11

- Q: When the two recognition methods disagree on a value from a scanned page, what may a
  technician see before review? → A: The passage stays retrievable, the disputed value is
  withheld and replaced by an "unverified, see scanned page" marker linked to the page image;
  neither candidate reading is shown (FR-024, FR-024a).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Authorized, traceable passages from text-based sources (Priority: P1)

The operator runs ingestion over the corpus. Every text-based document (procedures, manuals and
bulletins with extractable text, wiki pages, emails, chat, customer cases) becomes a set of
passages. Each passage keeps its document's access rule, records exactly where it came from, and
keeps procedures and tables intact. Documents without an access rule, empty files, and unreadable
files are quarantined with a reason instead of being indexed. Passages containing restricted
procedure steps carry the certification requirement of that procedure, even when they appear in
a less-restricted document.

**Why this priority**: Without authorized, traceable passages, the copilot cannot answer anything
safely. This slice alone supports lookups such as alarm-code meanings and documented fixes.

**Independent Test**: Run ingestion on the corpus, then for each of the 12 users list the passages
they are permitted to retrieve and compare against the document access rules; open any passage's
source reference and confirm it lands on the right page, section, record, or message.

**Acceptance Scenarios**:

1. **Given** a document whose access rule requires groups A and B, **When** it is ingested,
   **Then** every passage from it is retrievable only by users in both A and B.
2. **Given** the unofficial VRS-110 quick-reset wiki page has no access rule, **When** ingestion
   runs, **Then** it is quarantined with reason "no access rule" and none of its content is
   retrievable by any user.
3. **Given** the Q3 inspection checklist file is empty, **When** ingestion runs, **Then** it is
   quarantined with reason "empty file" and ingestion of all other documents completes.
4. **Given** the VRS-110 E-31 reset procedure (HV-PROC-07), **When** it is split into passages,
   **Then** its numbered steps are never separated from their safety preconditions, and the
   procedure can be delivered whole.
5. **Given** a table of specifications, **When** it is split into passages, **Then** every passage
   containing table values also contains the table's column headings.
6. **Given** a passage in a broadly visible document that reproduces steps of a
   certification-restricted procedure, **When** ingestion runs, **Then** the passage additionally
   requires that certification, and is never made less restricted than its document.
7. **Given** a chat export with a deleted message and an edited message, **When** ingested,
   **Then** the deleted message's content is absent and the edited message reflects its latest
   version, with replies attached to their threads.

---

### User Story 2 - Unified asset and service history (Priority: P1)

The pipeline builds one record per machine (identifier, model, serial, site, region, firmware,
oil type) from the fleet register, plus a single chronological service history per machine that
merges both regional maintenance systems and customer cases. Legacy identifiers from the acquired
company resolve to current identifiers, regional date and number formats are interpreted
correctly, cancelled work orders are marked as cancelled, and events recorded in two systems
appear once.

**Why this priority**: Questions such as "has this happened before on TAC-C-0142?" and "what
torque for FRS-P-0031?" cannot be answered without knowing which machine is meant and what has
happened to it. Equal priority with Story 1 because roughly half the evaluation questions depend
on it.

**Independent Test**: Query the history for TAC-C-0142 and fault E-14 and confirm the March 2026
and July 2026 events appear once each, linked to customer cases 00041207 and 00042388; look up
legacy identifier MFL-KM07 and confirm it resolves to RTM-H-0007.

**Acceptance Scenarios**:

1. **Given** a European maintenance record dated `03-12-2025`, **When** ingested, **Then** it is
   dated 3 December 2025, not 12 March 2025.
2. **Given** a European record with labour hours `2,5`, **When** ingested, **Then** the value is
   2.5 hours.
3. **Given** a European record referencing legacy asset `MFL-KM07`, **When** ingested, **Then** the
   event belongs to RTM-H-0007.
4. **Given** a work order with status "cancelled" in the source system, **When** ingested, **Then**
   it appears in history marked cancelled and is distinguishable from completed fixes.
5. **Given** a North American work order whose notes reference a customer case, **When** both are
   ingested, **Then** they are linked as one service event with both source references.
6. **Given** a history record or customer case, **When** ingested, **Then** it inherits its source
   export's access rule.

---

### User Story 3 - Applicability, revision, and authority metadata (Priority: P2)

Every document and passage carries the metadata needed to decide whether it applies and how much
it should be trusted: document type, authority tier (controlled procedure, manufacturer bulletin,
manual, wiki, email/chat), equipment models covered, revision and issue date, what it supersedes,
and conditions of applicability such as serial ranges and firmware versions. Bulletins are linked
to the specific machines in the fleet they affect. Duplicate copies of the same document are
recognized as one document.

**Why this priority**: Without this, the copilot can retrieve a correct-looking but wrong value:
a torque from a manual that a bulletin overrides for newer serials, or an oil interval from a
superseded revision. Depends on Stories 1 and 2.

**Independent Test**: Inspect the dataset for the acceptance facts below without running the
copilot.

**Acceptance Scenarios**:

1. **Given** Halden bulletin SB-2025-009, **When** ingested, **Then** it applies to HCP-350 units
   from serial HCP350-240001 onward, and FRS-P-0031 (serial HCP350-241187) is listed as affected.
2. **Given** Nordkyl bulletin SB-2025-014, **When** ingested, **Then** RTM-H-0007 is listed as an
   affected machine and the campaign code NK-C25-14 is recorded.
3. **Given** Vastra bulletin SB-2026-003, **When** ingested, **Then** its applicability records the
   firmware condition (below 5.1) and VRS-110 units on firmware 5.0 are listed as affected.
4. **Given** VRS-75 service manual Rev B (2024) and Rev C (2026), **When** both are ingested,
   **Then** Rev C is current and Rev B is marked superseded by Rev C.
5. **Given** `NK600_manual_final_v2.pdf` and the Nordkyl NK-600 Rev C manual have identical
   content, **When** ingested, **Then** they are one canonical document with both origins
   recorded, and a user permitted to see either copy can retrieve it.
6. **Given** a metadata value proposed by automated extraction, **When** it has no supporting
   quotation found verbatim in the source, **Then** the value is not stored and the item is sent
   to review.
7. **Given** a wiki page states a specification for a model that has a newer controlled manual,
   **When** ingested, **Then** the wiki passage is marked as possibly stale.

---

### User Story 4 - Difficult sources: scans, damaged files, other languages (Priority: P2)

Scanned documents are converted to text using two independent recognition methods whose
numerical values, units, and part numbers are compared; values that agree are marked verified,
and disagreements go to review. Partially damaged files are recovered where possible and marked
partial with the missing pages listed. Non-English content remains searchable from English
questions, with the original text always preserved for citation.

**Why this priority**: The 1998 HCP-200 manual exists only as a German scan, and a single
recognition pass already misreads its key clearance value. A wrong value from a real source is
the most dangerous kind of error because it looks verifiable.

**Independent Test**: Ingest the HCP-200 scan and the damaged VRS-45 bulletin; inspect the
resulting passages and flags.

**Acceptance Scenarios**:

1. **Given** the HCP-200 scan, **When** ingested, **Then** the impeller-to-casing clearance passage
   reads 0.38-0.50 mm, verified either by agreement of both recognition methods or by reviewer
   confirmation; until then the value is shown only as an "unverified" marker.
2. **Given** a value on a scanned page where the two methods disagree, **When** ingested, **Then**
   the passage is retrievable with that value replaced by an "unverified, see scanned page"
   marker linked to the page image, neither candidate reading is retrievable, and the value
   appears in the review queue.
3. **Given** a reviewer confirms a disputed value, **When** ingestion next runs, **Then** the
   confirmed value replaces the marker and is marked reviewer-verified.
4. **Given** recognized text reading "HGP-200" on a page of the HCP-200 manual, **When** ingested,
   **Then** the model is recorded as HCP-200, corrected against known fleet models, with the
   correction logged.
5. **Given** the damaged VRS-45 coupling bulletin, **When** ingested, **Then** recoverable pages are
   indexed, the document is marked partial, and the missing pages are listed.
6. **Given** a Dutch maintenance note or a bilingual German/English bulletin, **When** ingested,
   **Then** the original text is stored, an English rendering is stored alongside it, and each
   language block is separately searchable.

---

### User Story 5 - Running corpus: incremental updates and safe publishing (Priority: P2)

The corpus changes over time. The operator can add, change, or delete source files, or change an
access rule, and re-run ingestion. Only affected documents are reprocessed. A new dataset version
becomes visible to the copilot only after it passes validation; a failed run leaves the previous
version in service.

**Why this priority**: The corpus is a running list. Without incremental, validated publishing,
every change risks either stale guidance or a broken dataset in front of technicians.

**Independent Test**: Ingest the corpus; then modify one document, delete one, change one access
rule, and re-run; confirm only those documents changed and that a deliberately failing run does
not replace the published version.

**Acceptance Scenarios**:

1. **Given** an unchanged corpus, **When** ingestion runs twice, **Then** the resulting datasets are
   identical.
2. **Given** one changed document, **When** ingestion re-runs, **Then** only that document's passages
   are regenerated.
3. **Given** a deleted source file, **When** ingestion re-runs and publishes, **Then** none of its
   passages or history records are retrievable.
4. **Given** an access rule tightened for a document, **When** ingestion re-runs and publishes,
   **Then** users who lost access can no longer retrieve its passages.
5. **Given** a run whose validation checks fail, **When** it completes, **Then** the previously
   published dataset remains in service and the failure is reported.

---

### User Story 6 - Ingestion report and review queue (Priority: P3)

After each run, the operator receives a report: every source file and its outcome (indexed,
partial, quarantined with reason), counts of passages and history records, scanned pages
verified, metadata gaps, review items, access-rule coverage, and the result of every validation
check. Reviewers can see each flagged item with its source location and resolve it.

**Why this priority**: The pipeline must never fail silently. Lower priority only because the
underlying flags are produced by Stories 1-5; this story makes them visible and actionable.

**Independent Test**: Run ingestion and confirm every one of the 42 source files appears in the
report with an outcome, and every flagged item can be traced to its source location.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the operator opens the report, **Then** every source file is
   listed with exactly one outcome and, if not indexed normally, a reason.
2. **Given** an item in the review queue, **When** a reviewer opens it, **Then** they see the source
   location, the extracted value(s), and why it was flagged.
3. **Given** a reviewer resolves an item, **When** ingestion next runs, **Then** the resolution is
   applied and the item no longer appears as open.

### Edge Cases

- A source file is empty, unreadable, or in an unsupported format: quarantined with reason; the
  run continues.
- A document has no access rule, or an access rule references an unknown group: quarantined.
- A document appears in the access rules but the file is missing: reported; no passages exist.
- Two documents have identical content but different access rules: one canonical document,
  retrievable by a user permitted to see either copy.
- Two documents for the same model disagree (revision change, or Corvane procedure vs. Kyltek
  work instruction): both retained with authority tier and dates; the conflict is not resolved
  by ingestion.
- A bulletin's applicability range cannot be extracted with a verified quotation: the bulletin is
  indexed, the applicability is left empty, and the item goes to review. It is never assumed to
  apply to all units.
- A maintenance record has a blank legacy identifier: only the current identifier is used.
- A maintenance record references an asset not in the fleet register: retained, flagged.
- A record references a customer case that does not exist in the exports: retained, link
  flagged as unresolved.
- A procedure is too long to deliver as a single unit: it is still deliverable whole, with smaller
  units used only for finding it.
- Embedded document properties (titles, dates) are wrong or garbage: content-derived values take
  precedence and the discrepancy is not used as metadata.
- Restricted-content detection is uncertain: the passage is treated as restricted until reviewed.

## Requirements *(mandatory)*

### Functional Requirements

**Registration and access**

- **FR-001**: System MUST register every source file with a content fingerprint, source system,
  and path, and detect added, changed, and removed files between runs.
- **FR-002**: System MUST attach each document's access rule (a set of required groups; a user may
  access a document only if they belong to every required group; an empty set means all
  technicians).
- **FR-003**: System MUST quarantine, with a stated reason, any document that has no access rule,
  references an unknown group, is empty, or cannot be read. Quarantined content MUST NOT be
  retrievable.
- **FR-004**: System MUST attach to every passage and every history record an effective access
  rule that is at least as restrictive as its source document's rule.
- **FR-005**: System MUST detect passages that reproduce steps of a certification-restricted
  procedure and add that procedure's required groups to the passage's effective access rule.
  Detection MUST only add restrictions. Uncertain detections MUST be treated as restricted until
  reviewed.

**Extraction**

- **FR-006**: System MUST extract content from all source formats present in the corpus: documents
  with extractable text, scanned documents, word-processing documents, wiki page exports, email
  messages (including email printed to document form), chat exports, customer-case exports, and
  tabular exports.
- **FR-007**: System MUST extract content as typed structural blocks (heading, paragraph, list
  item, procedure step, table with header, record, message), each with a precise source location
  (page, section path, table, record identifier, or message identifier).
- **FR-008**: System MUST verify that every page or section produced content or is explicitly
  accounted for (recognized from image, blank, figure only, or unrecoverable).
- **FR-009**: System MUST attempt recovery of damaged files, index recoverable content, mark the
  document partial, and list unrecoverable pages.
- **FR-010**: System MUST split email threads into individual messages, removing quoted repeats and
  signatures, and record sender, recipients, and date.
- **FR-011**: System MUST reconstruct chat threads, exclude deleted messages, and use the latest
  version of edited messages.
- **FR-012**: System MUST preserve warning and caution blocks from wiki pages and procedures as
  distinct, typed content.

**Normalization**

- **FR-013**: System MUST interpret dates and numbers using each source's known conventions
  (including day-month-year dates and decimal commas) and MUST NOT infer a format from the value
  alone.
- **FR-014**: System MUST normalize identifiers (asset IDs, serial numbers, case numbers, part
  numbers, fault codes) to a canonical form while retaining the original text.
- **FR-015**: System MUST resolve legacy asset identifiers from the acquired company's system to
  current identifiers.
- **FR-016**: System MUST map work-order and case statuses from all source systems to one status
  vocabulary that distinguishes completed, open, and cancelled.
- **FR-017**: System MUST detect the language of each block and, for non-English blocks, store an
  English rendering linked to the original. Bilingual documents MUST be separated into
  per-language blocks.

**Enrichment and linking**

- **FR-018**: System MUST record for each document: document type, authority tier, controlled
  status, equipment models covered, revision, issue date, and applicability conditions (serial
  range, firmware condition) where stated.
- **FR-019**: System MUST record for each passage: fault codes, part numbers, asset identifiers,
  serial numbers, and case numbers it mentions, validated against known values where a reference
  list exists.
- **FR-020**: Any metadata value produced by automated interpretation MUST be stored only with a
  supporting quotation verified to appear in the source; otherwise the field stays empty and an
  item is added to the review queue.
- **FR-021**: System MUST identify documents with identical content as one canonical document,
  record all origins, and grant access to a user permitted to see any origin.
- **FR-022**: System MUST record supersession between revisions of the same document for the same
  model, and mark wiki or informal content as possibly stale when a newer controlled source covers
  the same model and topic.
- **FR-023**: System MUST determine, for each bulletin with applicability conditions, which
  machines in the fleet register it affects, and recompute this when the bulletin or fleet
  register changes.
- **FR-024**: For content recognized from images, System MUST compare numerical values, units, and
  part numbers between two independent recognition methods. Agreeing values MUST be marked
  verified. Disagreeing values MUST be withheld: the passage remains retrievable, but each
  disputed value is replaced by a marker stating the value is unverified, linked to the exact
  scanned page image so the reader can read it from the original. Neither candidate reading may
  appear in retrievable text until a reviewer confirms the value.
- **FR-024a**: System MUST retain the page image of every scanned page and link every passage
  recognized from it to that image.
- **FR-025**: System MUST correct recognized equipment model names against known fleet models and
  log each correction.

**Passages and structured data**

- **FR-026**: System MUST split documents into passages along structural boundaries, keeping a
  section's heading path with each passage.
- **FR-027**: System MUST NOT separate numbered procedure steps across passages in a way that
  prevents delivering the whole procedure; long procedures MUST be deliverable whole, with smaller
  units used only to locate them.
- **FR-028**: System MUST keep table column headings with every passage containing table values.
- **FR-029**: System MUST create one passage per customer case (including its comments and emails),
  per maintenance record, per chat thread, and per email message.
- **FR-030**: System MUST maintain a machine registry and a single chronological service history per
  machine, merging both regional maintenance systems and customer cases, with each event linked to
  its source records and duplicated events across systems recorded once.
- **FR-031**: System MUST make every passage findable both by exact identifiers (codes, part numbers,
  serials) and by meaning, in English and in its original language.

**Lifecycle and publishing**

- **FR-032**: System MUST reprocess only documents whose content, access rule, or dependencies have
  changed, and MUST produce identical output for identical input.
- **FR-033**: System MUST remove all passages and history records of deleted documents from the next
  published dataset.
- **FR-034**: System MUST build each new dataset version separately and publish it only after all
  validation checks pass; a failed run MUST leave the previous version in service.
- **FR-035**: System MUST record, for every passage, the source document, origin location, content
  fingerprint, processing version, and ingestion time.

**Validation, reporting, and review**

- **FR-036**: System MUST run validation checks before publishing, including at minimum: every
  retrievable item has an effective access rule; no quarantined content is retrievable; every
  passage has a source location; and the acceptance facts in Stories 1-4 hold.
- **FR-037**: System MUST produce a report per run listing every source file with exactly one
  outcome (indexed, partial, quarantined) and reason, plus counts, verification results,
  metadata gaps, open review items, and validation results.
- **FR-038**: System MUST maintain a review queue of flagged items with source location, extracted
  values, and reason, and MUST apply reviewer resolutions on the next run.

### Key Entities

- **Source Document**: one registered file or export; origin system, path, fingerprint, access rule,
  document type, authority tier, models, revision, issue date, applicability, status (active,
  superseded, partial, quarantined), canonical document if duplicate.
- **Content Block**: a typed structural unit extracted from a document, with source location and
  language.
- **Passage**: the unit retrieved and cited; text in original language and English, heading path,
  identifiers mentioned, effective access rule, verification status, parent passage when part of a
  longer procedure.
- **Access Rule**: the set of groups required to see a document or passage.
- **Machine**: a fleet asset with identifier, legacy aliases, model, serial, site, region, firmware,
  oil type.
- **Service Event**: one dated event in a machine's history; type, fault code, status, notes
  (original and English), parts, links to source records and customer cases, effective access rule.
- **Document Relation**: duplicate-of, supersedes, possibly-stale-versus, bulletin-affects-machine.
- **Quarantine Record**: a source excluded from the dataset, with stage and reason.
- **Review Item**: a flagged extraction awaiting human resolution, with source location and values.
- **Dataset Version**: a validated, published snapshot with its ingestion report.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of retrievable passages and history records have an effective access rule, and
  for all 12 users x 42 documents, retrievability matches the access rules exactly (0 exceptions).
- **SC-002**: 100% of source files appear in the run report with exactly one outcome; 0 files are
  silently skipped.
- **SC-003**: For each of the 10 evaluation questions, every fact required by the expert reference
  answer is present in the dataset, retrievable by the asking user, and contained in a single
  passage or record together with the machine or condition it applies to.
- **SC-004**: 0 values recognized from scanned images appear in retrievable text unless both
  recognition methods agree or a reviewer has confirmed them; 100% of disputed values are shown
  as an "unverified" marker linked to the page image.
- **SC-005**: Re-running ingestion on an unchanged corpus changes 0 passages; changing one document
  changes only that document's passages and its dependent relations.
- **SC-006**: A full ingestion of the current corpus completes and publishes within 30 minutes; a
  single-document update is published within 5 minutes.
- **SC-007**: After a deletion or access-rule tightening is published, 0 affected passages are
  retrievable by users who no longer have access.
- **SC-008**: An operator can identify why any source file was quarantined or flagged from the
  report alone, without inspecting the source, in under 2 minutes per item.

## Assumptions

- The corpus arrives as exported files in the formats currently present; live connections to
  source systems are out of scope for this feature, but new files in the same formats must be
  supported.
- The access rules file and user group definitions are the authoritative source of permissions for
  this feature; user identity and group lookup at query time are handled by the copilot.
- The fleet register is the authoritative list of machines and known models.
- Retaining superseded revisions (marked superseded) is required so the copilot can show conflicts;
  ingestion does not decide which conflicting source is correct.
- Restricted procedures are identified by the controlled procedures in the corpus (HV, refrigerant,
  confined space); their certification groups come from those procedures' access rules.
- Hosted automated interpretation services (for text recognition, translation, and metadata
  extraction) may be used; their outputs are always verified as required above.
- A single operator runs ingestion and resolves review items during the hackathon.
- The query-time behavior (retrieval, ranking, answer generation, abstention) is a separate feature.
