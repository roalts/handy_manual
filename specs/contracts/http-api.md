# Contract: HTTP API

Owner: 003 answer API. Consumers: 004 web client, 006 evaluation harness. JSON over HTTPS, served
by one process on `http://localhost:8000` in development. The web client is served from the same
origin, so no CORS.

## Sessions

| Method and path | Body | Returns |
|---|---|---|
| `POST /api/session` | `{"user_id": "u03"}` | `200` `Identity` and a signed, HTTP-only session cookie |
| `GET /api/session` | | `200` `Identity`, or `401` |
| `DELETE /api/session` | | `204` |

Development sign-in picks a user from `users.json` with no password; it is a stand-in for the real
identity provider and is disabled when `APP_ENV=production`. The cookie carries only the user ID,
signed with `SESSION_SECRET` from `.env`. Groups are re-read from `users.json` on every request.
Every endpoint below returns `401` without a session.

| Method and path | Returns |
|---|---|
| `GET /api/dev/users` | `{"users": [{"user_id", "name", "title", "groups"}]}` for the sign-in list; development only, `404` when `APP_ENV=production`; no session needed |
| `GET /api/groups` | `{"<group id>": "<plain description from users.json>"}`, for explaining missing groups; needs a session |

## Errors

Every non-2xx response has the body `{"error": "<code>", "detail": "<optional text>"}`. Codes:
`unauthenticated` (401), `not_visible` (403), `forbidden` (403, e.g. approving your own draft),
`not_found` (404), `invalid_request` (422), `invalid_state` (409, wrong draft state for the
action), `not_editable` (409, PATCH on a draft not in `draft` or `rejected`),
`model_unavailable` (503), `submission_failed` (503, the target system or its outbox could not be
written; the draft stays `approved` and a retry with the same key is safe).

Every `/api` response, including `page.png`, sends `Cache-Control: no-store`. The session cookie is
`HttpOnly; SameSite=Lax; Path=/` so image requests carry it.

## Asking

`POST /api/ask` with `AskRequest` returns `200` with `AnswerResponse` (answer.md).

- `422` for an invalid body, such as an empty question.
- `previous` (follow-ups, answer.md) is passed to the engine unchanged. The API does not look it
  up or store conversations; the client holds the last answer.
- `503` with `{"error": "model_unavailable"}` when the model provider fails. The API never falls
  back to an ungrounded answer.

## Sources (citation viewer)

`GET /api/sources/{passage_id}` returns:

```json
{
  "passage_id": "p_79e8...", "doc_id": "doc_4d74...", "title": "Halden HCP-350 IOM Rev D",
  "doc_type": "service_manual", "revision": "D", "issue_date": "2024-03-01", "status": "active",
  "superseded_by": null, "locator": "p. 7, 8.4 Replacing the mechanical seal",
  "lang": "en", "text_original": "...", "text_en": null,
  "page": 7, "page_image_url": "/api/sources/p_79e8.../page.png",
  "ocr": false, "possibly_stale": false
}
```

- `403` with `{"error": "not_visible"}` when the passage exists but the user can't see it, and
  `404` only when it doesn't exist.
- `text_original` is always present; `text_en` is present for translated passages. Withheld scan
  values appear as `[[unverified:<id>|page=<n>]]` and the client renders them as unverified.
- `page_image_url` is `null` unless the passage has a page **and** every passage on that page is
  visible to the user (`serving.page_fully_visible`). Otherwise the client shows the text only.
  This stops a page image from leaking a restricted section that shares the page.

`GET /api/sources/{passage_id}/page.png` returns the page image (the stored scan image for OCR'd
pages, otherwise the PDF page rendered at 150 dpi), downscaled to at most 1,600 px wide for phones.
Same visibility rule; `403` otherwise.

## Static files and client routes

The API serves one built client directory at `/`, set by `WEB_DIR` (default `web-react/dist/`,
the Vite output): `index.html`, and files under `/assets/` with the right `Content-Type` (`.js`
`text/javascript`, `.css` `text/css`, plus `.svg`, `.png`, `.woff2` if present). Nothing outside
that directory.

`/sources/*` and `/work-orders/*` also return `index.html`; these are client routes
(see answer.md, `viewer_url`). Unknown paths outside `/api/` are `404`, never a directory listing.
Static files are gzipped when the request's `Accept-Encoding` allows it, with
`Vary: Accept-Encoding`.

## Work orders

See work-orders-audit.md for states and rules.

| Method and path | Body | Returns |
|---|---|---|
| `POST /api/work-orders` | `{"answer_id", "suggestion": WorkOrderSuggestion, "asset_id"?, edits...}`; `asset_id` is required when `suggestion.asset_id` is null and must match it otherwise | `201` `WorkOrderDraft`; `422 invalid_request` for a missing, unknown or mismatched `asset_id`; `403 not_visible` only when a cited passage is hidden |
| `GET /api/work-orders?mine=true` | | drafts visible to the user |
| `GET /api/work-orders/{id}` | | `WorkOrderDraft`, `403`, or `404` |
| `PATCH /api/work-orders/{id}` | any of `summary`, `work_steps`, `priority`, `fault_code`, `parts`, `needs_specialist`, `return_visit` (others, including `citations`: `422`) | `WorkOrderDraft` (only in `draft` or `rejected`, else `409 not_editable`) |
| `POST /api/work-orders/{id}/request-approval` | | `WorkOrderDraft` in `pending_approval` |
| `POST /api/work-orders/{id}/approve` and `/reject` | `{"note"}` | approvers only, else `403`; the note is stored as `decision_note` |
| `POST /api/work-orders/{id}/submit` | `{"confirm": true}`, header `Idempotency-Key` | `200` `WorkOrderDraft` with `external_ref`; repeating the key returns the same result |

## Health

`GET /api/health` returns `{"status": "ok", "dataset_version": "ds_0026"}`.
