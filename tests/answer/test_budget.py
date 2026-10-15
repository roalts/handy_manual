"""Per-process spend cap of the hosted model client, offline (fake provider, temp cache)."""
import pytest

from copilot_answer import config
from copilot_answer import llm as llm_mod
from copilot_answer.llm import HostedLLM, Meter
from copilot_ingest.providers.base import ProviderUnavailable

MODEL = "gpt-5.4-mini-2026-03-17"  # US$0.75 per 1M input tokens


class FakeProvider:
    def complete_json(self, model, prompt, schema, prompt_version):
        return {"ok": True}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(llm_mod, "_last_usage", lambda version: (1_000_000, 0))
    monkeypatch.setattr(llm_mod, "_spent", 0.0)
    monkeypatch.setattr(llm_mod, "session_spend_usd", lambda: 1000.0)  # log total is ignored
    c = HostedLLM()
    c._provider = FakeProvider()
    return c


def _call(c, i):
    return c.complete_json(MODEL, f"prompt {i}", {}, "answer-test", "scope", Meter())


def test_cap_counts_this_process_and_is_configurable(client, monkeypatch):
    monkeypatch.setenv("ANSWER_BUDGET_USD", "1.0")
    _call(client, 1)
    _call(client, 2)  # 0.75 spent before this call: still under the cap
    assert llm_mod.process_spend_usd() == pytest.approx(1.5)
    with pytest.raises(ProviderUnavailable):
        _call(client, 3)
    assert _call(client, 1) == {"ok": True}  # cached answers are still served


@pytest.mark.parametrize("env, fresh", [(None, False), ("0", False), ("1", True)])
def test_build_engine_fresh_only_when_opted_in(monkeypatch, env, fresh):
    from copilot_answer import engine as engine_mod
    from copilot_answer import serving

    monkeypatch.setattr(serving, "PgServing", lambda: object())
    monkeypatch.setattr(engine_mod, "Engine", lambda serving, llm: llm)
    if env is None:
        monkeypatch.delenv("ANSWER_FRESH", raising=False)
    else:
        monkeypatch.setenv("ANSWER_FRESH", env)
    llm = engine_mod.build_engine()
    assert llm.fresh is fresh and llm.offline is False


def test_fresh_skips_cache_reads_but_writes(client):
    _call(client, 1)
    client._provider = None
    client.offline = True
    assert _call(client, 1) == {"ok": True}  # cached
    client.fresh = True
    with pytest.raises(ProviderUnavailable):
        _call(client, 1)


def test_default_budget(monkeypatch):
    monkeypatch.delenv("ANSWER_BUDGET_USD", raising=False)
    assert llm_mod.budget_usd() == 2.80
