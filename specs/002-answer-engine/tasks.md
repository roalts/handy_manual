---
description: "Tasks for 002 answer engine"
---

# Tasks: Answer Engine

**Input**: `specs/002-answer-engine/` (spec.md, plan.md, research.md)

**Tests**: requested (offline unit tests per deterministic stage, one hosted golden run).

**Status (2026-10-12)**: all tasks done. Unit tests were consolidated into `tests/answer/test_units.py` (validator, identifiers, resolution, applicability, conflicts, restricted detection) and `tests/answer/test_engine.py` (pipeline with fakes), instead of one file per module.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [x] T001 Create `src/copilot_answer/` and `tests/answer/`; add `src/copilot_answer` to wheel packages in `pyproject.toml`
- [x] T002 [P] `src/copilot_answer/config.py`: retrieval weights, k values, prices, prompt versions, restricted markers

## Phase 2: Foundational

- [x] T003 `src/copilot_answer/serving.py`: `Serving` protocol and `PgServing` (only `serving.*`), dataset_info check against settings (refuse to start on mismatch)
- [x] T004 [P] `src/copilot_answer/llm.py`: disk-cached model client (key includes model, prompt version, dataset version, groups, input hash), usage logging for embeddings, cost accounting, `FakeLLM`
- [x] T005 [P] `src/copilot_answer/ids.py`: identifier recognition with spacing variants
- [x] T006 [P] `tests/answer/fakes.py`: in-memory `Serving` fake with a mini corpus mirroring the golden cases
- [x] T007 `src/copilot_answer/identity.py`: Identity from users.json for the CLI

## Phase 3: US1 — Grounded answer (P1) 🎯 MVP

- [x] T008 [US1] `src/copilot_answer/resolve.py`: asset/model/site resolution
- [x] T009 [US1] `src/copilot_answer/retrieve.py`: identifier + keyword + vector retrieval, RRF, parent/child consolidation
- [x] T010 [US1] `src/copilot_answer/applicability.py`: model filter with document fallback, can_see re-check
- [x] T011 [US1] `src/copilot_answer/validate.py`: deterministic citation validator
- [x] T012 [US1] `src/copilot_answer/prompts.py`: sufficiency and generation prompts and schemas
- [x] T013 [US1] `src/copilot_answer/build.py`: citations (locator, flags), segments with unverified markers
- [x] T014 [US1] `src/copilot_answer/engine.py`: pipeline, regenerate-once, timings, `check()`
- [x] T015 [US1] `src/copilot_answer/__main__.py`: CLI `ask --user uNN [--asset ID] "question"`
- [x] T016 [P] [US1] Tests: `tests/answer/test_validate.py`, `test_ids.py`, `test_resolve.py`, `test_applicability.py`

## Phase 4: US2 — Restricted procedures (P1)

- [x] T017 [US2] `src/copilot_answer/restricted.py`: unsatisfied procedures, missing groups, candidates, marker guard
- [x] T018 [US2] Restricted mode in engine and prompts; drop steps; work-order suggestion
- [x] T019 [P] [US2] Tests: `tests/answer/test_restricted.py`, engine test with fake LLM leaking markers

## Phase 5: US3 — Abstain (P1)

- [x] T020 [US3] Abstain reasons: `unknown_asset`, `no_permitted_source`, `not_visible`, `out_of_scope`; all-sentences-failed → abstain
- [x] T021 [P] [US3] Tests: `tests/answer/test_engine.py` abstain cases

## Phase 6: US4 — Applicability, conflicts, stale, bulletins (P2)

- [x] T022 [US4] Superseded/stale handling and notices in `applicability.py`
- [x] T023 [US4] Bulletin statuses into `ResolvedAsset.bulletins`, evidence labels, notices
- [x] T024 [US4] Conflicts with code-chosen `preferred` in `build.py`
- [x] T025 [P] [US4] Tests for precedence and stale/superseded

## Phase 7: US5 — Service history (P2)

- [x] T026 [US5] History intent; `serving.events_for` for the asset; event passages as evidence; history notice

## Phase 8: US6 — Ask which machine (P3)

- [x] T027 [US6] Clarify when candidates differ (bulletins/firmware); tests

## Phase 9: US7 — Work-order suggestion (P3)

- [x] T028 [US7] Suggestion from cited facts: asset, fault code, certification, parts (validated), campaign code from bulletin status

## Phase 10: Polish

- [x] T029 Hosted golden run `tests/answer/test_golden.py` (`@pytest.mark.hosted`) writing `specs/002-answer-engine/golden-run.md`
- [x] T030 `uv run ruff check src tests` and `uv run pytest -q -m "not hosted"` pass

## Phase 11: Follow-up after review (orchestrator REQUEST 2026-10-12 20:15)

