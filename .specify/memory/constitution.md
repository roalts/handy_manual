<!--
Sync Impact Report
- Version change: unversioned template → 1.0.0 (initial ratification)
- Modified principles: all template placeholders replaced
  - [PRINCIPLE_1_NAME] → I. Authorization Is Enforced Outside the Model (NON-NEGOTIABLE)
  - [PRINCIPLE_2_NAME] → II. Every Claim Is Grounded and Verifiable (NON-NEGOTIABLE)
  - [PRINCIPLE_3_NAME] → III. Abstain Rather Than Guess
  - [PRINCIPLE_4_NAME] → IV. Applicability and Source Authority Are Decided by Code
  - [PRINCIPLE_5_NAME] → V. Restricted Procedures Are Safety Controls (NON-NEGOTIABLE)
- Added principles: VI. The Assistant Drafts, Humans Commit; VII. Measured Before Shipped;
  VIII. Simplest Architecture That Passes the Evaluation
- Added sections: Corpus and Ingestion Constraints; Development Workflow and Quality Gates
- Removed sections: none
- Templates: plan/spec/tasks templates read this file at runtime; not modified by this command
- Deferred TODOs:
  - TODO(SOURCE_PRECEDENCE_OWNER): name the business owner who approves the source precedence
    order in Principle IV (Corvane SOPs vs Kyltek work instructions in particular).
  - TODO(WORK_ORDER_APPROVERS): confirm which roles approve work-order drafts in Principle VI.
-->

# Corvane Field Service Copilot Constitution

## Core Principles

### I. Authorization Is Enforced Outside the Model (NON-NEGOTIABLE)

- A user MAY see a document only if they belong to every group in its `required_groups`.
  An empty list means every technician may see it.
- The language model MUST only receive text the requesting user is authorized to read.
  Authorization MUST NOT depend on prompt instructions or model behavior.
- Access control MUST fail closed: a document or passage with no ACL record MUST NOT be
  indexed or retrieved, and MUST be reported by ingestion.
- Permission filtering MUST be applied inside the retrieval query, not after ranking.
  A final check against the authoritative ACL source MUST run before prompt assembly.
- User identity and groups MUST come from the trusted identity source on every request,
  never from conversation content.
- Every derived artifact (cached answers, conversation history, work-order drafts, logs
  shown to users) MUST inherit the ACLs of the documents it quotes. Caches MUST be keyed
  by the user's effective permission set; cross-user semantic caching is prohibited.
- When access-limited data is absent, responses MUST say "not visible to you" rather than
  implying the data does not exist.

Rationale: technicians act on answers in front of live equipment; a model cannot be trusted
to keep secrets it has been shown.

### II. Every Claim Is Grounded and Verifiable (NON-NEGOTIABLE)

- Every factual statement in an answer MUST cite a specific passage the user is permitted
  to read, and each citation MUST open the exact source location on a phone.
- Citations MUST be validated by deterministic code before the answer is returned: the cited
  passage MUST be one supplied to the model, and specification values (torques, clearances,
  pressures, intervals), part numbers, fault codes, and case numbers in the sentence MUST
  appear in that passage. Sentences that fail validation MUST be removed or regenerated.
- Refusals and "you are not certified" responses MUST also be grounded in passages the user
  is permitted to read.
- Answers MUST NOT rely on the model's general knowledge for equipment specifications or
  procedures.

Rationale: technicians only trust an answer they can check against its source.

### III. Abstain Rather Than Guess

- The system MUST assess evidence sufficiency before generating an answer. When evidence is
  missing, it MUST say so, ask a clarifying question, or recommend escalation.
- The system MUST NOT substitute evidence about a similar model, serial range, or site for
  the one asked about (for example, BX-12 data for a BX-20 question).
- When the target asset is ambiguous and the answer depends on it, the system MUST ask
  which asset before answering.
- Abstention, clarification, and escalation are correct outcomes and MUST be measured as such.

Rationale: a wrong answer can cause a safety incident, a damaged machine, or a second visit;
"not found" costs a phone call.

### IV. Applicability and Source Authority Are Decided by Code

- Asset identifiers MUST be resolved to model, serial, firmware, and site from structured
  records before retrieval results are filtered.
- Applicability (serial ranges, model, firmware, superseded revisions) MUST be decided by
  deterministic logic over passage metadata, not by the model.
- When sources disagree, precedence MUST follow: controlled procedure > manufacturer
  bulletin > latest applicable manual revision > wiki > email and chat. Uncontrolled sources
  MUST NOT be the basis for a safety step when a controlled procedure covers it.
- Conflicts between sources MUST be shown to the user with both citations, never silently
  resolved. TODO(SOURCE_PRECEDENCE_OWNER): the precedence order requires a named business
  owner, especially for Corvane SOP versus Kyltek work-instruction conflicts.

