"""Assets, aliases, and the merged service history (US2)."""
from dataclasses import dataclass, field

import yaml

from copilot_ingest.ids import event_id_for
from copilot_ingest.models import Asset, ExtractResult, ReviewItem, ServiceEvent
from copilot_ingest.review import Decisions
from copilot_ingest.settings import CONFIG_DIR
from copilot_ingest.stages.normalize import (
    ConventionError,
    find,
    identifiers,
    map_value,
    parse_date,
    parse_number,
)

VERSION = "link-1"


def _sources() -> dict:
    """The per-source column, date and value-mapping config from sources.yaml."""
    return yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())


@dataclass
class History:
    assets: dict[str, Asset] = field(default_factory=dict)
    asset_aliases: dict[str, tuple[str, str]] = field(default_factory=dict)  # alias->(id, src)
    site_aliases: dict[str, str] = field(default_factory=dict)
    events: list[ServiceEvent] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    merged_cases: int = 0
    merged_with_different_rules: int = 0
    decisions: Decisions = field(default_factory=Decisions)

    def raise_or_decide(self, item: ReviewItem):
        """The reviewer's value for this item, or None after queueing it for review."""
        value = self.decisions.get(item)
        if value is None:
            self.review.append(item)
        return value


def build_assets(fleet: ExtractResult, h: History) -> None:
    """Load fleet register rows into `h.assets`, registering serials and site names as aliases.
    Rows that fail to parse are recorded in `h.errors` and skipped."""
    fmt = _sources()["fleet_register"]["date_format"]
    for r in fleet.records:
        try:
            a = Asset(asset_id=r["asset_id"].upper(), model=r["model"], serial=r["serial"].upper(),
                      site=r["site"], site_name=r.get("site_name") or None,
                      customer=r.get("customer") or None, region=r["region"],
                      install_date=parse_date(r.get("install_date"), fmt),
                      firmware=r.get("firmware") or None, oil_type=r.get("oil_type") or None,
                      contract_end=parse_date(r.get("contract_end"), fmt))
        except (ConventionError, KeyError) as e:
            h.errors.append(f"fleet_register row {r.get('_row')}: {e}")
            continue
        h.assets[a.asset_id] = a
        h.asset_aliases[a.serial] = (a.asset_id, "fleet_register.serial")
        h.site_aliases.setdefault(a.site, a.site)
        if a.site_name:
            h.site_aliases.setdefault(a.site_name, a.site)


def _resolve_asset(raw: str, h: History) -> str | None:
    """The fleet asset ID for a raw asset ID or alias, or None if unknown."""
    raw = (raw or "").strip().upper()
    if raw in h.assets:
        return raw
    if raw in h.asset_aliases:
        return h.asset_aliases[raw][0]
    return None


def _decided_asset(chosen, raw: str, h: History) -> str:
    """A reviewer-chosen fleet asset, else the raw ID (kept, flagged as unknown)."""
    if chosen and chosen != "keep":
        if chosen in h.assets:
            h.asset_aliases.setdefault(raw.strip().upper(), (chosen, "reviewer"))
            return chosen
        h.errors.append(f"review decision maps {raw!r} to {chosen!r}, not in the fleet register")
    return raw.strip().upper()


def _parts(text: str) -> list[str]:
    """Part numbers found in free text."""
    return find("part_number", text or "")


