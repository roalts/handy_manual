"""Resolve the machine a question is about from structured records (FR-004..006, research R2)."""
import re
from dataclasses import dataclass, field

from copilot_answer.ids import ASSET, LEGACY_ASSET, SERIAL, Recognized
from copilot_answer.serving import Asset


@dataclass
class Resolution:
    asset: Asset | None = None
    models: list[str] = field(default_factory=list)
    candidates: list[Asset] = field(default_factory=list)
    unknown: str | None = None
    """An ID-shaped token that names no asset (abstain: unknown_asset)."""
    site: str | None = None


@dataclass
class Fleet:
    assets: dict[str, Asset]
    aliases: dict[str, str]
    site_aliases: dict[str, str]

    def site_names(self) -> dict[str, str]:
        """Casefolded site alias, site name and its first word, to site code; aliases win."""
        names = {a.casefold(): s for a, s in self.site_aliases.items()}
        for a in self.assets.values():
            names.setdefault(a.site_name.casefold(), a.site)
            names.setdefault(a.site_name.split()[0].casefold(), a.site)
        return names


def find_site(question: str, fleet: Fleet) -> str | None:
    """The one site the question names (asset IDs and serials masked), else None."""
    text = SERIAL.sub(" ", LEGACY_ASSET.sub(" ", ASSET.sub(" ", question)))
    found = set()
    for name, site in sorted(fleet.site_names().items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I):
            found.add(site)
    return found.pop() if len(found) == 1 else None


def resolve(question: str, rec: Recognized, fleet: Fleet,
            asset_id: str | None = None) -> Resolution:
    """Machine from an explicit asset ID, else IDs and serials in the question, else one model
    at a named site; `unknown` is set for an ID that names no asset."""
    if asset_id:
        a = fleet.assets.get(asset_id.strip().upper()) or fleet.assets.get(
            fleet.aliases.get(asset_id.strip().upper(), ""))
        if not a:
            return Resolution(unknown=asset_id)
        return Resolution(asset=a, models=[a.model])

    named: list[Asset] = []
    for token in [*rec.asset_ids, *rec.legacy_ids, *rec.serials]:
        a = (fleet.assets.get(token) or fleet.assets.get(fleet.aliases.get(token, ""))
             or next((x for x in fleet.assets.values() if x.serial.upper() == token), None))
        if a is None:
            return Resolution(unknown=token)
        if a not in named:
            named.append(a)
    if len(named) == 1:
        return Resolution(asset=named[0], models=[named[0].model])
    if len(named) > 1:
        return Resolution(models=list(dict.fromkeys(a.model for a in named)), candidates=named)

    site = find_site(question, fleet)
    if len(rec.models) == 1 and site:
        cands = [a for a in fleet.assets.values() if a.model == rec.models[0] and a.site == site]
        if len(cands) == 1:
            return Resolution(asset=cands[0], models=[cands[0].model], site=site)
        return Resolution(models=rec.models, candidates=cands, site=site)
    return Resolution(models=list(rec.models), site=site)


def candidates_differ(cands: list[Asset], statuses: dict[str, dict[str, str]]) -> bool:
    """True when the answer may depend on which candidate is meant (research R6).

    `statuses` maps asset ID to {bulletin doc_id: status} for bulletins the user can see.
    """
    if len({a.firmware for a in cands}) > 1 and any(statuses.values()):
        return True
    keys = {k for s in statuses.values() for k in s}
    return any(len({statuses.get(a.asset_id, {}).get(k, "none") for a in cands}) > 1
               for k in keys)