- [x] T031 Read restricted markers from `serving.restricted_markers` (approved and proposed); remove the list in `config.py` and the yaml reading
- [x] T032 `not_visible` via `serving.hidden_exists` with the question embedding; calibrate the distance (research.md R12)
- [x] T033 Work-order suggestion with `asset_id: null` when no machine is resolved (restricted answers, or answers with parts)
- [x] T034 Prompt iteration: address the technician as "you"; keep safety warnings from the evidence (`answer-generate-3`)
- [x] T035 Rerun the golden set with model calls bypassing the cache; update `golden-run.md`

## Phase 12: User decisions (orchestrator 2026-10-12 20:35)

- [x] T036 Certification decided by code from restricted procedures in the evidence (research.md R13); offline tests; q09 checked with one hosted call
- [x] T037 Spend cap per process, `ANSWER_BUDGET_USD` (default US$2.80); offline test with a fake provider

## Phase 13: Follow-ups and "did you mean" (orchestrator 2026-10-12 23:25)

- [x] T038 Follow-up rewrite with `previous` (research.md R14): one cached call, `question_used`, machine carried unless the typed text names another
- [x] T039 "Did you mean" for unknown models and asset IDs (`src/copilot_answer/didyoumean.py`, research.md R15); `not_visible` notice only for `not_visible` abstains
- [x] T040 Offline tests for both; golden set extended to 21 cases (t1, f1–f3) and rerun on cache

## Phase 14: Answer completeness (orchestrator 2026-10-13 21:55)

- [x] T041 Generate prompt asks for definitions, reasons, branches, what cited records show and the machine's own identifiers (`answer-generate-5`, research.md R16)
- [x] T042 Golden test: required facts from the expert grading; a missed fact, forbidden fact or wrong outcome fails the test
- [x] T043 `identifier_search` ties broken by passage ID and no server-side prepared statements, so evidence doesn't drift in a long-running process (research.md R16); test against the published schema
- [ ] T044 Remaining misses after two iterations: q04 incident, q08 harness reason, q09 leak-test wording (see answer-engine.md 2026-10-13 report)
- [x] T045 Evidence labels ("[P4]", "(P4, P7)") removed from sentence, conflict, notice and work-order text by `validate.strip_labels`; prompt line against them (`answer-generate-6`, research.md R17); q10 confirmed with `copilot_eval run --only q10`
- [x] T046 Citation check also covers sensor and test-point tags (TS-2, TP1, PI-01) and dates in the passage's own format (research.md R18); hv2-uncert confirmed with `copilot_eval run --only hv2-uncert`

## Phase 15: q06 and the completeness pass (orchestrator 2026-10-14 18:35)

- [x] T047 Restricted answers: fault name, definition and "why you can't" tried (`answer-generate-7`, `answer-generate-8`) and withdrawn because p1 was exempted more often for a small q06 gain; back to `answer-generate-6` (research.md R19)
- [x] T048 Completeness pass for answers: code lists missing identifiers, values, dates and branches from cited passages; one fast-model call adds them; additions checked for markers, citations and closeness to hidden content (`answer-complete-1`, research.md R19)
- [x] T049 Citation check also covers dates without a year ("07-01", "07/01"), which must be in the sentence's own cited passages (research.md R19)
- [x] T050 Completeness pass drops candidates and additions naming a restricted procedure the user can't satisfy, and additions repeating a sentence; off by default (`ANSWER_COMPLETE=1`) until measured (research.md R19)
- [ ] T051 Two fresh runs with `ANSWER_COMPLETE=1` (needs OpenAI credits); turn the pass on by default only with 0 disclosures in both. Dropped for this submission (orchestrator 2026-10-14 21:10); the pass stays off

## Phase 16: Restricted-procedure backstop (orchestrator 2026-10-14 21:40)

- [x] T052 Backstop in code after the sufficiency call: a how-to question about work an unsatisfied procedure covers (scope from its published title) is restricted for that procedure, whatever the call returned; only adds restrictions (`restricted.covering`, `Engine._backstop`, research.md R20)
- [x] T053 When the evidence doesn't name the covering procedure, a passage the user can see that names it is found with `serving.keyword_search`, added to the evidence and cited (hv2-uncert: FS-STD-001 7.1 for HV-PROC-02)
- [x] T054 Offline tests (cs3-uncert and hv2-uncert shapes restricted; certified pairs, mention-only questions and every golden and paired answer question unchanged); one fresh subset run (`data/reports/eval-20261014-2202.md`, copied to `eval-subset-20261014-2202.md`)

## Dependencies

Setup → Foundational → US1 → (US2, US3) → US4 → (US5, US6, US7) → Polish. US2 and US3 share the
engine but touch different modules.
