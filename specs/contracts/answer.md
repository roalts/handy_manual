# Contract: Answer (engine output, API response)

Owner: 002 answer engine. Consumers: 003 answer API (passes it through unchanged), 004 web client
(renders it), 006 evaluation (scores it). Types: `src/copilot_contracts/answer.py`. JSON Schema:
`examples/answer-response.schema.json`.

## Call

```python
class AnswerEngine(Protocol):
    def answer(self, identity: Identity, request: AskRequest) -> AnswerResponse: ...
```

The engine is a Python library the API calls in-process. `Identity` is built by the API from the
session (user ID, name, groups); the engine never derives identity from the question.

`AskRequest`: `question`, plus `asset_id` and `clarification_of` when the user is answering a
clarification, plus `previous` when the message follows an earlier answer.

**Follow-ups (one turn of memory).** `previous` is `{answer_id, question, asset_id}` of the
answer being followed, where `question` is that answer's `question_used` (or its typed text). The
memory is held by the client, not the server. The engine first decides, from the two texts,
whether the new message continues the previous question ("Oh, I meant HCP-200", "and the
torque?") or starts a new one. If it continues, the engine rewrites it into one standalone
question, keeps `previous.asset_id` unless the new message names another machine, and returns
the rewrite as `question_used`. Everything after that (identifiers, retrieval, access, checks)
runs on the standalone question exactly as for a first question. `previous` grants nothing:
retrieval still uses the asker's groups.

**Unknown model or asset ("did you mean").** When the question names a model or asset ID that is
in neither the fleet nor the documents, and code finds close known ones (same family, a digit
added, dropped or changed, or one character off), the engine answers `clarify` with options
that each carry a `question`: the same text with the corrected name. The client resends that
`question` as a new ask (with the same `previous`, if any). With no close match it abstains with a
message saying the name isn't in the documents, never "not visible to you".

## Response statuses

| Status | Meaning | Required payload |
|---|---|---|
| `answer` | Grounded answer | `sentences` (each with at least one citation) |
| `clarify` | The answer depends on which machine, or a named model/asset doesn't exist; ask first | `clarification`: 2 or more machine options (`asset_id`), or 1 or more "did you mean" options (`question`) |
| `restricted` | The work needs a certification the user lacks | `restricted` (procedure name, missing groups, visible citations); usually `sentences` saying so and a `work_order_suggestion` |
| `abstain` | No permitted source covers it | `abstain_reason`; a `not_visible` notice only when the reason is `not_visible` (sources exist but are hidden); every other reason explains itself in a `no_answer` notice |

`AnswerResponse.check()` enforces these and that every referenced passage ID is in `citations`.
Producers must call it; consumers may rely on it.

## Field meanings

- **`sentences`**: in display order. `kind` is `statement`, `step` (with `step_number`, rendered
  as a numbered list) or `warning`. Text is in `segments`; a segment of kind `unverified` is a
  withheld scanned value and has no text. Render it as "value unverified, see scanned page
  `page`" with a link to `/sources/{page_image_passage_id}`.
- **`citations`**: keyed by `  passage_id`. `viewer_url` (`/sources/{passage_id}`) is a client route, not an API path: the web
  client opens its source viewer there, which calls `GET /api/sources/{passage_id}`. Flags: `superseded`, `possibly_stale`, `ocr` (from a scan), `translated` (the
  English text is a machine translation; the original is shown in the viewer).
- **`conflicts`**: sources that disagree, both sides cited. `preferred` is chosen by code
  (applicability to this machine first, then authority tier) or `null` when code can't decide.
  The client always shows both sides.
- **`notices`**: one-line banners: superseded revision, possibly stale, bulletin applies, check on
  site, unverified value, not visible, translated, service history used.
- **`asset`**: the resolved machine, with every bulletin's status for it from
  `serving.bulletin_assets`.
- **`work_order_suggestion`**: prefill for a draft (005). Every value is taken from a cited passage
  or the asset record; the engine never invents parts or codes.
- **`timings_ms`**: per step (`resolve`, `retrieve`, `filter`, `sufficiency`, `generate`,
  `validate`) plus `total`, for the latency target and failure analysis. Consumers must accept
  other keys.
- **`work_order_suggestion.asset_id`** may be `null` when no single machine was resolved (for
  example a restricted answer to a model-level question); the draft form then asks for the machine.

## Guarantees the engine gives

1. Every citation was in the prompt and is visible to `identity` at answer time.
2. Every specification value, part number, fault code, case number, asset ID and serial in a
   sentence appears in at least one of that sentence's cited passages, or is a field of the
   resolved `asset` record (exact, after whitespace and unit-spacing normalization). Sentences that fail are dropped or regenerated once; if nothing
   survives, the status is `abstain`.
3. No content of a restricted procedure the user can't see is ever present, summarized or
   paraphrased. Only its name and missing groups appear.
4. Evidence about a different model, serial range or site is never used as a substitute.
