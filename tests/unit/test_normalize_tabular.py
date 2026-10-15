from datetime import date

import pytest

from copilot_ingest.models import ExtractResult
from copilot_ingest.stages.link import build_history
from copilot_ingest.stages.normalize import ConventionError, map_value, parse_date, parse_number


def test_dates_follow_declared_format_only():
    assert parse_date("02-12-2025", "%d-%m-%Y") == date(2025, 12, 2)
    assert parse_date("02/12/2025", "%m/%d/%Y") == date(2025, 2, 12)
    with pytest.raises(ConventionError):
        parse_date("2025-12-02", "%d-%m-%Y")  # never guessed from the value
    assert parse_date("", "%d-%m-%Y") is None
    assert parse_date("2026-09-29T13:10:00.000+0000", "iso8601") == date(2026, 9, 29)


def test_decimal_conventions():
    assert parse_number("2,5", ",") == 2.5
    assert parse_number("1.234,5", ",") == 1234.5
    assert parse_number("1,234.5", ".") == 1234.5
    assert parse_number("", ",") is None


def test_status_mapping_rejects_unknown():
    m = {"Gereed": "completed", "Geannuleerd": "cancelled"}
    assert map_value("Geannuleerd", m, "status") == "cancelled"
    with pytest.raises(ConventionError):
        map_value("Bezig", m, "status")


def _servio(rows):
    header = {"werkorder": "", "datum": "", "object": "", "object_oud": "", "locatie": "",
              "type": "PO", "storingscode": "", "omschrijving": "", "monteur": "",
              "onderdelen": "", "uren": "", "draaiuren": "", "status": "Gereed"}
    return ExtractResult(path="data/servio.csv", fingerprint="f", extractor="tabular",
                         extractor_version="t",
                         records=[{"_row": i + 2, **header, **r} for i, r in enumerate(rows)])


def _fleet():
    return ExtractResult(path="data/fleet_register.csv", fingerprint="g", extractor="tabular",
                         extractor_version="t", records=[{
                             "_row": 2, "asset_id": "RTM-H-0007", "model": "NK-600",
                             "serial": "NK600-230415", "site": "RTM",
                             "site_name": "Rotterdam Distribution Hub", "customer": "x",
                             "region": "EU", "install_date": "3/1/2023", "firmware": "7.0",
                             "oil_type": "", "contract_end": ""}])


def test_legacy_alias_and_blank_legacy():
    h = build_history(_fleet(), [("servio", _servio([
        {"werkorder": "1", "datum": "02-12-2025", "object": "RTM-H-0007",
         "object_oud": "MFL-KM07", "locatie": "Rotterdam DC Maasvlakte", "uren": "2,5"},
        {"werkorder": "2", "datum": "03-12-2025", "object": "RTM-H-0007", "object_oud": ""},
    ]), ["region-eu"])], [])
    assert h.asset_aliases["MFL-KM07"][0] == "RTM-H-0007"
    assert "" not in h.asset_aliases
    assert h.site_aliases["Rotterdam DC Maasvlakte"] == "RTM"
    ev = next(e for e in h.events if e.sources[0]["record_id"] == "1")
    assert ev.event_date == date(2025, 12, 2) and ev.labor_hours == 2.5
    assert ev.required_groups == [["region-eu"]]


def test_unknown_asset_creates_review_item():
    h = build_history(_fleet(), [("servio", _servio([
        {"werkorder": "9", "datum": "01-01-2026", "object": "XYZ-Q-0001"}]), ["region-eu"])], [])
    assert [r.kind for r in h.review] == ["unknown_asset"]
    assert h.events[0].asset_id == "XYZ-Q-0001"


def test_duplicate_export_row_counted_once():
    row = {"werkorder": "5", "datum": "01-01-2026", "object": "RTM-H-0007"}
    h = build_history(_fleet(), [("servio", _servio([row, dict(row)]), ["region-eu"])], [])
    assert len(h.events) == 1
