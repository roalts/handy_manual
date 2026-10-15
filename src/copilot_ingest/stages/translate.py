"""English text for non-English content (research.md R11).

Passages that already carry their English version (bilingual manuals and bulletins, KT-WI-14's
NL/EN headings) are not translated. Everything else that is not English gets `text_en`; the
original stays in `text_original` for citation. Each translation must keep every number and code
of the original; failures are retried once with the strong model, and left untranslated if they
fail again.
"""
import json
import re
from collections import Counter
from dataclasses import dataclass, field

import yaml

from copilot_ingest.ids import sha256_bytes
from copilot_ingest.providers.base import ProviderUnavailable
from copilot_ingest.settings import CONFIG_DIR, get_settings
from copilot_ingest.stages.chunk import detect_lang

VERSION = "translate-1"
PROMPT = "translate-1"
BATCH = 40
BILINGUAL_EN_SHARE = 0.3  # English share of classified text above which no translation is needed

_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "source_lang", "english"],
        "properties": {"id": {"type": "integer"},
                       "source_lang": {"type": "string",
                                       "description": "ISO 639-1 code of the original"},
                       "english": {"type": "string"}}}}},
}


def _glossary() -> str:
    """The NL/DE/SV term glossary as `lang: source = english` lines for the prompt."""
    g = yaml.safe_load((CONFIG_DIR / "glossary_nl_de_sv.yaml").read_text())
    return "\n".join(f"{lang}: {src} = {en}" for lang, terms in g.items()
                     for src, en in (terms or {}).items())


def _prompt(items: list[tuple[int, str]]) -> str:
    """Translation prompt for a batch of (id, text) pairs, one JSON object per line."""
    body = "\n".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) for i, t in items)
    return (
        "Translate each text into plain English for field-service technicians. The texts are "
        "maintenance notes and service records for pumps, compressors and chillers.\n"
        "Rules:\n"
        "- Keep every number, unit, fault code, part number, asset ID, serial number, model code, "
        "date and name exactly as written.\n"
        "- Do not add, explain or drop anything. Keep abbreviations you cannot expand.\n"
        "- If a text is already English, return it unchanged.\n"
        "- Use these term translations:\n" + _glossary() + "\n\nTexts (one JSON per line):\n"
        + body)


_KEEP = re.compile(r"\d+(?:[.,]\d+)*|[A-Z]{1,4}-\d+(?:-\d+)*")
_MARKER = re.compile(r"\[\[unverified:[^\]]+\]\]")


def preserved(original: str, english: str) -> bool:
    """The translation has exactly the numbers, codes and withheld-value markers of the
    original: nothing dropped, and nothing added (a translation must never restore a value that
    OCR withheld)."""
    def keep(text):
        """Counts of numbers and codes, with decimal commas normalised to points."""
        return Counter(t.replace(",", ".") for t in _KEEP.findall(text))
    return keep(original) == keep(english) and \
        _MARKER.findall(original) == _MARKER.findall(english)


def is_bilingual(text: str) -> bool:
    """English is already present for a substantial part of the text."""
    chars = Counter()
    for line in text.splitlines():
        if len(re.findall(r"[^\W\d_]{2,}", line)) < 3:
            continue
        lang = detect_lang(line)
        if lang:
            chars[lang] += len(line)
    total = sum(chars.values())
    return total > 0 and chars["en"] / total >= BILINGUAL_EN_SHARE


@dataclass
class Translations:
    """Per-text cache in data/artifacts/_translations, keyed by text hash and prompt version."""
    path: object = None
    store: dict = field(default_factory=dict)
    stats: Counter = field(default_factory=Counter)

    @classmethod
    def load(cls) -> "Translations":
        """The cache for the current prompt version; empty if no file exists yet."""
        path = get_settings().data_dir / "artifacts" / "_translations" / f"{PROMPT}.json"
        store = json.loads(path.read_text()) if path.exists() else {}
        return cls(path=path, store=store)

    def save(self) -> None:
        """Write the cache to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.store, ensure_ascii=False, indent=0, sort_keys=True))

    def get(self, text: str) -> dict | None:
        """The cached translation, or None if missing or it fails the preservation check."""
        t = self.store.get(sha256_bytes(text.encode()))
        return t if t and preserved(text, t["en"]) else None

    def translate(self, texts: list[str], provider, fast: str, strong: str) -> None:
        """Translate uncached texts with the fast model, retry failures once with the strong one,
        and save the cache. Without a provider, only counts what stays untranslated."""
        todo = sorted({t for t in texts if t.strip() and self.get(t) is None})
        if not todo or provider is None:
            self.stats["not_translated_offline"] += len(todo) if provider is None else 0
            return
        failed = self._run(todo, provider, fast)
        if failed and strong:
            self.stats["retried_with_strong_model"] += len(failed)
            failed = self._run(failed, provider, strong)
        self.stats["failed_preservation_check"] += len(failed)
        self.save()

    def _run(self, texts: list[str], provider, model: str) -> list[str]:
        """Translate in batches into the store; return the texts that failed or were unreachable."""
        failed = []
        for start in range(0, len(texts), BATCH):
            batch = list(enumerate(texts[start:start + BATCH]))
            try:
                out = provider.complete_json(model, _prompt(batch), _SCHEMA, PROMPT)
            except ProviderUnavailable:
                failed += [t for _, t in batch]
                continue
            got = {it["id"]: it for it in out.get("items", [])}
            for i, t in batch:
                it = got.get(i)
                if it and preserved(t, it["english"]):
                    self.store[sha256_bytes(t.encode())] = {
                        "en": it["english"], "lang": it["source_lang"].lower()[:2],
                        "model": model}
                    self.stats[f"translated_with_{model}"] += 1
                else:
                    failed.append(t)
        return failed
