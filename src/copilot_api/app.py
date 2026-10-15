"""The answer API (specs/contracts/http-api.md): sessions, ask, sources, work orders, static."""
import gzip
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Protocol

from fastapi import Body, Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from copilot_answer import ProviderUnavailable
from copilot_api.config import ApiConfig
from copilot_api.engines import EnginePool
from copilot_api.identity import Directory, User
from copilot_api.session import COOKIE, Sessions
from copilot_api.sources import ImageRef, SourceResult
from copilot_contracts import AskRequest, AuditEvent, PartLine, WorkOrderSuggestion
from copilot_contracts.services import AuditLog, ServiceError, WorkOrders

log = logging.getLogger("copilot_api")

CREATE_EDITS = {"summary", "work_steps", "priority", "fault_code", "parts"}
EDITABLE = CREATE_EDITS | {"needs_specialist", "return_visit"}
CREATE_FIELDS = {"answer_id", "suggestion", "asset_id"} | CREATE_EDITS
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
                ".png": "image/png", ".woff2": "font/woff2"}
COMPRESSIBLE = {".html", ".css", ".js", ".svg"}


class Sources(Protocol):
    def dataset_version(self) -> str:
        """The dataset version currently served."""
        ...
    def visible(self, groups: frozenset[str], ids) -> set[str]:
        """The passage IDs among `ids` that `groups` may see."""
        ...
    def source(self, groups: frozenset[str], passage_id: str) -> SourceResult:
        """The citation view for a passage, or why it can't be shown."""
        ...
    def render(self, ref: ImageRef) -> bytes | None:
        """The page image as PNG, or None if it can't be rendered."""
        ...


@dataclass
class Deps:
    config: ApiConfig
    directory: Directory
    sessions: Sessions
    engines: EnginePool
    sources: Sources
    work_orders: WorkOrders
    audit: AuditLog


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str | None = None) -> None:
        """`code` becomes the body's `error` value, `detail` its optional `detail`."""
        super().__init__(detail or code)
        self.status, self.code, self.detail = status, code, detail


def error_response(status: int, code: str, detail: str | None = None) -> JSONResponse:
    """The JSON error body `{"error": code}`, with `detail` when given."""
    body = {"error": code}
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status)


def _now() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)


