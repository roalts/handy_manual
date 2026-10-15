"""Close known names for a model or asset ID that doesn't exist (answer.md "Unknown model or
asset"). Pure code: no model calls."""
import re

from copilot_answer.ids import ASSET, MODEL


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _split(model: str) -> tuple[str, str]:
    """(family, number) of a model name."""
    family, _, number = model.partition("-")
    return family, number


def close_models(name: str, known: set[str]) -> list[str]:
    """Same family with a digit added, dropped or changed; or one character off overall."""
    family, number = _split(name)
    out = []
    for k in known:
        kf, kn = _split(k)
        if (kf == family and edit_distance(number, kn) == 1) or edit_distance(name, k) == 1:
            out.append(k)
    return sorted(out)


def close_assets(asset_id: str, known: set[str]) -> list[str]:
    """Known asset IDs one edit away."""
    return sorted(k for k in known if edit_distance(asset_id, k) == 1)


def _canonical_model(m: re.Match) -> str:
    """Canonical model name of a `MODEL` match."""
    return f"{m.group(1).upper()}-{m.group(2)}"


def _canonical_asset(m: re.Match) -> str:
    """Canonical asset ID of an `ASSET` match."""
    return f"{m.group(1).upper()}-{m.group(2).upper()}-{m.group(3)}"


def replace_name(text: str, name: str, replacement: str) -> str:
    """`text` with every spelling of the model or asset ID `name` replaced."""
    for pattern, canon in ((MODEL, _canonical_model), (ASSET, _canonical_asset)):
        text = pattern.sub(lambda m, c=canon: replacement if c(m) == name else m.group(0), text)
    return text


def ask_text(names: list[str]) -> str:
    """The clarifying question listing the names ("Did you mean A or B?")."""
    return "Did you mean " + (names[0] if len(names) == 1 else
                              ", ".join(names[:-1]) + " or " + names[-1]) + "?"