def _maintenance_events(name: str, result: ExtractResult, required: list[str],
                        h: History) -> list[tuple[ServiceEvent, list[str]]]:
    """Return events with the case numbers each row cites."""
    cfg = _sources()[name]
    cols = cfg["columns"]
    out = []
    seen: dict[str, dict] = {}
    for r in result.records:
        rid = r[cfg["record_id"]]
        content = {k: v for k, v in r.items() if k != "_row"}
        if rid in seen:
            if seen[rid] == content:
                # the export repeats the row; it is one event
                h.counts[f"{name} duplicate rows skipped"] = \
                    h.counts.get(f"{name} duplicate rows skipped", 0) + 1
                continue
            rid = f"{rid}#row{r['_row']}"
        seen[rid] = content
        anchor = {"record_id": rid, "row": r["_row"]}
        try:
            event_date = parse_date(r[cols["date"]], cfg["date_format"])
            status = map_value(r[cols["status"]], cfg["status_map"], "status")
            etype = map_value(r[cols["event_type"]], cfg["event_type_map"], "event type")
            labor = parse_number(r.get(cols["labor_hours"], ""), cfg["decimal"])
            run_hours = parse_number(r.get(cols["run_hours"], ""), cfg["decimal"])
        except ConventionError as e:
            h.errors.append(f"{result.path} row {r['_row']}: {e}")
            continue
        raw_asset = r[cols["asset"]]
        asset_id = _resolve_asset(raw_asset, h)
        legacy = r.get(cols.get("legacy_asset", ""), "").strip().upper() if "legacy_asset" in \
            cols else ""
        if legacy and asset_id:
            prev = h.asset_aliases.get(legacy)
            if prev and prev[0] != asset_id:
                chosen = h.raise_or_decide(ReviewItem(
                    kind="unknown_asset", path=result.path, anchor=anchor, field="legacy_asset",
                    candidates={"legacy": legacy, "assets": [prev[0], asset_id]},
                    reason="legacy ID maps to two current assets",
                    fingerprint=result.fingerprint, stage="link"))
                if chosen in h.assets:
                    h.asset_aliases[legacy] = (chosen, "reviewer")
            else:
                h.asset_aliases[legacy] = (asset_id, f"{name}.{cols['legacy_asset']}")
        if asset_id is None:
            chosen = h.raise_or_decide(ReviewItem(
                kind="unknown_asset", path=result.path, anchor=anchor, field="asset",
                candidates={"value": raw_asset}, reason="asset not in the fleet register",
                fingerprint=result.fingerprint, stage="link"))
            asset_id = _decided_asset(chosen, raw_asset, h)
        site_name = r.get(cols.get("site_name", ""), "").strip() if "site_name" in cols else ""
        if site_name and asset_id in h.assets:
            h.site_aliases.setdefault(site_name, h.assets[asset_id].site)
        notes = r.get(cols["notes"], "") or None
        fault = (r.get(cols["fault_code"], "") or "").strip().upper() or None
        ev = ServiceEvent(
            event_id=event_id_for(name, rid), asset_id=asset_id, event_date=event_date,
            event_type=etype, fault_code=fault, status=status, notes_original=notes,
            parts=_parts(r.get(cols["parts"], "")), labor_hours=labor, run_hours=run_hours,
            technician=r.get(cols["technician"]) or None,
            sources=[{"system": name, "path": result.path, "record_id": rid,
                      "row": r["_row"], "lang": cfg.get("lang")}],
            required_groups=[sorted(required)],
        )
        out.append((ev, identifiers(notes or "")["case_numbers"]))
    h.counts[f"{name} events"] = len(out)
    return out


def _case_events(result: ExtractResult, required: list[str], h: History
                 ) -> dict[str, ServiceEvent]:
    """Salesforce case events keyed by case number; unknown assets are queued for review."""
    cfg = _sources()["salesforce"]
    out = {}
    for rec in result.records:
        cn = rec["case_number"]
        try:
            status = map_value(rec["status"], cfg["status_map"], "case status")
            created = parse_date(rec["created"], "iso8601")
        except ConventionError as e:
            h.errors.append(f"{result.path} case {cn}: {e}")
            continue
        asset_id = _resolve_asset(rec["asset"] or rec["serial"] or "", h)
        if asset_id is None:
            chosen = h.raise_or_decide(ReviewItem(
                kind="unknown_asset", path=result.path, anchor={"record_id": cn}, field="asset",
                candidates={"asset": rec["asset"], "serial": rec["serial"]},
                reason="case asset not in the fleet register",
                fingerprint=result.fingerprint, stage="link"))
            asset_id = _decided_asset(chosen, rec["asset"] or rec["serial"] or "UNKNOWN", h)
        if rec.get("site") and asset_id in h.assets:
            h.site_aliases.setdefault(rec["site"], h.assets[asset_id].site)
        notes = " | ".join(x for x in (rec["subject"], rec["description"], rec["resolution"]) if x)
        out[cn] = ServiceEvent(
            event_id=event_id_for("salesforce", cn), asset_id=asset_id, event_date=created,
            event_type="case", fault_code=(rec["fault_code"] or "").upper() or None,
            status=status, notes_original=notes or None, parts=_parts(rec["parts_used"] or ""),
            technician=rec["owner"],
            sources=[{"system": "salesforce", "path": result.path, "record_id": cn}],
            required_groups=[sorted(required)],
        )
    h.counts[f"salesforce:{result.path}"] = len(out)
    return out