def create_app(deps: Deps) -> FastAPI:
    """The API with its routes, error handlers and client files, all served from `deps`."""
    app = FastAPI(title="Field service copilot API", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.deps = deps
    cfg, directory, sessions, sources = deps.config, deps.directory, deps.sessions, deps.sources

    # ------------------------------------------------------------------ plumbing

    @app.middleware("http")
    async def cache_headers(request: Request, call_next):
        """Never cache API responses; make clients revalidate everything else."""
        response = await call_next(request)
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api") else "no-cache")
        return response

    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        """An ApiError as its JSON error body."""
        return error_response(e.status, e.code, e.detail)

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, e: ServiceError):
        """A work order or audit service refusal, with the status and code it carries."""
        return error_response(e.http_status, e.code, str(e) or None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        """Request validation failures as 422 invalid_request."""
        return error_response(422, "invalid_request", _describe(e.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        """Framework HTTP errors in our error shape; unknown routes and methods are not_found."""
        if e.status_code in (404, 405):
            return error_response(404, "not_found")
        return error_response(e.status_code, "invalid_request", str(e.detail))

    @app.exception_handler(Exception)
    async def unexpected(_: Request, e: Exception):
        """Log the exception and return a bare 500 that reveals nothing about it."""
        log.exception("unhandled error")
        return error_response(500, "internal_error")

    def user_of(request: Request) -> User:
        """The signed-in user; 401 for a missing or bad cookie or a user no longer in users.json."""
        user_id = sessions.user_id(request.cookies.get(COOKIE))
        user = directory.user(user_id) if user_id else None
        if user is None:
            raise ApiError(401, "unauthenticated")
        return user

    Authed = Annotated[User, Depends(user_of)]

    def record(**kw) -> None:
        """Write an audit event with a fresh ID and the current time."""
        deps.audit.record(AuditEvent(event_id=uuid.uuid4().hex, at=_now(), **kw))

    # ------------------------------------------------------------------ sessions

    @app.get("/api/health")
    def health():
        """Health check, with the dataset version being served."""
        return {"status": "ok", "dataset_version": sources.dataset_version()}

    @app.get("/api/dev/users")
    def dev_users():
        """Users for the development sign-in picker; not_found in production."""
        if cfg.production:
            raise ApiError(404, "not_found")
        return {"users": [{"user_id": u.user_id, "name": u.name, "title": u.title,
                           "groups": sorted(u.groups)} for u in directory.users()]}

    @app.post("/api/session")
    def sign_in(body: Annotated[dict, Body()]):
        """Development sign-in as any user in users.json, setting the session cookie."""
        if cfg.production:
            raise ApiError(404, "not_found", "development sign-in is disabled")
        user_id = body.get("user_id")
        user = directory.user(user_id) if isinstance(user_id, str) else None
        if user is None:
            raise ApiError(422, "invalid_request", "unknown user_id")
        response = JSONResponse(_identity(user))
        response.set_cookie(value=sessions.sign(user.user_id), max_age=sessions.max_age,
                            **sessions.cookie_args())
        return response

    @app.get("/api/session")
    def session(user: Authed):
        """The signed-in user's identity."""
        return _identity(user)

    @app.delete("/api/session")
    def sign_out():
        """Sign out by clearing the session cookie; needs no session."""
        response = Response(status_code=204)
        response.delete_cookie(**sessions.cookie_args())
        return response

    @app.get("/api/groups")
    def groups(user: Authed):
        """Permission group IDs with their plain descriptions."""
        return directory.groups()

    # ------------------------------------------------------------------ ask

    @app.post("/api/ask")
    def ask(user: Authed, body: Annotated[Any, Body()] = None):
        """Answer a question and audit it; 503 when the model is unavailable.
        An answer citing a passage the user can't see is withheld as a 500 and audited."""
        identity = user.identity()
        try:
            req = AskRequest.model_validate(body)
        except ValidationError as e:
            raise ApiError(422, "invalid_request", _describe(e.errors())) from e
        if not req.question.strip():
            raise ApiError(422, "invalid_request", "question must not be empty")
        started = time.monotonic()
        details = {"question": req.question, "asset_id": req.asset_id,
                   "clarification_of": req.clarification_of,
                   "previous_answer_id": req.previous.answer_id if req.previous else None}
        engine_ms = 0
        try:
            with deps.engines.engine() as engine:
                t = time.monotonic()
                resp = engine.answer(identity, req)
                engine_ms = int((time.monotonic() - t) * 1000)
        except ProviderUnavailable as e:
            record(user_id=user.user_id, kind="answer", outcome="model_unavailable",
                   details={**details, "error": type(e).__name__})
            raise ApiError(503, "model_unavailable") from e
        hidden = set(resp.citations) - sources.visible(identity.groups, resp.citations)
        if hidden:
            log.error("engine returned citations not visible to %s: %s", user.user_id,
                      sorted(hidden))
            record(user_id=user.user_id, kind="answer", answer_id=resp.answer_id,
                   dataset_version=resp.dataset_version, passage_ids=[],
                   outcome="blocked_invisible_citation",
                   details={**details, "hidden": sorted(hidden)})
            raise ApiError(500, "internal_error")
        record(user_id=user.user_id, kind="answer", answer_id=resp.answer_id,
               dataset_version=resp.dataset_version, passage_ids=sorted(resp.citations),
               outcome=resp.status, details={
                   **details, "question_used": resp.question_used,
                   "abstain_reason": resp.abstain_reason,
                   "restricted_procedure": resp.restricted.procedure if resp.restricted else None,
                   "engine_ms": engine_ms,
                   "api_overhead_ms": int((time.monotonic() - started) * 1000) - engine_ms})
        return JSONResponse(resp.model_dump(mode="json"))

    # ------------------------------------------------------------------ sources

    def source_or_raise(user: User, passage_id: str) -> SourceResult:
        """The passage's source if shown; 404 if missing, 403 (audited) if hidden from the user."""
        res = sources.source(user.groups, passage_id)
        if res.outcome == "not_found":
            raise ApiError(404, "not_found")
        if res.outcome == "not_visible":
            record(user_id=user.user_id, kind="access_denied", dataset_version=res.dataset_version,
                   passage_ids=[passage_id], outcome="not_visible",
                   details={"endpoint": "source"})
            raise ApiError(403, "not_visible")
        return res

    @app.get("/api/sources/{passage_id}")
    def source(user: Authed, passage_id: str):
        """Citation viewer data for a passage, audited as a source view."""
        res = source_or_raise(user, passage_id)
        record(user_id=user.user_id, kind="source_view", dataset_version=res.dataset_version,
               passage_ids=[passage_id], outcome="shown",
               details={"page_image": res.image is not None})
        return res.view

    @app.get("/api/sources/{passage_id}/page.png")
    def page_png(user: Authed, passage_id: str):
        """The cited page as PNG; 403 (audited) if the page holds anything the user can't see."""
        res = source_or_raise(user, passage_id)
        if res.image is None:
            if res.view["page"] is None:
                raise ApiError(404, "not_found", "this passage has no page")
            record(user_id=user.user_id, kind="access_denied",
                   dataset_version=res.dataset_version, passage_ids=[passage_id],
                   outcome="page_not_fully_visible", details={"endpoint": "page.png"})
            raise ApiError(403, "not_visible", "the page holds content not visible to you")
        data = sources.render(res.image)
        if data is None:
            raise ApiError(404, "not_found", "page image unavailable")
        record(user_id=user.user_id, kind="source_view", dataset_version=res.dataset_version,
               passage_ids=[passage_id], outcome="page_image",
               details={"page": res.view["page"], "kind": res.image.kind})
        return Response(data, media_type="image/png")

    # ------------------------------------------------------------------ work orders

    def wo_call(user: User, action: str, draft_id: str | None, fn):
        """Run a work order service call; its auditing is left to the service."""
        # Draft events, refused actions and their access_denied events are recorded by 005.
        return fn()

    @app.post("/api/work-orders", status_code=201)
    def create_draft(user: Authed, body: Annotated[dict, Body()]):
        """Create a work order draft from an answer's suggestion, with optional edits."""
        if bad := set(body) - CREATE_FIELDS:
            raise ApiError(422, "invalid_request", f"unknown fields: {', '.join(sorted(bad))}")
        try:
            suggestion = WorkOrderSuggestion.model_validate(body.get("suggestion"))
            edits = _edits({k: v for k, v in body.items() if k in CREATE_EDITS})
        except ValidationError as e:
            raise ApiError(422, "invalid_request", _describe(e.errors())) from e
        answer_id, asset_id = body.get("answer_id"), body.get("asset_id")
        if not all(v is None or isinstance(v, str) for v in (answer_id, asset_id)):
            raise ApiError(422, "invalid_request", "answer_id and asset_id must be strings")
        d = wo_call(user, "create", None, lambda: deps.work_orders.create(
            user.identity(), answer_id, suggestion, asset_id=asset_id, **edits))
        return JSONResponse(d.model_dump(mode="json"), status_code=201)

    @app.get("/api/work-orders")
    def list_drafts(user: Authed, mine: bool = False):
        """Drafts visible to the user, or only their own with `mine`."""
        return [d.model_dump(mode="json")
                for d in deps.work_orders.list_visible(user.identity(), mine=mine)]

    @app.get("/api/work-orders/{draft_id}")
    def get_draft(user: Authed, draft_id: str):
        """One draft, if visible to the user."""
        return wo_call(user, "get", draft_id, lambda: deps.work_orders.get(
            user.identity(), draft_id)).model_dump(mode="json")

    @app.patch("/api/work-orders/{draft_id}")
    def edit_draft(user: Authed, draft_id: str, body: Annotated[dict, Body()]):
        """Change editable fields of the user's draft."""
        if bad := set(body) - EDITABLE:
            raise ApiError(422, "invalid_request", f"not editable: {', '.join(sorted(bad))}")
        if not body:
            raise ApiError(422, "invalid_request", "no changes")
        try:
            changes = _edits(body)
        except ValidationError as e:
            raise ApiError(422, "invalid_request", _describe(e.errors())) from e
        return wo_call(user, "edit", draft_id, lambda: deps.work_orders.edit(
            user.identity(), draft_id, changes)).model_dump(mode="json")

    @app.post("/api/work-orders/{draft_id}/request-approval")
    def request_approval(user: Authed, draft_id: str):
        """Send the user's draft to a lead for approval."""
        return wo_call(user, "request-approval", draft_id, lambda: deps.work_orders
                       .request_approval(user.identity(), draft_id)).model_dump(mode="json")

    def decide(user: User, draft_id: str, body: dict | None, approve: bool):
        """Approve or reject a draft with the body's optional `note`."""
        note = (body or {}).get("note")
        if note is not None and not isinstance(note, str):
            raise ApiError(422, "invalid_request", "note must be a string")
        fn = deps.work_orders.approve if approve else deps.work_orders.reject
        return wo_call(user, "approve" if approve else "reject", draft_id,
                       lambda: fn(user.identity(), draft_id, note or None)
                       ).model_dump(mode="json")

    @app.post("/api/work-orders/{draft_id}/approve")
    def approve(user: Authed, draft_id: str, body: Annotated[dict | None, Body()] = None):
        """Approve a draft awaiting the user's approval."""
        return decide(user, draft_id, body, True)

    @app.post("/api/work-orders/{draft_id}/reject")
    def reject(user: Authed, draft_id: str, body: Annotated[dict | None, Body()] = None):
        """Reject a draft awaiting the user's approval."""
        return decide(user, draft_id, body, False)

    @app.post("/api/work-orders/{draft_id}/submit")
    def submit(user: Authed, draft_id: str, body: Annotated[dict | None, Body()] = None,
               idempotency_key: Annotated[str | None, Header()] = None):
        """Submit a draft to its work order system; needs confirm true and an Idempotency-Key."""
        if (body or {}).get("confirm") is not True:
            raise ApiError(422, "invalid_request", "confirm must be true")
        if not idempotency_key or not idempotency_key.strip():
            raise ApiError(422, "invalid_request", "Idempotency-Key header is required")
        return wo_call(user, "submit", draft_id, lambda: deps.work_orders.submit(
            user.identity(), draft_id, confirm=True, idempotency_key=idempotency_key.strip())
        ).model_dump(mode="json")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
    def api_not_found(rest: str):
        """Unknown /api paths, for any method, get a JSON not_found."""
        raise ApiError(404, "not_found")

    # ------------------------------------------------------------------ static files

    web = cfg.web_dir.resolve()
    files = StaticFiles()

    def static(request: Request, name: str, under: Path) -> Response:
        """A client file; 404 unless it resolves to a file of a known type inside `under`."""
        path = (web / name).resolve()
        if under not in path.parents or not path.is_file() or path.suffix not in STATIC_TYPES:
            raise ApiError(404, "not_found")
        return files.response(path, _accepts_gzip(request.headers.get("accept-encoding", "")))

    @app.get("/")
    @app.get("/index.html")
    @app.get("/sources/{rest:path}")
    @app.get("/work-orders/{rest:path}")
    def index(request: Request):
        """The client's page, also served for its own routes."""
        return static(request, "index.html", web)

    @app.get("/assets/{name:path}")
    def asset(request: Request, name: str):
        """A file of the built client."""
        return static(request, f"assets/{name}", web / "assets")

    return app


class StaticFiles:
    """Static file bodies, plain and gzipped, cached by path, size and modification time."""

    def __init__(self) -> None:
        """Start with an empty cache."""
        self._cache: dict[Path, tuple[tuple[int, int], bytes, bytes | None]] = {}
        self._lock = threading.Lock()

    def response(self, path: Path, gzip_ok: bool) -> Response:
        """The file, gzipped when `gzip_ok` and smaller; re-read whenever it changes on disk."""
        st = path.stat()
        key = (st.st_size, st.st_mtime_ns)
        with self._lock:
            cached = self._cache.get(path)
        if cached is None or cached[0] != key:
            raw = path.read_bytes()
            packed = gzip.compress(raw, mtime=0) if path.suffix in COMPRESSIBLE else None
            cached = (key, raw, packed)
            with self._lock:
                self._cache[path] = cached
        _, raw, packed = cached
        headers = {"Vary": "Accept-Encoding"}
        if gzip_ok and packed is not None and len(packed) < len(raw):
            headers["Content-Encoding"] = "gzip"
            raw = packed
        return Response(raw, media_type=STATIC_TYPES[path.suffix], headers=headers)


def _accepts_gzip(header: str) -> bool:
    """Whether an Accept-Encoding header allows gzip (or *) with a nonzero q-value."""
    for part in header.split(","):
        coding, _, params = part.strip().partition(";")
        if coding.strip().lower() in ("gzip", "*"):
            q = params.strip().removeprefix("q=").strip() if "q=" in params else "1"
            try:
                return float(q) > 0
            except ValueError:
                return False
    return False


def _identity(user: User) -> dict:
    """The session body: user ID, name and sorted groups."""
    return {"user_id": user.user_id, "name": user.name, "groups": sorted(user.groups)}


def _edits(body: dict) -> dict:
    """Draft edits with parts parsed as PartLine and the yes/no flags checked to be booleans."""
    out = dict(body)
    if "parts" in out:
        if not isinstance(out["parts"], list):
            raise ApiError(422, "invalid_request", "parts must be a list")
        out["parts"] = [PartLine.model_validate(p) for p in out["parts"]]
    for flag in ("needs_specialist", "return_visit"):
        if flag in out and not isinstance(out[flag], bool):
            raise ApiError(422, "invalid_request", f"{flag} must be true or false")
    return out


def _describe(errors) -> str:
    """Pydantic errors as one line of `field: message`, without the leading `body` in paths."""
    parts = []
    for e in errors:
        loc = ".".join(str(x) for x in e.get("loc", ()) if x != "body")
        parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
    return "; ".join(parts) or "invalid request"
