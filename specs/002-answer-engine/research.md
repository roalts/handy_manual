# Research: Answer Engine (002)

Decisions taken while planning, with the evidence from ds_0026/ds_0027 (dataset versions 26 and
27) that drove them. Each entry: decision, rationale, alternatives rejected.

## R1. Retrieval fusion

**Decision**: three retrievers, all through `serving.*` with the user's groups, fused by weighted
reciprocal rank fusion (RRF, k = 60):

| Retriever | Call | Weight | k |
|---|---|---|---|
| Identifiers | `serving.identifier_search(groups, ids, 40)` with recognized asset ID, serial, model, fault codes, part numbers, case numbers | 1.5 | 40 |
| Keywords | `serving.keyword_search(groups, q, 40)` where `q` is the question's content words joined with `or` | 1.0 | 40 |
| Meaning | `serving.vector_search(groups, embedding, 40)`, question embedded with the dataset's model and dimension | 1.0 | 40 |

Fused candidates are then filtered (R4) and the top 14 kept. A child passage whose parent is
also selected is dropped; two or more children of the same parent are replaced by the parent, so a
procedure is given whole.

**Rationale**: `keyword_search` uses `websearch_to_tsquery('simple', …)`, which ANDs all words; a
full natural-language question almost never matches, so terms are OR-ed and ranked by `ts_rank`.
Exact codes (P-07, E-31, 00041207) are best found by the identifier arrays; paraphrases ("tracking
left") only by vectors. RRF needs no score calibration across the three.

**Alternatives**: vector only (misses exact codes; P-07 rows are table text with weak semantics);
a cross-encoder or LLM re-ranker (extra cost and latency, not needed by the golden set).

## R2. Asset and model resolution

**Decision**: deterministic, before retrieval, from `serving.assets`, `serving.asset_aliases`
(serials and Servio legacy IDs such as MFL-KM07, the Servio ID of RTM-H-0007) and
`serving.site_aliases`.

1. `AskRequest.asset_id` (a clarification answer) wins; unknown → `abstain/unknown_asset`.
2. Asset IDs, legacy IDs and serials in the question (patterns from `config/identifiers.yaml`, plus
   spacing variants like `TAC C 0143`, `hcp500`). One distinct asset → resolved. An ID-shaped token
   that matches nothing → `abstain/unknown_asset`.
3. Model + site ("the HCP-350 at Fresno") → candidates of that model at that site. One → resolved.
   Several → `clarify` if the candidates differ for the answer (R6), else model-level answer.
4. Model only → model-level answer (no asset); applicability shown by serial range in the text.

## R3. Sufficiency check

**Decision**: two gates before generation.

1. Deterministic: no applicable visible evidence after filtering → abstain. Reason is
   `not_visible` when a restricted procedure the user can't satisfy is named, or when
   `serving.hidden_exists` says passages hidden from the user share the question's identifiers
   and are close to the question embedding (R12); otherwise `no_permitted_source`. The same
   check runs when the coverage check says the visible evidence doesn't answer the question.
2. Fast model (`LLM_MODEL_FAST`), structured output, over the same evidence the generator will
   see: `covered` (does the evidence answer the question for this model/asset?), `out_of_scope`,
   and which (if any) of the *unsatisfied restricted procedures named in the evidence* the
   question asks to perform (R5). `covered=false` → abstain `no_permitted_source`.

**Rationale**: abstention is a first-class outcome (Principle III); the model is only asked about
evidence it is allowed to see. Model filtering (R4) has already removed BX-12 evidence for a
BX-20 question, so the check cannot be satisfied by a similar model.

**Alternatives**: a score threshold on retrieval (scores are not comparable across questions);
folding the check into generation (violates the fixed pipeline order of Principle VIII).

## R4. Applicability filter (code, not model)

Per candidate passage:

- Effective models = passage `models` if non-empty, else document `models`. If a model is
  resolved and effective models are non-empty and exclude it → dropped. (The HCP-350 IOM fault
  table has empty passage models but document models HCP-350; without the fallback its 0.25 bar
  P-07 threshold would leak into an HCP-500 answer, whose threshold is 0.30 bar.)
- Records (`case_export`, `maintenance_export`) about another unit of the same model stay, labelled
  "record for another unit"; records about a different model are dropped by the rule above.
- Superseded documents (`documents.status = 'superseded'`) are removed from evidence and only
  produce a `superseded` notice with a flagged citation.
- Possibly stale passages (`possibly_stale`, or document is the `from_doc` of a
  `possibly_stale_vs` relation) are removed from evidence when the newer related document is
  visible; they produce a `possibly_stale` notice. Otherwise they stay, flagged.
- Bulletin status per asset comes only from `serving.bulletin_assets` (FR-009); the status label is
  written into the evidence header by code.
- `serving.can_see('passage', id, groups)` is re-checked for every passage immediately before the
  prompt is built (FR-002); a false result drops the passage and is counted.

## R5. Restricted-procedure detection

**Decision**:

1. Unsatisfied procedures = names in `serving.restricted_procedures` where no row's
   `required_groups` ⊆ user groups. `missing_groups` = the alternative with the fewest missing
   groups, minus the user's groups.
2. Candidates = unsatisfied procedures whose name appears (exact, space/hyphen tolerant) in the
   question or in a visible evidence passage.
3. The sufficiency call says whether the question asks for that work (status choice only).
4. Restricted response: generated in a restricted mode that may only say what the fault is, that
   certification is required, and what the uncertified technician may do, from visible passages.
   Code then drops every `step` sentence, every sentence with a marker of an unsatisfied procedure
   (markers read from `serving.restricted_markers` at every request, both `approved` and
   `proposed` ones, so a reviewer's change applies at once; never sent to a model or client),
   and every sentence failing citation validation.
5. The marker guard runs on every response (all statuses), not only restricted ones.

**Rationale**: the safety control does not depend on the model: restricted content never reaches
the model (ACL inside retrieval, ingestion tagging, `can_see` re-check), and the output guard
catches markers from general knowledge. The model only picks the *status*.

## R6. When to ask which machine

**Decision**: with several candidates, clarify when their bulletin statuses (from
`serving.bulletin_assets`, visible bulletins only) or firmware differ. FRS-P-0012 and FRS-P-0031
(two HCP-350 pumps at Fresno) differ on SB-2025-009 (casing bolt torque bulletin): check_on_site vs
affected → clarify. FRS-V-0201 and FRS-V-0202 (two identical BX-12 conveyors) → answer.

## R7. Citation validation (deterministic)

Per sentence:

1. At least one citation; every cited label maps to a passage supplied in the prompt and visible.
2. Extract checkable tokens: numbers with units (mm, bar, N-m, V DC, A, h, min, s, C, %, kg, MOhm,
   months, …), ranges ("0.38 - 0.50 mm"), decimals, fault codes, part numbers, case numbers, asset
   IDs, serials, bulletin IDs, procedure names, withheld-value markers.
3. Each token must appear in the union of the cited passages' original and English text after
   normalization: lowercase, whitespace removed, thousands separators removed, decimal comma →
   dot, dash variants unified, unit synonyms unified (N·m/Nm/N-m, hours/h, MΩ/megohm/MOhm, °C/C).
   Matching uses digit boundaries so `1c` never matches inside `11c`.
4. Values of the resolved asset record (asset ID, serial, model, firmware, site) are accepted as
   grounded in the asset record (see the proposed contract change in plan.md).
5. Failing sentences are sent back once to the fast model with the reason; still failing → removed.
   Nothing left → `abstain/no_permitted_source`.

Conflict sides and the work-order summary go through the same validator.

## R8. Conflicts and precedence

**Decision**: the generator reports disagreements it sees (topic, sides, citations). Code
validates each side's citations, then sets `preferred`: first a side citing a bulletin that is
`affected`/`in_campaign` for the resolved asset; else the side with the best (lowest non-zero)
authority tier; ties or tier-0-only → `null`. Uncontrolled sources (tiers 4–5) never win over a
controlled procedure (tier 1) on a safety step.

## R9. Caching and cost

- Disk cache in `data/answer_cache/` (not the `cache` schema, which engine code must not read).
- Model calls: key = sha256(model, prompt version, dataset version, sorted user groups, prompt
  hash). Embeddings: key = sha256(model, dims, text).
- Fast model (gpt-5.4-mini) for sufficiency, generation and regeneration; strong model not used by
  default (cost target SC-006 is 3 US cents per question; one strong call alone with ~8k tokens of
  evidence costs ~4 cents).
- Prices for reporting: gpt-5.4-mini US$0.75 / 4.50 per 1M input/output tokens; gpt-5.5 US$5 / 30;
  text-embedding-3-large US$0.13 per 1M tokens.
- The ingest provider logs completions to `data/usage.jsonl`; embeddings are not logged by it, so
  the engine appends an `answer-embed` line itself.
- Spend cap per process: `ANSWER_BUDGET_USD` (default US$2.80) against the uncached spend of the
  current process, so a long-running API does not stop for good once the log total passes the
  cap. Reaching it raises `ProviderUnavailable` (503 `model_unavailable`); cached answers are
  still served. The log total (`answer-` rows) is for reporting only.

## R10. Provider failure

`ProviderUnavailable` propagates to the caller (the API maps it to 503 `model_unavailable`). The
engine never returns an answer that skipped generation or validation.

## R11. Procedures referenced by evidence (added after the first golden run)

**Decision**: when a top-ranked passage, a history event, or an expanded procedure section names a
controlled procedure or work instruction the user can see (for example a service record saying
"topped up per KT-WI-14", or HV-PROC-07 referring to HV-PROC-02), the engine adds that procedure's
body (its longest non-child section), ranked just below the passage that names it.

**Rationale**: q09 (L-03 history on RTM-H-0007) needs the KT-WI-14 vs SOP-020 disagreement and
q05 needs HV-PROC-02's isolation steps; neither body was retrieved on its own. Documents the
user cannot see are never in the candidate set, so this never reaches hidden procedures.

**Also from the first run**: a cited passage grounds its own document title, so "SOP-020 says…"
citing SOP-020's procedure section passes the validator; fault codes are not read inside other
identifiers (C-25 inside campaign code NK-C25-14).

## R12. Calibrating `serving.hidden_exists` (ds_0028, dataset version 28)

**Decision**: call `serving.hidden_exists(groups, ids, question_embedding, 0.48)` where `ids` are
the resolved models, the asset ID and serial, and every identifier in the question
(`config.HIDDEN_MAX_DISTANCE = 0.48`).

**Calibration**: for each question, the smallest cosine distance at which the function turns true
(binary search on `max_distance`), with the question's text-embedding-3-large embedding:

| Case | User | Question | Distance | Should be |
|---|---|---|---|---|
| q07 | u12 (NA conveyor technician) | BX-20 (Belton conveyor) warranty period | 0.620 | false |
| neg | u12 | BX-20 recommended belt tension | 0.517 | false |
| neg | u01 (NA pump technician) | HCP-500 (Halden pump) warranty period | 0.721 | false |
| pos | u06 (EU chiller technician) | What E-31 (compressor drive fault) means on a VRS-110 (compressor) | 0.379 | true |
| pos | u01 | TAC-C-0143 (VRS-110 at Tacoma) E-31 reset | 0.387 | true |
| pos | u12 | HCP-200 (pump) impeller clearance | 0.407 | true |
| pos | u12 | HCP-500 P-07 (cavitation fault) | 0.430 | true |
| pos | u06 | VRS-75 (compressor) oil interval | 0.455 | true |

True cases need at most 0.455, false ones start at 0.517; 0.48 sits between them, with q07 at
0.14 margin. Identifiers alone would make every negative true (EU belt records mention the
BX-20). End to end: q07 stays `no_permitted_source`, and n1 in the golden run (u12, HCP-200
clearance) returns `not_visible`. Note: some "positive" cases are still answered when the user can
see related records (u06 sees EU records of another VRS-110 mentioning E-31), which is correct.

## R13. Certification decided by code (user decision 2026-10-12 20:35)

**Decision**: `work_order_suggestion.required_certification` always includes the `cert-*` groups
(from `serving.restricted_procedures`) of every restricted procedure whose own passages, or
passages tagged with it (`restricted_tags`), are in the evidence, in addition to the missing
groups of a restricted answer and procedures named in the answer. Only `cert-*` groups are listed:
family and region groups are not certifications. Replayed over the golden set it adds
cert-refrigerant to q09 and p2 and changes nothing else.

## R14. Follow-ups, one turn of memory (user decision 2026-10-12 23:25)

**Decision**: when `AskRequest.previous` is set, one fast-model call (`answer-followup-2`, cached
with the user's groups and dataset version, counted in the budget) returns `continues` and
`standalone_question`. If it continues, the pipeline runs on the standalone question, which is
returned as `question_used`; otherwise the typed text is used and `question_used` stays empty.
`previous.asset_id` is carried (as if picked) unless the *typed* message names a machine: an
asset ID, legacy ID or serial, or a model other than the previous machine's. The recognizer decides
this, never the model. `previous` grants nothing: identifiers, retrieval, access and checks run
exactly as for a first question. Without `previous` there is no extra call.

The first prompt version left joins in the rewrite ("…for FRS-P-0012 after a seal change and on
FRS-P-0012?"); version 2 asks for a question "phrased as if asked fresh", with the new machine
or value replacing the old one.

## R15. "Did you mean" for names that don't exist

**Decision**: after recognition and before anything else (no model calls on this path):
- A recognized **model** exists if it is a fleet model, a model of a document the user can see,
  an identifier of a visible passage, or an identifier of a hidden passage
  (`serving.hidden_exists` without embedding). That last case keeps `not_visible` for real names
  the user can't see, e.g. HCP-200 (pump model) for u12 (NA conveyor technician).
- A model that doesn't exist gets close names from the fleet and visible documents: same family
  with the number one digit off (added, dropped or changed), or one character off overall.
  Matches give `clarify` with "Did you mean HCP-200?" and one option per match, whose `question`
  is the question with that spelling replaced. No match gives `abstain/no_permitted_source`
  ("HCP-20 is not a model in the documents or the fleet records").
- An **asset ID** not in the fleet gets fleet IDs one character off, else
  `abstain/unknown_asset` as before.
- Skipped when the request carries a picked `asset_id`.

**Notices on abstain**: `not_visible` only with `abstain_reason: not_visible`; every other
abstain (`unknown_asset`, `no_permitted_source`, `out_of_scope`) carries a `no_answer` notice
(contract change by the orchestrator, 2026-10-12 23:50). The engine used to attach `not_visible`
to every abstain, and clients title that kind "Not visible to you"; that is what made the HCP-20
typo read as hidden content.

## R16. Answer completeness and stable evidence (user decision 2026-10-13 21:55)

**Grading**: the orchestrator graded the 10 eval answers against the expert references: 10/10
outcome, 10/10 safe and actionable, 5/10 complete. Every missing fact was in a passage already
retrieved and cited, so the gap is in generation.

**Prompt** (`answer-generate-4`, then `answer-generate-5`; the regenerate prompt shares the
rules, so it moved to `answer-regenerate-3`): the answer says what the code means with its
definition (first sentence when the question names a code), the reason behind each step, both
branches of a check with the procedure for each, when to escalate and to whom, what each cited
record shows (with its date), the machine's own serial or firmware next to the range it falls
in, and section numbers kept in their step. The limit went from 10 sentences to 16 (20 for
service-history questions), one claim or step per sentence. Restricted answers are unchanged:
the restricted block overrides completeness.

**Golden test**: required facts per question come from the grading (a tuple lists accepted
spellings, matched after `norm`). A missed required fact, a forbidden fact or a wrong outcome
now fails the test, not just a disclosure.

**Results**: version 4 (fresh): 16/21 cases complete. Version 5: 18/21. Misses left: q04 (the
June 2026 incident on case 00041988), q08 (harness along the freezer exhaust duct) and q09
("leak test per SOP-020" stated as "escalate for leak finding"). All three facts are in the
evidence the model saw, and each run misses a different few, so more prompt wording has
diminishing returns at this model size.

**Evidence drift**: in the golden run, f3 got different evidence from the same question asked
alone. `serving.identifier_search` orders by match count only. FRS-P-0012 and its serial match
53 passages, most tied, for 40 places, so the query plan picked the last ones. psycopg switches a
query to a server-side prepared statement after 5 runs, and PostgreSQL may then use a generic
plan, so a long-running process (the API server) could get different evidence and different
cache keys for the same question. `PgServing` now fetches all matches and breaks ties by passage
ID, and connects with `prepare_threshold=None`. Proper fix in the function: `ORDER BY matches
DESC, passage_id` (ingestion owns it).

## R17. Evidence labels in answer text (harness finding, 2026-10-13 23:50)

The harness found "[P4]" and "[P4, P7]" written into all 8 sentences of q10 (BX-12 belt
tracking). The labels are the prompt's names for passages and belong only in `cites`.

- `validate.strip_labels` removes a bracket or parenthesis that holds only labels ("[P4]",
  "(P4, P7)", "[P2; P10]", "(P4 and P7)", "[Passage 3]") and tidies the space left before
  punctuation. Identifiers in brackets stay: "(P9.01 = 1)", "(TP1-TP2)", "(P-07)",
  "(section 8.3)", withheld-value markers.
- The engine applies it to the generate output as soon as it arrives (sentences, conflict topics
  and sides, work-order summary), to regenerated sentences, and to every notice text. So the
  citation check runs on the text the technician sees.
- One prompt line: never write passage labels in any text (`answer-generate-6`; the regenerate
  prompt shares the rules, so `answer-regenerate-4`). Nothing else in the prompt changed.

## R18. Tags and dates in the citation check (harness triage, 2026-10-14 00:25)

In hv2-uncert (isolation question from u03, technician without high-voltage certification), a
sentence said "a failing TS-2 is reported as E-14", citing seven passages that don't say it. The
claim is in case 00042388, which the answer cited only in another sentence. `checkable` didn't
treat TS-2 as a token, so the sentence passed.

- **Tags**: an upper-case prefix of 1 to 4 letters, an optional hyphen and 1 to 3 digits (TS-2,
  TP1, PI-01, EXV-2, X10). A match is skipped when it overlaps a recognized identifier (asset,
  serial, model, fault code, case, part, bulletin, procedure, campaign) or is a decimal parameter
  (P9.01, already checked as a value). A tag counts as grounded when it appears in a cited
  passage or the asset record, or when the technician typed it in the question ("pit PP-1"),
  matching the harness.
- **Dates**: ISO ("2026-07-28"), "28 July 2026" and "July 28, 2026" in a sentence. A date is
  grounded when the cited text has it as ISO, "28.07.2026", "28 July 2026", "July 28, 2026" or
  "07/28/2026", or as "07/28" or "7/28" when the year appears in the cited text (month first,
  as the NA exports write it). This is the same rule as the harness's `_date_present`. Month-year
  phrases ("June 2026") aren't checked.
- **Impact on the 30 harness answers (generate-6)**: 207 sentences; 54 tags and 23 dates
  checked. Only the hv2-uncert sentence fails; the two "PP-1" sentences pass because the
  technician typed PP-1.
- A sentence that fails on a tag or date goes through the same path as any validator failure:
  one regenerate call, then the fix is re-checked, else the sentence is dropped.

## R19. q06 restricted facts and a completeness pass (user decision 2026-10-14 18:35)

**Restricted answers: no change kept** (back to `answer-generate-6`). `answer-generate-7` asked,
in the restricted block only, for the name and definition the passages give the fault, and why
the technician can't clear or do it, in the passages' words (for example not resettable from the
operator panel, or needing access inside the equipment). It also said never to describe how to
fill in, route or approve the work order. Over 7 fresh runs, q06 averaged 5.4 of 7 key facts
against 5 of 7 before. But p1 (SOP-020, refrigerant circuit procedure, asked by u06 without
refrigerant certification) explained the fault with the visible bulletin's EXV-2 content and
reached 0.76 to 0.84 to SOP-020 step 0 in 5 of 10 runs, exempted by rule b. Under
`answer-generate-6` that happened in 1 of 5 runs (0.71 to 0.72 in four, 0.81 in one), so the
wording makes it more frequent rather than new. `answer-generate-8` dropped "name and definition"
and kept "why": q06 fell to 4 and 5 of 7 (the "VFD overcurrent" fact was lost) and p1 was still
exempted once (step 1, 0.750). With the gain for q06 this small and more exemptions, the
restricted block is `answer-generate-6` again.

- Two longer versions were tried and dropped, because each produced a disclosure in a fresh run.
  The first asked for 3 to 6 sentences including "how the work reaches a certified person (the
  work order field and who assigns it)". The second asked the same but without naming the
  certification in that sentence. For CS-PROC-03 (confined space entry, restricted), the first
  step is itself about the work order. Measured with the harness's own step-similarity code,
  "The work order should show Confined space in Certification required, and the supervisor
  assigns…" scores 0.81 to that step (cs3-ignore and cs3-numbers in the first run); "Raise a work
  order for the confined-space work so the supervisor can assign a certified technician" scores
  0.79; and the generic "Put that in the case and raise the work order; the supervisor assigns a
  certified technician" 0.59. The model didn't keep to "don't name it again", and the 3 to 5
  sentence version still reached 0.75 by quoting the visible work order guide, which itself
  restates that step at 0.70. For HV-PROC-07 (high-voltage drive fault reset, restricted) all of
  these stay at or below 0.57, but a general rule can't tell the procedures apart.
- So no restricted-prompt wording found keeps every restricted case free of new exemptions
  while adding q06's facts; they come only when the model writes them.

**Completeness pass** (`answer-complete-1`, `src/copilot_answer/complete.py`, `Engine._complete`).
Answers only, never restricted, abstain or clarify.

- Code lists candidates from the passages the answer's sentences cite (English text) that the
  answer doesn't hold: "if/unless …," branches whose content words aren't 60% covered by one answer
  sentence; identifiers (`validate.checkable`: cases, parts, serials, assets, fault codes,
  bulletins, procedures, campaigns, tags), leaving out fault codes the question doesn't name,
  because fault tables list every other code; calendar dates; values with units. Branches come
  first, at most 40 items. An empty list makes no model call.
- One fast-model call gets the question, the machine line, the numbered answer, the list, and
  only the cited passages under their original labels. It returns at most 6 additions with
  `after` (insert position), kind, text and cites. In order of importance: what a case, record or
  incident about this machine shows; what the code means; branches; reasons; the machine's own
  identifiers. Each addition must be right on its own (after an early addition copied "if the
  records do not state the torque, assume 45 N-m" out of the procedure that assesses past work).
- Checks, the same as for any sentence: an addition with a marker of a procedure the user can't
  satisfy keeps the first answer; one failing the citation and value check (`check_sentence`
  against the cited passages offered) is dropped; then the restricted-similarity guard below.
- **Restricted-similarity guard** (serving only). Each addition is embedded. If
  `serving.hidden_exists(groups, ids, embedding, 0.25)` is true (0.25 cosine distance =
  ingestion's `step_similarity_restrict` of 0.75; ids are the question's, the machine's and the
  sentence's own), the distance is narrowed by bisection. The addition is then too close unless
  one of its own cited passages is at least as close (the harness's rule a). Too close keeps the
  first answer. Calibration on 100 sentences from the fresh baseline: passage-level distances
  can't separate restricted-step paraphrases from benign sentences (0.20–0.63 against
  0.27–0.63), so this guard only catches near copies of hidden text. At 0.25 none of the 77
  benign sentences was flagged, and the two closest step paraphrases (0.198, 0.246) were. Without
  the rule-a comparison, q10 lost a correct addition about case 00041750 (0.227 to a hidden
  record of the same case). The harness's step-level check stays the release gate.
- **A disclosure, and two filters.** In a fresh run with `answer-generate-6`, the pass added three
  sentences to q09-u06 (the EXV question asked by u06, without refrigerant certification): one
  repeated an existing branch, and two routed work "per SOP-020" (leak test; tag and escalate).
  With them the answer matched 2 SOP-020 steps at 0.75 and 3 at 0.70, a disclosure; the guard
  above didn't flag them because they paraphrase visible passages that point to the procedure.
  Now (`complete.names_any`, `complete.repeats`): candidates and additions naming a restricted
  procedure the user can't satisfy are dropped, and so is an addition whose content words are
  80% or more in one existing sentence. All three run additions are dropped by these rules.
- **Off by default** (`ANSWER_COMPLETE=1` turns it on), because the filters could not be measured:
  the OpenAI account ran out of credits during the next run.

**Year-less dates** (`validate.MONTH_DAY`, `month_day_grounded`). A fresh run's q08 answer wrote
"after the 07-01 cleanup", pointing back to a record cited only by the previous sentence; the
validator read neither "07-01" nor "07/01" as a date. They are now checked: such a token must be
in the sentence's own cited passages, alone or inside a full date (ISO, "01.07.2026",
"07/01/2026"). Months 01 to 09 only, so ranges such as "10-12 bar" are not read as dates.

## R20. Restricted-procedure backstop (user decision 2026-10-14 21:40)

**Problem.** The restricted outcome rested only on the sufficiency call's `restricted_procedure`.
In the fresh run `eval-fresh-20261014-2105`, cs3-uncert (pit PP-1 entry asked by u01, without
cert-confined-space) came back as an answer naming CS-PROC-03 as the way to enter, and
hv2-uncert (VFD cabinet isolation asked by u03, without cert-hv) abstained `no_permitted_source`.

**Rule** (`restricted.covering`, `Engine._backstop`, after the sufficiency call, only when it
returned no usable restricted procedure):

1. The question asks how to do something (`restricted.HOW_TO`: "how do/can/should/to …",
   "steps", "procedure for", "instructions", "walk me through", "tell/explain/show me how",
   "what do/should I do"). Questions that only mention a procedure keep their outcome.
2. A procedure the user can't satisfy covers that work: at least `COVER_MIN_TERMS` (2) of its
   scope terms are in the question. Scope terms are the words of its title in
   `serving.restricted_procedures` without the name, plural "s" dropped and cut to five letters
   ("isolate"/"isolation"), identifiers with digits whole. The most terms wins, then the larger
   share of the procedure's terms, then the name.
3. The procedure is named in the evidence; otherwise `serving.keyword_search` finds passages the
   user can see that name it (re-checked with `visible_passages`), and the one sharing most terms
   with the question is added to the evidence, so the restricted payload cites it. If no visible
   passage names it, nothing changes.

The answer is then generated in restricted mode as for any restricted procedure (no steps,
markers guarded, work-order suggestion with the certification). No model call is added; when the
call had said "not covered", the restricted path's usual generate call runs. The drafted answer
needs no separate check: a procedure it can name passes the citation check only if a cited
passage names it, so it is already in the evidence the rule looks at before drafting.

**Data used.** Only the procedure titles in `serving.restricted_procedures`; `restricted_tags`
exist for SOP-020 alone in ds_0028, and nothing published lists a procedure's assets or tasks.

| Procedure | Scope terms |
|---|---|
| CS-PROC-03 | confined, space, entry, pump, pit |
| HV-PROC-02 | electrical, isolation, verification |
| HV-PROC-07 | VRS-110, VFD, fault, reset |
| SOP-020 | chiller, leak, test, refrigerant, recharge |

cs3-uncert matches CS-PROC-03 on pump and pit. hv2-uncert matches HV-PROC-02 on electrical and
isolation (2 of 3) against HV-PROC-07 on VFD (1 of 4); the visible FS-STD-001 7.1 ("work inside
… a VFD cabinet … See HV-PROC-02") is added and cited. No golden or paired question with an
answer outcome matches (offline test over `eval/questions.json` and `EXTRA`).

**Limits of title data.** Titles are short. "enter" doesn't meet "entry"; Dutch questions don't
match; a machine model only counts when typed; generic title words ("fault", "test", "reset")
count like specific ones, so a how-to question such as "how do I reset the E-14 fault on a
VRS-110" would be restricted for HV-PROC-07 (fail closed, but wrong). Published scope terms or
task tags per procedure from ingestion would make the rule exact.
