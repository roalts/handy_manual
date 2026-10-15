"""Development stand-in for the 003 answer API (specs/contracts/http-api.md).

Serves web-react/dist/ (or --web DIR) at / and canned responses under /api. Standard library only.

    uv run python web-react/dev/mock_api.py [--port 8000]

Not the real API: the session cookie is the bare user ID (unsigned), and drafts live in memory.
"""
import argparse
import copy
import gzip
import json
import re
import struct
import sys
import time
import uuid
import zlib
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web-react" / "dist"
EXAMPLES = ROOT / "specs" / "contracts" / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PAGE_IMAGES = ROOT / "data" / "page_images"

COOKIE = "copilot_session"
HIDDEN_PASSAGE = "p_0ee8e5f1561408d13db4a416"
"""Always answers 403 not_visible, to exercise that path in the viewer."""
SCAN_PASSAGE = "p_7a891cda95ff12c33c8caaa5"
SCAN_FINGERPRINT = "7e158c0800367317bb39abadf6539e6e1dc1fe502641e38100e569ff2606e6bb"
SLOW_SECONDS = 8
HV_PROC_07_GROUPS = ("cert-hv", "family-compressors")
"""Required groups of HV-PROC-07 per serving.restricted_procedures in ds_0027."""
REGION_BY_SITE = {"FRS": "NA", "TAC": "NA", "RTM": "EU", "GDN": "EU"}
TARGET_BY_REGION = {"NA": "maintpro", "EU": "servio"}
KNOWN_ASSETS = {"FRS-P-0012", "FRS-P-0031", "FRS-C-0101", "TAC-C-0142", "TAC-C-0143", "TAC-C-0150",
                "RTM-C-0121"}
"""Machines the mock accepts as a draft's asset; real ones from ds_0026 (dataset version 26)."""


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


USERS = {u["id"]: u for u in load_json(ROOT / "users.json")["users"]}
GROUPS = load_json(ROOT / "users.json")["groups"]
RESPONSES = {name: load_json(EXAMPLES / f"{name}.json")
             for name in ("answer", "restricted", "abstain", "clarify", "unverified")}
RESPONSES["oil"] = load_json(FIXTURES / "mock_oil.json")
RESPONSES["hcp200_clearance"] = load_json(FIXTURES / "mock_hcp200_clearance.json")
SOURCES = load_json(FIXTURES / "sources.json")

DRAFTS: dict[str, dict] = {}
SUBMISSIONS: dict[str, dict] = {}
"""Idempotency-Key -> draft as returned by the first submit."""


def placeholder_png(width=600, height=800) -> bytes:
    """A plain light-grey page with a darker frame; stands in for a rendered PDF page."""
    rows = []
    for y in range(height):
        edge = y < 6 or y >= height - 6
        row = bytearray([0])
        for x in range(width):
            v = 120 if edge or x < 6 or x >= width - 6 else 236
            row += bytes((v, v, v))
        rows.append(bytes(row))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


PLACEHOLDER_PNG = placeholder_png()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identity(user: dict) -> dict:
    return {"user_id": user["id"], "name": user["name"], "groups": sorted(user["groups"])}


def region_of(asset_id: str) -> str:
    return REGION_BY_SITE.get(asset_id.split("-")[0], "NA")


ASSET_RE = re.compile(r"\b(?:FRS|TAC|RTM|GDN)-[A-Z]-\d{3,5}\b", re.I)
MODEL_RE = re.compile(r"\b(HCP|VRS|BX|NK)-(\d+)\b", re.I)
KNOWN_MODELS = {"HCP-200", "HCP-350", "HCP-500", "VRS-45", "VRS-75", "VRS-110", "BX-12", "BX-20", "NK-600"}
FOLLOW_UP_RE = re.compile(r"^\s*(oh|and|also|what about|how about|i meant|sorry)\b", re.I)


