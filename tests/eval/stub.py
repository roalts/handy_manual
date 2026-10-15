"""A stub of the HTTP API (http-api.md) serving recorded responses, and a fake reference, so the
harness can be tested without the engine, the server or a model (006 US1 independent test).

`fixtures/eval10.json`: the orchestrator's run of the 10 golden questions (prompt
answer-generate-3, ds_0028: dataset version 28) with every cited passage as the source
endpoint returns it to the asking user.
"""
import json
import re
from copy import deepcopy
from pathlib import Path

import httpx

from copilot_eval.reference import Procedure

FIXTURE = Path(__file__).parent / "fixtures" / "eval10.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


class StubApi:
    """`responses[(user, question)]` is returned by /api/ask; `sources[user][pid]` by the source
    endpoint; a pid in `hidden[user]` gives 403, any other 404."""

    def __init__(self, fixture: dict, status: int = 200) -> None:
        self.dataset_version = fixture["dataset_version"]
        self.responses = {(c["user_id"], c["question"]): deepcopy(c["response"])
                          for c in fixture["cases"]}
        self.sources: dict[str, dict] = {}
        self.hidden: dict[str, set[str]] = {}
        for c in fixture["cases"]:
            self.sources.setdefault(c["user_id"], {}).update(deepcopy(c["sources"]))
            if c["hidden_passage"]:
                self.hidden.setdefault(c["user_id"], set()).add(c["hidden_passage"])
        self.ask_status = status
        self.asked: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        user = (re.search(r"stub_user=(\w+)", request.headers.get("cookie", "")) or [None, None])[1]
        if path == "/api/health":
            return httpx.Response(200, json={"status": "ok",
                                             "dataset_version": self.dataset_version})
        if path == "/api/session" and request.method == "POST":
            uid = json.loads(request.content)["user_id"]
            return httpx.Response(200, json={"user_id": uid, "name": uid, "groups": []},
                                  headers={"set-cookie": f"stub_user={uid}; Path=/"})
        if user is None:
            return httpx.Response(401, json={"error": "unauthenticated"})
        if path == "/api/ask":
            if self.ask_status != 200:
                return httpx.Response(self.ask_status, json={"error": "model_unavailable"})
            q = json.loads(request.content)["question"]
            self.asked.append((user, q))
            return httpx.Response(200, json=self.responses[(user, q)])
        if m := re.fullmatch(r"/api/sources/([\w]+)", path):
            pid = m.group(1)
            if pid in self.sources.get(user, {}):
                return httpx.Response(200, json=self.sources[user][pid])
            if pid in self.hidden.get(user, set()):
                return httpx.Response(403, json={"error": "not_visible"})
            return httpx.Response(404, json={"error": "not_found"})
        return httpx.Response(404, json={"error": "not_found"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class FakeReference:
    def __init__(self, fixture: dict, procedures=None, markers=None, steps=None) -> None:
        self._dataset = fixture["dataset_version"]
        self._procedures = procedures if procedures is not None else [
            Procedure("HV-PROC-07", "HV-PROC-07 VRS-110 VFD Fault Reset", "doc_hv7",
                      (frozenset({"cert-hv", "family-compressors"}),)),
            Procedure("SOP-020", "SOP-020 Chiller Leak Test", "doc_sop20",
                      (frozenset({"cert-refrigerant", "family-chillers"}),))]
        self._markers = markers if markers is not None else {"HV-PROC-07": ["ZZ-MARK-1"]}
        self._steps = steps or {}
        self._visible: dict[frozenset, dict[str, str]] = {}
        for c in fixture["cases"]:
            texts = self._visible.setdefault(frozenset(c["groups"]), {})
            for pid, b in c["sources"].items():
                texts[pid] = f"{b['title']}\n{b['text_original']}\n{b['text_en'] or ''}"

    def dataset_version(self) -> str:
        return self._dataset

    def procedures(self):
        return self._procedures

    def markers(self):
        return self._markers

    def procedure_steps(self):
        return self._steps

    def visible_texts(self, groups):
        return self._visible.get(frozenset(groups), {})


def users(fixture: dict) -> dict[str, frozenset[str]]:
    return {c["user_id"]: frozenset(c["groups"]) for c in fixture["cases"]}
