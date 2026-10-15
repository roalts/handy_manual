"""Tunable constants of the answer engine (research.md R1, R5, R9)."""
import os
from functools import lru_cache
from pathlib import Path

import yaml

from copilot_ingest.settings import CONFIG_DIR, get_settings

PROMPT_SUFFICIENCY = "answer-sufficiency-1"
PROMPT_GENERATE = "answer-generate-6"
PROMPT_REGENERATE = "answer-regenerate-4"
PROMPT_FOLLOWUP = "answer-followup-2"
PROMPT_COMPLETE = "answer-complete-1"
PROMPT_EMBED = "answer-embed"

RRF_K = 60
RETRIEVER_WEIGHTS = {"identifier": 1.5, "keyword": 1.0, "vector": 1.0}
RETRIEVE_K = 40
EVIDENCE_MAX = 16
# Cases and maintenance records outside the history list, so manuals are not crowded out.
RECORDS_MAX = 5
MODEL_BOOST = 1.5
# Passages per document in the evidence: controlled procedures and applying bulletins, email and
# chat threads, everything else.
PER_DOC_MAX_PRIMARY = 8
PER_DOC_MAX_INFORMAL = 3
PER_DOC_MAX = 5
BULLETIN_PASSAGES = 4
EVIDENCE_MAX_CHARS = 42_000
HISTORY_EVENTS_MAX = 12
REFERENCE_SCAN = 20  # top hits scanned for named controlled procedures

# US$ per 1M tokens (OpenAI standard tier, checked 2026-10-12). Keyed by model-name prefix.
PRICES = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.5": (5.00, 30.00),
    "text-embedding-3-large": (0.13, 0.0),
}

# Cosine distance up to which hidden passages sharing the question's identifiers count as "about
# this question" for abstain reason not_visible (calibrated in research.md R12).
HIDDEN_MAX_DISTANCE = 0.48

# Restricted backstop (research.md R20): scope terms of a procedure's title a how-to question must
# contain for the procedure to cover the work, and keyword hits searched for a visible passage
# naming it when the evidence doesn't.
COVER_MIN_TERMS = 2
COVER_NAMING_K = 20

# Completeness pass (research.md R19): candidates listed to the model, sentences it may add, and
# the cosine distance at or under which an added sentence is too close to content hidden from the
# user (0.25 = ingestion's step_similarity_restrict of 0.75); the first answer is then kept.
# Off until two fresh harness runs show 0 disclosures with the procedure-name filter (R19).
COMPLETE_ENABLED = os.environ.get("ANSWER_COMPLETE", "0") == "1"
COMPLETE_MAX_ITEMS = 40
COMPLETE_MAX_ADDITIONS = 6
COMPLETE_HIDDEN_DISTANCE = 0.25


def cache_dir() -> Path:
    """Answer cache directory under the data dir, created if missing."""
    path = get_settings().data_dir / "answer_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache
def identifier_patterns() -> dict:
    """Canonical identifier patterns from config/identifiers.yaml (read once)."""
    return yaml.safe_load((CONFIG_DIR / "identifiers.yaml").read_text())


def price(model: str) -> tuple[float, float]:
    """(input, output) US$ per 1M tokens by longest matching model prefix."""
    for prefix, p in sorted(PRICES.items(), key=lambda kv: -len(kv[0])):
        if model.startswith(prefix):
            return p
    return (5.00, 30.00)  # unknown model: assume the expensive one