def build_history(fleet: ExtractResult | None, maintenance: list[tuple[str, ExtractResult, list]],
                  cases: list[tuple[ExtractResult, list]],
                  decisions: Decisions | None = None) -> History:
    """maintenance: (source name, extract, required groups); cases: (extract, required groups)."""
    h = History(decisions=decisions or Decisions())
    if fleet is not None:
        build_assets(fleet, h)
    rows: list[tuple[ServiceEvent, list[str]]] = []
    for name, result, required in maintenance:
        rows += _maintenance_events(name, result, required, h)
    case_events: dict[str, ServiceEvent] = {}
    for result, required in cases:
        case_events.update(_case_events(result, required, h))

    claimed: set[str] = set()
    for ev, cited in sorted(rows, key=lambda x: (x[0].event_date, x[0].event_id)):
        for cited_cn in cited:
            cn, case = cited_cn, case_events.get(cited_cn)
            if case is None:
                fix = h.raise_or_decide(ReviewItem(
                    kind="unresolved_link", path=ev.sources[0]["path"],
                    anchor={"record_id": ev.sources[0]["record_id"], "case_number": cited_cn},
                    field="case_number", candidates={"case_number": cited_cn},
                    reason="cited case not found in any case export", stage="link"))
                if fix and fix != "none":
                    cn, case = fix, case_events.get(fix)
                if case is None:
                    if fix and fix != "none":
                        h.errors.append(f"review decision links {cited_cn} to {fix}, "
                                        "which is not in any case export")
                    continue
            if cn in claimed:
                ev.sources.append({"system": "salesforce", "record_id": cn,
                                   "relation": "references"})
                continue
            claimed.add(cn)
            ev.sources.append({**case.sources[0], "relation": "same_event"})
            if case.required_groups != ev.required_groups:
                # combined content: the user must be allowed to see every source
                ev.required_groups = [sorted(set(ev.required_groups[0])
                                             | set(case.required_groups[0]))]
                h.merged_with_different_rules += 1
            if not ev.fault_code and case.fault_code:
                ev.fault_code = case.fault_code
            h.merged_cases += 1
        h.events.append(ev)
    h.events += [ev for cn, ev in case_events.items() if cn not in claimed]
    h.events.sort(key=lambda e: (e.asset_id, e.event_date, e.event_id))
    return h


def event_text(ev: ServiceEvent) -> str:
    """One-line summary of a service event, ending with its source record references."""
    refs = "; ".join(f"{s['system']} {s['record_id']}" for s in ev.sources)
    parts = f" Parts: {', '.join(ev.parts)}." if ev.parts else ""
    fault = f" fault {ev.fault_code}" if ev.fault_code else ""
    hours = f" Run hours {ev.run_hours:g}." if ev.run_hours is not None else ""
    return (f"{ev.event_date.isoformat()} {ev.asset_id} {ev.event_type}{fault} ({ev.status}): "
            f"{ev.notes_original or ''}{parts}{hours} Technician {ev.technician or '-'}. "
            f"Source: {refs}").strip()
