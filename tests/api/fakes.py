"""Test doubles for the answer API: a scripted engine and a sources store without a database."""
import json
from pathlib import Path

from copilot_api.sources import SourceResult
from copilot_contracts import AnswerResponse, AskRequest, Identity

EXAMPLES = Path(__file__).resolve().parents[2] / "specs" / "contracts" / "examples"


def example(name: str) -> AnswerResponse:
    resp = AnswerResponse.model_validate(json.loads((EXAMPLES / f"{name}.json").read_text()))
    resp.check()
    return resp


class FakeEngine:
    """Records every call; returns a fixed response or raises a fixed error."""

    def __init__(self, response: AnswerResponse | None = None,
                 error: Exception | None = None) -> None:
        self.response = response or example("answer")
        self.error = error
        self.calls: list[tuple[Identity, AskRequest]] = []

    def answer(self, identity: Identity, request: AskRequest) -> AnswerResponse:
        self.calls.append((identity, request))
        if self.error:
            raise self.error
        return self.response


class FakeSources:
    """Everything visible except `hidden`; no source views or images."""

    def __init__(self, hidden: set[str] | None = None) -> None:
        self.hidden = hidden or set()

    def dataset_version(self) -> str:
        return "ds_test"

    def visible(self, groups, ids) -> set[str]:
        return set(ids) - self.hidden

    def source(self, groups, passage_id) -> SourceResult:
        return SourceResult("not_found", "ds_test")

    def render(self, ref):
        return None
