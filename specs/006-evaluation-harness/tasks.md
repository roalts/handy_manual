---

description: "Tasks for 006 evaluation harness"
---

# Tasks: Evaluation Harness

**Input**: `specs/006-evaluation-harness/` (spec.md, plan.md), `specs/contracts/http-api.md`,
`specs/contracts/answer.md`, `specs/contracts/serving-additions.md`, and the brief in
`specs/coordination/orchestrator.md` ("2026-10-13 21:55 — Eval of the 10 questions").

**Tests**: required by the brief (seeded trials for SC-003, offline against a stub API).

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [x] T001 Create package `src/copilot_eval/` and add it to the hatch `packages` list in `pyproject.toml`
- [x] T002 Create `tests/eval/` with a stub API (`stub.py`) and the recorded 10-question run with its sources (`fixtures/eval10.json`)

## Phase 2: Foundational

- [x] T003 [P] Text normalization independent of the engine (`textnorm.py`)
- [x] T004 [P] HTTP client: dev sign-in per user, ask, sources, health; infrastructure errors (`client.py`)
- [x] T005 [P] Read-only reference reads from `serving.*`: procedures, markers, step lines, visible passages (`reference.py`)
- [x] T006 Own API instance on a free port (never 8000), scratch schema, per-answer cost meter, spend cap (`server.py`, `__main__.py`)
- [x] T007 One category per failure (`categorize.py`), FR-007 and SC-002

## Phase 3: User Story 1 - Golden set score (P1)

- [x] T008 [US1] `eval/key_facts.yaml` from the 10 reference answers, starting from the 21:55 grading (FR-002)
- [x] T009 [US1] Deterministic fact matching by unit and scope (`facts.py`), FR-003
- [x] T010 [US1] Outcome checks (status, abstain reason, restricted procedure and missing groups) in `runner.py`
- [x] T011 [US1] Tests: the recorded run scores like the review; a missed fact in a cited passage is `generation`; q07 with 12 months is `applicability`

## Phase 4: User Story 2 - Restricted-content disclosure (P1)

- [x] T012 [US2] `eval/restricted_pairs.yaml`: pairs and adversarial variants for HV-PROC-07, HV-PROC-02, SOP-020, CS-PROC-03 (FR-004)
- [x] T013 [US2] Markers and ingestion's step-similarity rule, plus the per-sentence rule with the visible-citation exemption (`disclosure.py`), FR-005
- [x] T014 [US2] Calibrate on the recorded answers (negatives) and on q05 and p2 scored for uncertified users (positives); recorded in plan.md
- [x] T015 [US2] Seeded trials: every marker in every kind of text; real markers; real restricted steps (three steps, one step)

## Phase 5: User Story 3 - Citation validity (P1)

- [x] T016 [US3] Re-open every citation as the asker; values of each sentence in its cited passages or the asset record (`citations.py`), FR-006
- [x] T017 [US3] Calibrate the value check on the recorded answers to zero false failures
- [x] T018 [US3] Seeded trials: every value corrupted in turn; every citation swapped for a hidden passage; 38 N-m to 39 N-m

## Phase 6: User Story 4 - Access grid (P2)

- [x] T019 [US4] Reuse `tests/api/test_sources.py::test_exhaustive_grid_matches_can_see` as a subprocess (`grid.py`)

## Phase 7: Report and exit code

- [x] T020 Dated report `data/reports/eval-YYYYMMDD-HHMM.md` and verdict file `.json` (FR-009); `compare` for SC-004
- [x] T021 Exit codes 0, 1 (disclosure, grid, citation), 2 (infrastructure), FR-008
- [x] T022 Final baseline after the engine agent's report (it names `answer-generate-5`): full run, then a second cached run compared for SC-004; report in `specs/coordination/evaluation.md`

## Phase 8: Triage of the answer-generate-6 baseline (orchestrator.md, 2026-10-14 00:10)

- [x] T023 `--dump` option: each response with the sources the harness fetched, for triage
- [x] T024 Value check: a code followed by "-and-later"; ISO dates written as "07/28" in a record of that year, "28.07.2026" or "28 July 2026"; tests for both and for a tag still missing from a sentence's citations
- [x] T025 Per-sentence disclosure exception (rule b) for restricted steps restated by the sentence's own visible citations (user decision 2026-10-14 11:50): every exempted pair listed in the report; tests in `tests/eval/test_exemption.py`

## Phase 9: Fresh run before submission (orchestrator.md, 2026-10-14 17:55)

- [x] T026 `--fresh`: `ANSWER_FRESH=1` for the harness's own API instance only (read by `copilot_answer.build_engine`, default off), refused with `--base-url`, stated in the report; tests in `tests/answer/test_budget.py` and `tests/eval/test_harness.py`
- [x] T027 Fresh run with `--budget 1.00`, compared with the cached baseline; report copied to `specs/006-evaluation-harness/eval-fresh-20261014-1752.md`

## Phase 10: Final fresh run of the default engine (orchestrator.md, 2026-10-14 21:10)

- [x] T028 q05 key fact "E-31 is a VFD overcurrent trip" also accepts "output current above its peak current limit" (DECISION 2026-10-14 18:40; q05 only); test in `tests/eval/test_harness.py`
- [x] T029 One fresh run of `answer-generate-6` with `ANSWER_COMPLETE` unset and `--budget 2.00`, compared with the 17:52 fresh baseline; report copied to `specs/006-evaluation-harness/eval-fresh-20261014-2105.md`
- [x] T030 Citation value check: the article "a" after a number is not amperes ("5.0 a failing"), and a plain word joined to a dotted number is dropped ("under-5.1"); tests in `tests/eval/test_harness.py` (REQUEST 2026-10-14 22:50)
- [x] T031 One cached re-score with the grid, report copied to `specs/006-evaluation-harness/eval-final-20261014-2247.md` (it scored the 22:38 run's answers, not the 22:35 ones; see `specs/coordination/evaluation.md`, 22:54)

- [x] T032 Citation value check: a decimal comma in a cited passage counts as a decimal point ("3,3 bar" grounds "3.3 bar"), after thousands separators are removed, never for lists or dates; tests in `tests/eval/test_harness.py` (DECISION 2026-10-14 23:10)
- [x] T033 Cached re-score with the grid, report copied to `specs/006-evaluation-harness/eval-final-20261014-2304.md`; README line on one fresh run at a time

## Not done

- FR-003 paraphrase judging with the fast model: not needed; every key fact is matched by
  value, identifier or keyword group. Revisit if the user's review of `key_facts.yaml` asks for
  meaning-level facts that keywords can't express.
