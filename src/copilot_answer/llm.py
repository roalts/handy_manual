"""Model access for the engine: disk cache, usage logging, cost metering (research.md R9).

The cache key always includes the dataset version and the user's exact group set (FR-027), so a
cached output built from one user's evidence can never be served to a different permission set.
"""
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from copilot_answer import config
from copilot_ingest.ids import sha256_bytes
from copilot_ingest.providers.base import ProviderUnavailable
from copilot_ingest.settings import get_settings

DEFAULT_BUDGET_USD = 2.80
_spent = 0.0
_spent_lock = threading.Lock()


def budget_usd() -> float:
    """Spend cap per process (`ANSWER_BUDGET_USD`, default US$2.80)."""
    return float(os.environ.get("ANSWER_BUDGET_USD") or DEFAULT_BUDGET_USD)


def process_spend_usd() -> float:
    """Model spend of this process since it started (uncached calls only)."""
    return _spent


def _add_spend(usd: float) -> None:
    """Add to this process's spend (thread-safe)."""
    global _spent
    with _spent_lock:
        _spent += usd


@dataclass
class Call:
    prompt_version: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool
    seconds: float


@dataclass
class Meter:
    calls: list[Call] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        """Cost of the uncached calls."""
        return sum(c.cost_usd for c in self.calls if not c.cached)


class LLM(Protocol):
    def complete_json(self, model: str, prompt: str, schema: dict[str, Any],
                      prompt_version: str, scope: str, meter: Meter) -> dict[str, Any]:
        """Structured output for `prompt` matching `schema`; cached per `scope` (dataset version
        and group set)."""
        ...

    def embed(self, model: str, text: str, dims: int, meter: Meter) -> list[float]:
        """Embedding of `text` with `dims` dimensions."""
        ...


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """US$ cost of a call at the model's price per 1M tokens."""
    pin, pout = config.price(model)
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


def session_spend_usd() -> float:
    """Spend of the engine over all processes (`answer-` prompt versions in data/usage.jsonl);
    for reporting only, the cap counts `process_spend_usd`."""
    path = get_settings().data_dir / "usage.jsonl"
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if str(row.get("prompt_version", "")).startswith("answer-"):
            total += cost(row["model"], row.get("input_tokens") or 0,
                          row.get("output_tokens") or 0)
    return total


def _last_usage(prompt_version: str) -> tuple[int, int]:
    """Token counts of the latest usage.jsonl row for `prompt_version` (written by the
    provider), or zeros."""
    path = get_settings().data_dir / "usage.jsonl"
    for line in reversed(path.read_text().splitlines()):
        row = json.loads(line)
        if row.get("prompt_version") == prompt_version:
            return row.get("input_tokens") or 0, row.get("output_tokens") or 0
    return 0, 0


class HostedLLM:
    """OpenAI through the ingestion provider, behind a disk cache."""

    def __init__(self, offline: bool = False, fresh: bool = False) -> None:
        """`fresh` skips cache reads (still writes), to measure real latency and cost."""
        self.offline = offline
        self.fresh = fresh
        self._provider = None
        self._lock = threading.Lock()

    def _inner(self):
        """The OpenAI provider, created on first use; raises `ProviderUnavailable` when offline."""
        if self.offline:
            raise ProviderUnavailable("offline mode: model call not cached")
        if self._provider is None:
            from copilot_ingest.providers.openai_provider import OpenAIProvider

            self._provider = OpenAIProvider()
        return self._provider

    def _check_budget(self) -> None:
        """Raise `ProviderUnavailable` once this process has spent its budget."""
        if process_spend_usd() >= budget_usd():
            raise ProviderUnavailable("answer engine budget for this process reached")

    def complete_json(self, model, prompt, schema, prompt_version, scope, meter):
        """Cached structured output, keyed by model, prompt version, scope, prompt and schema; a
        miss calls the model and meters its usage and cost."""
        payload = json.dumps([model, prompt_version, scope, prompt, schema], sort_keys=True)
        key = sha256_bytes(payload.encode())
        path = config.cache_dir() / "calls" / f"{key}.json"
        if path.exists() and not self.fresh:
            row = json.loads(path.read_text())
            meter.calls.append(Call(prompt_version, model, row["input_tokens"],
                                    row["output_tokens"], row["cost_usd"], True, 0.0))
            return row["output"]
        inner = self._inner()
        self._check_budget()
        start = time.monotonic()
        out = inner.complete_json(model, prompt, schema, prompt_version)
        seconds = time.monotonic() - start
        with self._lock:
            tin, tout = _last_usage(prompt_version)
        c = cost(model, tin, tout)
        _add_spend(c)
        meter.calls.append(Call(prompt_version, model, tin, tout, c, False, seconds))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"model": model, "prompt_version": prompt_version,
                                    "input_tokens": tin, "output_tokens": tout,
                                    "cost_usd": c, "output": out}))
        return out

    def embed(self, model, text, dims, meter):
        """Cached embedding, keyed by model, dims and text (not by scope, and read even when
        `fresh`); a miss is metered and logged to usage.jsonl."""
        key = sha256_bytes(json.dumps([model, dims, text]).encode())
        path = config.cache_dir() / "embeddings" / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        inner = self._inner()
        self._check_budget()
        start = time.monotonic()
        vec = inner.embed(model, [text], dims)[0]
        tokens = max(1, len(text) // 4)
        c = cost(model, tokens, 0)
        _add_spend(c)
        meter.calls.append(Call(config.PROMPT_EMBED, model, tokens, 0, c, False,
                                time.monotonic() - start))
        with (get_settings().data_dir / "usage.jsonl").open("a") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model,
                                "prompt_version": config.PROMPT_EMBED, "input_tokens": tokens,
                                "output_tokens": 0, "reasoning_tokens": None}) + "\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(vec))
        return vec


class FakeLLM:
    """Test double: `handler(prompt_version, prompt) -> dict`; embeddings are fixed vectors."""

    def __init__(self, handler: Callable[[str, str], dict[str, Any]], dims: int = 1024) -> None:
        """Wrap `handler`; `prompts` records every (prompt_version, prompt) asked."""
        self.handler = handler
        self.dims = dims
        self.prompts: list[tuple[str, str]] = []

    def complete_json(self, model, prompt, schema, prompt_version, scope, meter):
        """Record the prompt and return the handler's output, metered at zero cost."""
        self.prompts.append((prompt_version, prompt))
        meter.calls.append(Call(prompt_version, model, 0, 0, 0.0, False, 0.0))
        return self.handler(prompt_version, prompt)

    def embed(self, model, text, dims, meter):
        """A zero vector of `dims` dimensions."""
        return [0.0] * dims
