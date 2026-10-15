"""End-to-end checks of the mock API over HTTP. Standard library only.

    uv run python -m unittest web-react/dev/test_mock_api.py
"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_api  # noqa: E402

mock_api.SLOW_SECONDS = 0.2

try:  # the contract types are importable under `uv run`; plain python skips type validation
    from copilot_contracts.work_orders import WorkOrderDraft
except ImportError:
    WorkOrderDraft = None

ERROR_CODES = {"unauthenticated", "not_visible", "forbidden", "not_found", "invalid_request",
               "invalid_state", "not_editable", "model_unavailable"}


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with self.opener.open(req) as res:
                raw = res.read()
                return res.status, res.headers, raw
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def json(self, method, path, body=None, headers=None):
        status, _, raw = self.call(method, path, body, headers)
        data = json.loads(raw) if raw else None
        if status >= 400:
            assert set(data) <= {"error", "detail"} and data["error"] in ERROR_CODES, data
        elif WorkOrderDraft and (path.startswith("/api/work-orders/") or (path == "/api/work-orders" and method == "POST")):
            WorkOrderDraft.model_validate(data)
        return status, data


class MockApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory()
        web = Path(cls.tmp.name)
        (web / "assets").mkdir()
        (web / "dev").mkdir()
        (web / "index.html").write_text('<!doctype html><html><body><div id="root"></div></body></html>')
        (web / "assets" / "app.js").write_text("export const app = 1;\n" * 100)
        (web / "dev" / "mock_api.py").write_text("hidden")
        cls.server = mock_api.make_server(0, web)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()
        cls.server.server_close()

    def signed_in(self, user_id):
        c = Client(self.base)
        status, ident = c.json("POST", "/api/session", {"user_id": user_id})
        self.assertEqual(status, 200)
        self.assertEqual(ident["user_id"], user_id)
        return c

    def ask(self, c, question, **extra):
        body = {"question": question, **extra}
        status, resp = c.json("POST", "/api/ask", body)
        try:
            from copilot_contracts.answer import AskRequest
        except ImportError:
            return status, resp
        try:
            AskRequest.model_validate(body)
            contract_ok = bool(question.strip())
        except ValueError:
            contract_ok = False
        if status != 401:
            self.assertEqual(status != 422, contract_ok, f"mock and AskRequest disagree on {body}")
        return status, resp

    def test_static_and_health(self):
        c = Client(self.base)
        status, headers, raw = c.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'<div id="root"', raw)
        self.assertEqual(c.call("GET", "/sources/p_x")[0], 200)
        self.assertEqual(c.call("GET", "/assets/app.js")[1]["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(c.call("GET", "/dev/mock_api.py")[0], 404)
        self.assertEqual(c.call("GET", "/../users.json")[0], 404)
        self.assertEqual(c.json("GET", "/api/health")[1]["status"], "ok")
        self.assertEqual(c.call("GET", "/tests/text.test.mjs")[0], 404)

    def test_static_gzip_when_accepted(self):
        import gzip
        c = Client(self.base)
        _, plain_headers, plain = c.call("GET", "/assets/app.js")
        self.assertIsNone(plain_headers["Content-Encoding"])
        status, headers, raw = c.call("GET", "/assets/app.js", headers={"Accept-Encoding": "gzip, deflate, br"})
        self.assertEqual((status, headers["Content-Encoding"], headers["Vary"]), (200, "gzip", "Accept-Encoding"))
        self.assertEqual(gzip.decompress(raw), plain)
        self.assertEqual(int(headers["Content-Length"]), len(raw))
        self.assertIsNone(c.call("GET", "/icon.svg" if (mock_api.WEB / "icon.svg").exists() else "/",
                                 headers={"Accept-Encoding": "identity"})[1]["Content-Encoding"])

    def test_serves_another_web_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp)
            (web / "assets").mkdir()
            (web / "index.html").write_text('<div id="root"></div>')
            (web / "assets" / "index-abc123.js").write_text("export {}")
            (web / "assets" / "index-abc123.css").write_text("body{}")
            (web / "dev").mkdir()
            (web / "dev" / "secret.txt").write_text("x")
            server = mock_api.make_server(0, web)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                c = Client(f"http://127.0.0.1:{server.server_address[1]}")
                for path in ("/", "/sources/p_x", "/work-orders/wo_1"):
                    status, _, raw = c.call("GET", path)
                    self.assertEqual((status, raw), (200, b'<div id="root"></div>'), path)
                self.assertEqual(c.call("GET", "/assets/index-abc123.js")[1]["Content-Type"], "text/javascript; charset=utf-8")
                self.assertEqual(c.call("GET", "/assets/index-abc123.css")[1]["Content-Type"], "text/css; charset=utf-8")
                self.assertEqual(c.call("GET", "/js/app.js")[0], 404)
                self.assertEqual(c.call("GET", "/dev/secret.txt")[0], 404)
                self.assertEqual(c.call("GET", "/../index.html")[0], 404)
                self.assertEqual(c.json("GET", "/api/health")[1]["status"], "ok")
            finally:
                server.shutdown()
                server.server_close()

    def test_session_lifecycle(self):
        c = Client(self.base)
        self.assertEqual(c.json("GET", "/api/session")[0], 401)
        self.assertEqual(c.json("POST", "/api/ask", {"question": "x"})[0], 401)
        self.assertEqual(c.json("POST", "/api/session", {"user_id": "nobody"})[0], 422)
        self.assertEqual(c.json("GET", "/api/groups")[0], 401)
        users = c.json("GET", "/api/dev/users")[1]
        self.assertEqual(set(users), {"users"})
        c = self.signed_in("u01")
        self.assertEqual(c.json("GET", "/api/session")[1]["name"], "Maria Okafor")
        self.assertEqual(c.json("GET", "/api/groups")[1]["cert-hv"],
                         "High-voltage electrical certification (VFD cabinets)")
        self.assertEqual(c.json("DELETE", "/api/session")[0], 204)
        self.assertEqual(c.json("GET", "/api/session")[0], 401)

    def test_api_responses_are_not_cached(self):
        c = self.signed_in("u01")
        _, headers, _ = c.call("POST", "/api/ask", {"question": "torque"})
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_ask_routing(self):
        u03, u02 = self.signed_in("u03"), self.signed_in("u02")
        self.assertEqual(self.ask(u03, "E-31 on TAC-C-0143")[1]["restricted"]["missing_groups"], ["cert-hv"])
        u01 = self.signed_in("u01")
        self.assertEqual(self.ask(u01, "E-31 on TAC-C-0143")[1]["restricted"]["missing_groups"],
                         ["cert-hv", "family-compressors"])
        certified = self.ask(u02, "E-31 on TAC-C-0143")[1]
        self.assertEqual(certified["status"], "answer")
        self.assertIsNone(certified["restricted"])
        self.assertEqual(self.ask(u03, "BX-20 warranty")[1]["status"], "abstain")
        self.assertEqual(self.ask(u03, "HCP-350 at Fresno torque")[1]["status"], "clarify")
        self.assertEqual(self.ask(u03, "HCP-200 rated head")[1]["answer_id"], "ans_example_unverified")
        self.assertEqual(self.ask(u03, "casing torque FRS-P-0031")[1]["answer_id"], "ans_example_q04")
        picked = self.ask(u03, "HCP-350 at Fresno torque", asset_id="FRS-P-0031", clarification_of="ans_example_clarify")
        self.assertEqual(picked[1]["asset"]["asset_id"], "FRS-P-0031")
        self.assertEqual(self.ask(u03, "please fail"), (503, {"error": "model_unavailable"}))
        self.assertEqual(self.ask(u03, "  ")[0], 422)
        self.assertEqual(self.ask(u03, "slow torque")[1]["status"], "answer")

    def valid_answer(self, r):
        try:
            from copilot_contracts.answer import AnswerResponse
        except ImportError:
            return r
        AnswerResponse.model_validate(r).check()
        return r

    def test_did_you_mean_then_follow_up(self):
        u01 = self.signed_in("u01")
        typo = "What's the impeller-to-casing clearance spec on an HCP-20?"
        r = self.valid_answer(self.ask(u01, typo)[1])
        self.assertEqual(r["status"], "clarify")
        self.assertEqual(r["clarification"]["question"], "Did you mean HCP-200?")
        self.assertEqual(r["clarification"]["options"], [{
            "asset_id": None, "label": "HCP-200",
            "question": "What's the impeller-to-casing clearance spec on an HCP-200?"}])
        self.assertIsNone(r["question_used"])
        prev = {"answer_id": r["answer_id"], "question": typo, "asset_id": None}
        r = self.valid_answer(self.ask(u01, "Oh, I meant HCP-200", previous=prev)[1])
        self.assertEqual(r["question_used"], "What's the impeller-to-casing clearance spec on an HCP-200?")
        self.assertEqual(r["answer_id"], "ans_mock_hcp200_clearance")
        self.assertIn("0.38 - 0.50 mm", r["sentences"][0]["segments"][0]["text"])

    def test_unknown_model_without_close_match_abstains(self):
        r = self.valid_answer(self.ask(self.signed_in("u01"), "Seal kit for the HCP-9?")[1])
        self.assertEqual((r["status"], r["abstain_reason"]), ("abstain", "no_permitted_source"))
        self.assertIn("HCP-9 isn't in the documents", r["notices"][0]["text"])
        self.assertEqual(r["notices"][0]["kind"], "no_answer")
        r = self.ask(self.signed_in("u01"), "Warranty on the BX-20 conveyor")[1]
        self.assertEqual([n["kind"] for n in r["notices"]], ["no_answer"])

    def test_follow_up_new_topic_switch_machine_and_restricted(self):
        u03 = self.signed_in("u03")
        q04 = {"answer_id": "ans_example_q04", "question": "Casing bolt torque for FRS-P-0031", "asset_id": "FRS-P-0031"}
        r = self.ask(u03, "Warranty on the BX-20 conveyor", previous=q04)[1]
        self.assertEqual((r["status"], r["question_used"]), ("abstain", None))
        r = self.ask(u03, "and on FRS-P-0012?", previous=q04)[1]
        self.assertEqual(r["question_used"], "Casing bolt torque for FRS-P-0012")
        self.assertNotEqual((r.get("asset") or {}).get("asset_id"), "FRS-P-0031")
        e31 = {"answer_id": "ans_example_q06", "question": "E-31 on TAC-C-0143, how do I reset it?", "asset_id": "TAC-C-0143"}
        r = self.valid_answer(self.ask(u03, "and how long does it take?", previous=e31)[1])
        self.assertEqual((r["status"], r["restricted"]["procedure"]), ("restricted", "HV-PROC-07"))
        self.assertIn("how long does it take", r["question_used"])
        carried = {**e31, "question": "Why does E-31 trip?"}
        r = self.ask(u03, "and the reset?", previous=carried)[1]
        self.assertEqual((r["status"], r["asset"]["asset_id"]), ("restricted", "TAC-C-0143"))

    def test_previous_is_validated(self):
        u01 = self.signed_in("u01")
        self.assertEqual(self.ask(u01, "and?", previous={"answer_id": "a", "question": ""})[0], 422)
        self.assertEqual(self.ask(u01, "and?", previous={"answer_id": "a", "question": "q", "groups": ["cert-hv"]})[0], 422)
        self.assertEqual(self.ask(u01, "x", user_id="u02")[0], 422)

    def test_sources(self):
        c = self.signed_in("u01")
        for name in ("answer", "restricted", "unverified"):
            for pid in mock_api.RESPONSES[name]["citations"]:
                status, src = c.json("GET", f"/api/sources/{pid}")
                self.assertEqual(status, 200, pid)
                self.assertTrue(src["text_original"])
        self.assertEqual(c.json("GET", f"/api/sources/{mock_api.HIDDEN_PASSAGE}"), (403, {"error": "not_visible"}))
        self.assertEqual(c.json("GET", "/api/sources/p_does_not_exist")[0], 404)
        scan = c.json("GET", f"/api/sources/{mock_api.SCAN_PASSAGE}")[1]
        self.assertIn("[[unverified:", scan["text_original"])
        self.assertNotIn("45 m", scan["text_original"] + scan["text_en"])
        status, headers, png = c.call("GET", scan["page_image_url"])
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertTrue(png.startswith(b"\x89PNG"))
        no_image = c.json("GET", "/api/sources/p_01d8fc970b80aa01db626b23")[1]
        self.assertEqual((no_image["page"], no_image["page_image_url"]), (3, None))

    def test_work_order_approval_flow(self):
        u03, u08 = self.signed_in("u03"), self.signed_in("u08")
        sug = mock_api.RESPONSES["restricted"]["work_order_suggestion"]
        status, d = u03.json("POST", "/api/work-orders", {"answer_id": "ans_example_q06", "suggestion": sug})
        self.assertEqual(status, 201)
        self.assertEqual((d["target_system"], d["status"], d["approval_reasons"]), ("maintpro", "draft", ["certification"]))
        self.assertEqual(d["eligible_approvers"], ["u08"])
        self.assertEqual(u03.json("PATCH", f"/api/work-orders/{d['draft_id']}", {"asset_id": "x"}),
                         (422, {"error": "invalid_request", "detail": "asset_id is not editable"}))
        did = d["draft_id"]
        status, d = u03.json("PATCH", f"/api/work-orders/{did}", {"summary": "E-31 trip, reset needed under HV-PROC-07"})
        self.assertEqual((status, d["summary"]), (200, "E-31 trip, reset needed under HV-PROC-07"))
        key = {"Idempotency-Key": d["idempotency_key"]}
        self.assertEqual(u03.json("POST", f"/api/work-orders/{did}/submit", {"confirm": True}, key)[0], 409)
        self.assertEqual(u03.json("POST", f"/api/work-orders/{did}/request-approval", {})[1]["status"], "pending_approval")
        self.assertEqual(u03.json("POST", f"/api/work-orders/{did}/approve", {"note": ""})[0], 403)
        self.assertEqual(self.signed_in("u07").json("GET", f"/api/work-orders/{did}")[0], 403)
        approved = u08.json("POST", f"/api/work-orders/{did}/approve", {"note": "ok, book Daniel"})[1]
        self.assertEqual((approved["status"], approved["decided_by"], approved["decision_note"]),
                         ("approved", "u08", "ok, book Daniel"))
        self.assertEqual(u03.json("POST", f"/api/work-orders/{did}/submit", {}, key)[0], 422)
        status, first = u03.json("POST", f"/api/work-orders/{did}/submit", {"confirm": True}, key)
        self.assertEqual((status, first["status"]), (200, "submitted"))
        self.assertTrue(first["external_ref"].startswith("MP-"))
        again = u03.json("POST", f"/api/work-orders/{did}/submit", {"confirm": True}, key)[1]
        self.assertEqual(again["external_ref"], first["external_ref"])
        self.assertEqual(u03.json("PATCH", f"/api/work-orders/{did}", {"summary": "x"}), (409, {"error": "not_editable"}))

    def test_work_order_direct_submit_to_servio(self):
        u09 = self.signed_in("u09")
        sug = mock_api.RESPONSES["oil"]["work_order_suggestion"]
        d = u09.json("POST", "/api/work-orders", {"answer_id": "ans_mock_oil", "suggestion": sug})[1]
        self.assertEqual((d["target_system"], d["approval_reasons"], d["eligible_approvers"]), ("servio", [], []))
        done = u09.json("POST", f"/api/work-orders/{d['draft_id']}/submit", {"confirm": True},
                        {"Idempotency-Key": d["idempotency_key"]})[1]
        self.assertTrue(done["external_ref"].startswith("SV-"))

    def test_draft_needs_a_machine_when_none_was_resolved(self):
        u03 = self.signed_in("u03")
        r = self.ask(u03, "How do I reset E-31 on a VRS-110?")[1]
        self.assertEqual((r["status"], r["asset"], r["work_order_suggestion"]["asset_id"]), ("restricted", None, None))
        try:
            from copilot_contracts.answer import AnswerResponse
            AnswerResponse.model_validate(r).check()
        except ImportError:
            pass
        sug = r["work_order_suggestion"]
        base = {"answer_id": r["answer_id"], "suggestion": sug}
        status, err = u03.json("POST", "/api/work-orders", base)
        self.assertEqual((status, err["error"]), (422, "invalid_request"))
        self.assertIn("asset_id is required", err["detail"])
        self.assertEqual(u03.json("POST", "/api/work-orders", {**base, "asset_id": "TAC-C-9999"}),
                         (422, {"error": "invalid_request", "detail": "unknown asset TAC-C-9999"}))
        self.assertEqual(u03.json("POST", "/api/work-orders", {**base, "asset_id": "TAC-C-0142", "citations": []})[0], 422)
        status, d = u03.json("POST", "/api/work-orders", {**base, "asset_id": "TAC-C-0142"})
        self.assertEqual((status, d["asset_id"], d["target_system"]), (201, "TAC-C-0142", "maintpro"))
        self.assertEqual((d["needs_specialist"], d["return_visit"]), (False, False))
        with_asset = mock_api.RESPONSES["restricted"]["work_order_suggestion"]
        status, err = u03.json("POST", "/api/work-orders", {"suggestion": with_asset, "asset_id": "TAC-C-0142"})
        self.assertEqual((status, err["detail"]), (422, "the suggestion is for TAC-C-0143, not TAC-C-0142"))

    def test_specialist_and_return_visit_need_approval(self):
        u09 = self.signed_in("u09")
        sug = mock_api.RESPONSES["oil"]["work_order_suggestion"]
        d = u09.json("POST", "/api/work-orders", {"answer_id": "ans_mock_oil", "suggestion": sug})[1]
        status, d = u09.json("PATCH", f"/api/work-orders/{d['draft_id']}", {"needs_specialist": True, "return_visit": True})
        self.assertEqual((status, d["approval_reasons"], d["eligible_approvers"]), (200, ["specialist", "return visit"], ["u07"]))
        self.assertEqual(u09.json("PATCH", f"/api/work-orders/{d['draft_id']}", {"return_visit": "yes"})[0], 422)

    def test_no_eligible_approver(self):
        u08 = self.signed_in("u08")
        sug = mock_api.RESPONSES["restricted"]["work_order_suggestion"]
        d = u08.json("POST", "/api/work-orders", {"answer_id": "ans_example_q06", "suggestion": sug})[1]
        self.assertIn("no eligible approver", d["approval_reasons"])
        self.assertEqual(d["eligible_approvers"], [])
        self.assertEqual(u08.json("POST", f"/api/work-orders/{d['draft_id']}/request-approval", {})[0], 409)


if __name__ == "__main__":
    unittest.main()