def one_digit_off(a: str, b: str) -> bool:
    """A digit added, dropped or changed."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def did_you_mean(question: str) -> dict | None:
    """Clarify with corrected names when the question names an unknown model close to a known one."""
    for m in MODEL_RE.finditer(question):
        name = f"{m.group(1).upper()}-{m.group(2)}"
        if name in KNOWN_MODELS:
            continue
        close = sorted(k for k in KNOWN_MODELS
                       if k.split("-")[0] == m.group(1).upper() and one_digit_off(k.split("-")[1], m.group(2)))
        if not close:
            r = copy.deepcopy(RESPONSES["abstain"])
            r.update(answer_id="ans_mock_unknown_model", question_used=None)
            r["notices"] = [{"kind": "no_answer", "text": f"{name} isn't in the documents or the fleet records.",
                             "citations": []}]
            return r
        r = copy.deepcopy(RESPONSES["clarify"])
        r["answer_id"] = "ans_mock_did_you_mean"
        r["clarification"] = {
            "question": f"Did you mean {' or '.join(close)}?",
            "options": [{"asset_id": None, "label": k,
                         "question": question[:m.start()] + k + question[m.end():]} for k in close]}
        return r
    return None


def standalone(question: str, previous: dict | None) -> tuple[str, str | None]:
    """Mock follow-up rewrite: (question to answer, carried asset ID)."""
    if not previous or not FOLLOW_UP_RE.search(question):
        return question, None
    before = previous["question"]
    named_asset = ASSET_RE.search(question)
    named_model = MODEL_RE.search(question)
    if named_asset and ASSET_RE.search(before):
        rewritten = ASSET_RE.sub(named_asset.group(0).upper(), before, count=1)
    elif named_model and MODEL_RE.search(before):
        rewritten = MODEL_RE.sub(named_model.group(0).upper(), before, count=1)
    else:
        rest = FOLLOW_UP_RE.sub("", question).strip(" ,?.") or question
        rewritten = f"{before.rstrip(' ?.')}: {rest}?"
    carried = None if named_asset else previous.get("asset_id")
    return rewritten, carried


def answer_ask(user: dict, body: dict) -> dict:
    used, carried = standalone(body["question"], body.get("previous"))
    route = used if not carried or carried.lower() in used.lower() else f"{used} ({carried})"
    r = did_you_mean(used) or choose_response(user, {**body, "question": route})
    named = ASSET_RE.search(used)
    if named and r.get("asset") and r["asset"]["asset_id"] != named.group(0).upper():
        r = no_canned_answer(named.group(0).upper())
    r["question_used"] = used if used != body["question"] else None
    return r


def no_canned_answer(asset_id: str) -> dict:
    r = copy.deepcopy(RESPONSES["abstain"])
    r["answer_id"] = "ans_mock_no_canned"
    r["notices"] = [{"kind": "no_answer",
                     "text": f"The mock API has no canned answer for {asset_id}.", "citations": []}]
    return r


def choose_response(user: dict, body: dict) -> dict:
    q = body["question"].lower()
    asset_id = body.get("asset_id") if body.get("clarification_of") else None
    if asset_id:
        if asset_id == "FRS-P-0031":
            return copy.deepcopy(RESPONSES["answer"])
        return no_canned_answer(asset_id)
    if "e-31" in q:
        r = copy.deepcopy(RESPONSES["restricted"])
        missing = [g for g in HV_PROC_07_GROUPS if g not in user["groups"]]
        if missing:
            r["restricted"]["missing_groups"] = missing
            if not re.search(r"\btac-c-\d{4}\b", q):
                # Model-level question: no machine resolved, so the suggestion has no asset.
                r.update(answer_id="ans_mock_e31_no_asset", asset=None)
                r["work_order_suggestion"]["asset_id"] = None
                r["work_order_suggestion"]["summary"] = "E-31 VFD overcurrent trip on a VRS-110, needs reset under HV-PROC-07"
            return r
        r.update(answer_id="ans_mock_e31_certified", status="answer", restricted=None,
                 work_order_suggestion=None)
        r["sentences"] = [r["sentences"][0], {
            "kind": "statement", "step_number": None,
            "segments": [{"kind": "text", "text": "The reset is done under HV-PROC-07, which you can open "
                          "on SharePoint with your HV certification.", "review_item_id": None,
                          "page": None, "page_image_passage_id": None}],
            "citations": ["p_f305f74b3d432a456bfd9221"]}]
        return r
    if "bx-20" in q:
        return copy.deepcopy(RESPONSES["abstain"])
    if "hcp-200" in q and "clearance" in q:
        return copy.deepcopy(RESPONSES["hcp200_clearance"])
    if "hcp-200" in q:
        return copy.deepcopy(RESPONSES["unverified"])
    if "oil" in q or "vrs-75" in q:
        return copy.deepcopy(RESPONSES["oil"])
    if "fresno" in q and not re.search(r"\bfrs-p-\d{4}\b", q):
        return copy.deepcopy(RESPONSES["clarify"])
    return copy.deepcopy(RESPONSES["answer"])


def approval_reasons(d: dict) -> list[str]:
    reasons = []
    if d["parts"]:
        reasons.append("parts")
    if d["required_certification"]:
        reasons.append("certification")
    if d["campaign_code"]:
        reasons.append("campaign")
    if d["needs_specialist"]:
        reasons.append("specialist")
    if d["return_visit"]:
        reasons.append("return visit")
    if reasons and not eligible_approvers(d):
        reasons.append("no eligible approver")
    return reasons


def refresh_approval(d: dict) -> None:
    d["approval_reasons"] = approval_reasons(d)
    d["eligible_approvers"] = eligible_approvers(d) if d["approval_reasons"] and \
        "no eligible approver" not in d["approval_reasons"] else []


def eligible_approvers(d: dict) -> list[str]:
    region = "region-" + region_of(d["asset_id"]).lower()
    return [u["id"] for u in USERS.values()
            if "role-lead" in u["groups"] and region in u["groups"] and u["id"] != d["created_by"]]


def can_view_draft(user: dict, d: dict) -> bool:
    return d["created_by"] == user["id"] or user["id"] in eligible_approvers(d)


CREATE_EDITS = {"summary", "work_steps", "priority", "fault_code", "parts"}
EDITABLE = CREATE_EDITS | {"needs_specialist", "return_visit"}


def validate_edits(body: dict) -> str | None:
    for key in body:
        if key not in EDITABLE:
            return f"{key} is not editable"
    for key in ("needs_specialist", "return_visit"):
        if key in body and not isinstance(body[key], bool):
            return f"{key} must be true or false"
    if "summary" in body and not str(body["summary"]).strip():
        return "summary must not be empty"
    if "priority" in body and body["priority"] not in ("low", "medium", "high"):
        return "priority must be low, medium or high"
    if "parts" in body:
        parts = body["parts"]
        if not isinstance(parts, list) or not all(
                isinstance(p, dict) and p.get("part_number") and isinstance(p.get("quantity", 1), int)
                and p.get("quantity", 1) >= 1 for p in parts):
            return "parts must be a list of {part_number, quantity >= 1}"
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "CopilotMock/1"

    # ---------- plumbing ----------
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, fmt % args))

    def send_json(self, status: int, payload=None, headers: dict | None = None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def error(self, status: int, code: str, detail: str | None = None):
        payload = {"error": code}
        if detail:
            payload["detail"] = detail
        self.send_json(status, payload)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def current_user(self) -> dict | None:
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        morsel = cookie.get(COOKIE)
        return USERS.get(morsel.value) if morsel else None

    # ---------- routing ----------
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method: str):
        url = urlparse(self.path)
        path = url.path
        if not path.startswith("/api/"):
            if method != "GET":
                return self.error(404, "not_found")
            return self.serve_static(path)
        try:
            self.route_api(method, path, parse_qs(url.query))
        except BrokenPipeError:
            pass

    def route_api(self, method, path, query):
        if path == "/api/health" and method == "GET":
            return self.send_json(200, {"status": "ok", "dataset_version": "ds_0026"})
        if path == "/api/dev/users" and method == "GET":
            return self.send_json(200, {"users": [{"user_id": u["id"], "name": u["name"], "title": u["title"],
                                                   "groups": u["groups"]} for u in USERS.values()]})
        if path == "/api/session":
            return self.session(method)

        user = self.current_user()
        if not user:
            return self.error(401, "unauthenticated")

        if path == "/api/groups" and method == "GET":
            return self.send_json(200, GROUPS)
        if path == "/api/ask" and method == "POST":
            return self.ask(user)
        m = re.fullmatch(r"/api/sources/([\w-]+)(/page\.png)?", path)
        if m and method == "GET":
            return self.source(m.group(1), bool(m.group(2)))
        if path == "/api/work-orders":
            if method == "POST":
                return self.create_draft(user)
            if method == "GET":
                mine = query.get("mine", ["false"])[0] == "true"
                drafts = [d for d in DRAFTS.values() if can_view_draft(user, d)
                          and (not mine or d["created_by"] == user["id"])]
                return self.send_json(200, drafts)
        m = re.fullmatch(r"/api/work-orders/([\w-]+)(?:/(request-approval|approve|reject|submit))?", path)
        if m:
            return self.draft_action(user, method, m.group(1), m.group(2))
        return self.error(404, "not_found")

    # ---------- sessions ----------
    def session(self, method):
        if method == "POST":
            body = self.read_body()
            user = USERS.get((body or {}).get("user_id", ""))
            if not user:
                return self.error(422, "invalid_request", "unknown user_id")
            return self.send_json(200, identity(user), {
                "Set-Cookie": f"{COOKIE}={user['id']}; Path=/; HttpOnly; SameSite=Lax"})
        if method == "GET":
            user = self.current_user()
            return self.send_json(200, identity(user)) if user else self.error(401, "unauthenticated")
        if method == "DELETE":
            return self.send_json(204, None, {"Set-Cookie": f"{COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"})
        return self.error(404, "not_found")

    # ---------- ask ----------
    def ask(self, user):
        body = self.read_body()
        question = (body or {}).get("question")
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            return self.error(422, "invalid_request", "question must be 1 to 2000 characters")
        q = question.lower()
        if "slow" in q:
            time.sleep(SLOW_SECONDS)
        if "fail" in q:
            return self.error(503, "model_unavailable")
        prev = body.get("previous")
        if prev is not None and not (isinstance(prev, dict) and isinstance(prev.get("answer_id"), str)
                                     and isinstance(prev.get("question"), str) and prev["question"].strip()
                                     and set(prev) <= {"answer_id", "question", "asset_id"}):
            return self.error(422, "invalid_request", "previous must be {answer_id, question, asset_id}")
        if bad := set(body) - {"question", "asset_id", "clarification_of", "previous"}:
            return self.error(422, "invalid_request", f"unknown fields: {', '.join(sorted(bad))}")
        return self.send_json(200, answer_ask(user, body))

    # ---------- sources ----------
    def source(self, passage_id, want_png):
        if passage_id == HIDDEN_PASSAGE:
            return self.error(403, "not_visible")
        src = SOURCES.get(passage_id)
        if not src:
            return self.error(404, "not_found")
        if not want_png:
            return self.send_json(200, src)
        if not src["page_image_url"]:
            return self.error(404, "not_found", "no page image")
        data = PLACEHOLDER_PNG
        if passage_id == SCAN_PASSAGE:
            candidate = PAGE_IMAGES / SCAN_FINGERPRINT / f"page-{src['page']}.png"
            if candidate.is_file():
                data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- work orders ----------
    def create_draft(self, user):
        body = self.read_body()
        sug = (body or {}).get("suggestion")
        if not isinstance(sug, dict) or not sug.get("summary"):
            return self.error(422, "invalid_request", "suggestion with a summary is required")
        if bad := set(body) - {"answer_id", "suggestion", "asset_id"} - CREATE_EDITS:
            return self.error(422, "invalid_request", f"unknown fields: {', '.join(sorted(bad))}")
        edits = {k: v for k, v in body.items() if k in CREATE_EDITS}
        if problem := validate_edits(edits):
            return self.error(422, "invalid_request", problem)
        given = body.get("asset_id")
        if given is not None and not isinstance(given, str):
            return self.error(422, "invalid_request", "asset_id must be a string")
        if sug.get("asset_id") and given and sug["asset_id"] != given:
            return self.error(422, "invalid_request", f"the suggestion is for {sug['asset_id']}, not {given}")
        chosen = sug.get("asset_id") or given
        if not chosen:
            return self.error(422, "invalid_request", "asset_id is required: choose the machine for this work order")
        if chosen not in KNOWN_ASSETS:
            return self.error(422, "invalid_request", f"unknown asset {chosen}")
        d = {
            "draft_id": "wo_" + uuid.uuid4().hex[:12],
            "created_by": user["id"],
            "created_at": now_iso(),
            "answer_id": body.get("answer_id"),
            "asset_id": chosen,
            "target_system": TARGET_BY_REGION[region_of(chosen)],
            "fault_code": sug.get("fault_code"),
            "summary": sug["summary"],
            "work_steps": "",
            "required_certification": list(sug.get("required_certification") or []),
            "parts": list(sug.get("parts") or []),
            "campaign_code": sug.get("campaign_code"),
            "priority": "medium",
            "needs_specialist": False,
            "return_visit": False,
            "citations": list(sug.get("citations") or []),
            "status": "draft",
            "approval_reasons": [],
            "eligible_approvers": [],
            "decided_by": None,
            "decided_at": None,
            "decision_note": None,
            "idempotency_key": str(uuid.uuid4()),
            "external_ref": None,
        }
        d.update(edits)
        refresh_approval(d)
        DRAFTS[d["draft_id"]] = d
        return self.send_json(201, d)

    def draft_action(self, user, method, draft_id, action):
        d = DRAFTS.get(draft_id)
        if not d:
            return self.error(404, "not_found")
        if not can_view_draft(user, d):
            return self.error(403, "not_visible")
        if action is None and method == "GET":
            return self.send_json(200, d)
        body = self.read_body()
        if body is None:
            return self.error(422, "invalid_request", "body must be a JSON object")
        if action is None and method == "PATCH":
            if d["created_by"] != user["id"]:
                return self.error(403, "forbidden")
            if d["status"] not in ("draft", "rejected"):
                return self.error(409, "not_editable")
            if problem := validate_edits(body):
                return self.error(422, "invalid_request", problem)
            d.update(body)
            d["status"] = "draft"
            refresh_approval(d)
            return self.send_json(200, d)
        if method != "POST":
            return self.error(404, "not_found")
        if action == "request-approval":
            if d["created_by"] != user["id"] or d["status"] != "draft":
                return self.error(409, "invalid_state")
            if not d["approval_reasons"] or "no eligible approver" in d["approval_reasons"]:
                return self.error(409, "invalid_state", "; ".join(d["approval_reasons"]) or "no approval needed")
            d["status"] = "pending_approval"
            return self.send_json(200, d)
        if action in ("approve", "reject"):
            if user["id"] not in eligible_approvers(d):
                return self.error(403, "forbidden")
            if d["status"] != "pending_approval":
                return self.error(409, "invalid_state")
            d.update(status="approved" if action == "approve" else "rejected",
                     decided_by=user["id"], decided_at=now_iso(), decision_note=(body.get("note") or None))
            return self.send_json(200, d)
        if action == "submit":
            key = self.headers.get("Idempotency-Key")
            if not key:
                return self.error(422, "invalid_request", "Idempotency-Key header is required")
            if key in SUBMISSIONS:
                return self.send_json(200, SUBMISSIONS[key])
            if body.get("confirm") is not True:
                return self.error(422, "invalid_request", "confirm must be true")
            if d["created_by"] != user["id"]:
                return self.error(403, "forbidden")
            ready = d["status"] == "approved" or (d["status"] == "draft" and not d["approval_reasons"])
            if not ready:
                return self.error(409, "invalid_state", "approval needed before submit")
            prefix = "MP" if d["target_system"] == "maintpro" else "SV"
            d.update(status="submitted", external_ref=f"{prefix}-{uuid.uuid4().int % 10**7:07d}")
            SUBMISSIONS[key] = copy.deepcopy(d)
            return self.send_json(200, d)
        return self.error(404, "not_found")

    # ---------- static ----------
    def serve_static(self, path):
        if path == "/" or path.startswith("/sources/") or path.startswith("/work-orders/"):
            path = "/index.html"
        web = self.server.web_dir
        target = (web / path.lstrip("/")).resolve()
        hidden = (web / "dev", web / "tests")
        if web not in target.parents or any(h in target.parents for h in hidden) or not target.is_file():
            return self.error(404, "not_found")
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".json": "application/json", ".mjs": "text/javascript; charset=utf-8",
                 ".woff2": "font/woff2", ".webp": "image/webp", ".ico": "image/x-icon"}
        data = target.read_bytes()
        compress = target.suffix in (".html", ".js", ".mjs", ".css", ".svg", ".json")
        gzip_ok = compress and re.search(r"\bgzip\b", self.headers.get("Accept-Encoding", ""))
        if gzip_ok:
            data = gzip.compress(data, compresslevel=6, mtime=0)
        self.send_response(200)
        self.send_header("Content-Type", types.get(target.suffix, "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        if compress:
            self.send_header("Vary", "Accept-Encoding")
        if gzip_ok:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_server(port: int, web: Path = WEB) -> ThreadingHTTPServer:
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.web_dir = Path(web).resolve()
    return server


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--web", type=Path, default=WEB, help="client directory to serve at / (default web-react/dist/)")
    args = ap.parse_args()
    if not (args.web / "index.html").is_file():
        ap.error(f"{args.web} has no index.html")
    server = make_server(args.port, args.web)
    print(f"Mock API on http://localhost:{args.port}/  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