Rationale: the most dangerous answers in this domain are correct for a different serial or
an older revision.

### V. Restricted Procedures Are Safety Controls (NON-NEGOTIABLE)

- Procedures requiring a certification (high voltage, refrigerant handling, confined space)
  MUST NOT be presented, summarized, or paraphrased to users lacking that certification,
  regardless of which document contains the steps.
- Ingestion MUST tag passages containing restricted-procedure content with the corresponding
  certification groups. Content tagging MAY only add restrictions, never remove them.
- For uncertified users, the system MUST state that certification is required and offer to
  draft a work order or escalation instead of steps.

Rationale: performing these procedures without certification is unsafe or illegal; the
control is a lockout, not a confidentiality preference.

### VI. The Assistant Drafts, Humans Commit

- The assistant MAY draft work orders and escalations; it MUST NOT submit them to MaintPro,
  Servio, or any external system without explicit human confirmation.
- Drafts requiring parts, certifications, specialists, or return visits MUST be approved by
  an authorized role before submission. TODO(WORK_ORDER_APPROVERS): confirm approving roles.
- Every submission MUST carry an idempotency key so retries cannot create duplicates.
- Every answer, draft, approval, and submission MUST be audit-logged with the user, the
  sources shown, and the outcome.

Rationale: reading cannot damage equipment; committing parts, people, and visits can.

### VII. Measured Before Shipped

- Changes to retrieval, prompts, models, ingestion, or policy MUST pass the evaluation suite
  before release.
- Release-blocking checks: zero restricted-content disclosures on adversarial and paired
  questions; ACL property tests over every user-document pair; fail-closed ingestion tests;
  citation validity on the golden set.
- The golden set MUST contain real technician questions, the asking user, and an expert
  reference answer. Paired questions MUST exist for every restricted procedure (same question,
  certified and uncertified user).
- Failures MUST be categorized (ingestion, retrieval, applicability, generation, citation,
  policy) so fixes target the failing stage.
- Targets MUST be set from risk and field data, not universal thresholds.

Rationale: the model is probabilistic; only measurement shows whether the system is safe.

### VIII. Simplest Architecture That Passes the Evaluation

- The answer path MUST be a deterministic pipeline: identify user, resolve asset, retrieve,
  filter applicability, check sufficiency, generate, validate citations.
- Autonomous agents, multi-agent orchestration, and fine-tuning MUST NOT be introduced
  without an evaluation result showing the deterministic pipeline fails a requirement they fix.
- Infrastructure (queues, orchestration platforms, extra services) MUST be justified by
  measured load or reliability needs.

Rationale: predictable systems are easier to verify, debug, and trust when mistakes are
expensive.

## Corpus and Ingestion Constraints

- The corpus is a running list: ingestion MUST support adding, updating, and deleting
  documents incrementally. Deletions and ACL changes MUST propagate to the index, and the
  index copy of ACLs MUST NOT be the final authorization decision.
- Every passage MUST trace to its source document, location (page, section, or record),
  version, and ingestion time.
- Each passage MUST carry metadata: equipment model, applicable serial range, revision and
  date, source type and authority tier, language, and required groups.
- Scanned documents MUST be OCR-processed; non-English sources (German, Dutch) MUST remain
  searchable from English questions, with the original text available for citation.
- Superseded revisions and duplicate copies MUST be linked to the current version.
- Maintenance histories from MaintPro (NA) and Servio (EU) MUST be normalized into one asset
  history model while preserving the original record identifiers.
- The client is primarily a phone at customer sites with unreliable connectivity: answers
  MUST be concise, steps numbered, and sources viewable on mobile. Latency targets SHOULD start
  at p95 ≤ 15 s to a first useful answer and be revised from field measurements.

## Development Workflow and Quality Gates

- Features follow the Spec Kit flow: specify, clarify where needed, plan, tasks, implement.
- Every plan MUST include a Constitution Check mapping the design to Principles I–VIII and
  justifying any exception in a complexity-tracking entry.
- Every specification MUST state, for each user-facing behavior, its authorization rule,
  its evidence requirement, and its abstention behavior.
- Code review MUST verify: no authorization logic in prompts, no unvalidated citations, no
  external writes without confirmation, and tests for any new data source's ACL mapping.
- Evaluation results MUST accompany any change to retrieval, prompts, models, or policy.

## Governance

This constitution supersedes other project practices. Amendments require a written proposal
stating the change, its rationale, affected principles, and the migration plan for existing
specs and code, approved by the technical owner. Versioning follows semantic versioning:
MAJOR for removing or redefining a principle, MINOR for adding a principle or materially
expanding guidance, PATCH for clarifications. Compliance is reviewed at every plan's
Constitution Check and in code review; unresolved violations block release.

**Version**: 1.0.0 | **Ratified**: 2026-10-11 | **Last Amended**: 2026-10-11
