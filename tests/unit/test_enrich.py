from datetime import date
from types import SimpleNamespace as NS

from copilot_ingest.models import Anchor, Block, BulletinRule, Document, ExtractResult
from copilot_ingest.stages import enrich


def _block(text, page=1, type_="paragraph", header=None, rows=None):
    return Block(type=type_, text=text, anchor=Anchor(page=page), header=header, rows=rows)


def _result(blocks, extractor="pdf"):
    return ExtractResult(path="x.pdf", fingerprint="f", extractor=extractor,
                         extractor_version="1", blocks=blocks)


def _rule(**kw):
    base = dict(rule_id="r", doc_id="d", model="VRS-110", outcome="affected", quote="q")
    return BulletinRule(**{**base, **kw})


def _asset(asset_id, model, serial, firmware=None, region="EU"):
    return NS(asset_id=asset_id, model=model, serial=serial, firmware=firmware, region=region)


# --- quote verification (R7) -----------------------------------------------------------------

def test_verify_accepts_exact_quote_with_parsable_value():
    block = "Document BC-OM-012, Issue B,\n1 October 2024"
    assert enrich.verify("issue_date", "2024-10-01", "Issue B, 1 October 2024", block)
    assert enrich.verify("revision", "B", "Issue B, 1 October 2024", block)


def test_verify_rejects_quote_not_in_block():
    assert not enrich.verify("revision", "C", "Revision C", "Revision B (2024-02-12)")


def test_verify_rejects_value_not_in_quote():
    assert not enrich.verify("issue_date", "2024-03-01", "Issue date 2024-02-12",
                             "Issue date 2024-02-12")


def test_parse_date_forms():
    assert enrich.parse_date("Issue date / Ausgabedatum 2025-06-18") == date(2025, 6, 18)
    assert enrich.parse_date("2 September 2025") == date(2025, 9, 2)
    assert enrich.parse_date("last modified on Mar 21, 2024") == date(2024, 3, 21)
    assert enrich.parse_date("week 01/2024") is None


def test_rule_metadata_ignores_revision_mentions_in_prose():
    r = _result([_block("Rev E of the HCP-350 IOM is in preparation.")])
    assert "revision" not in enrich.rule_metadata(r, {}).fields


def test_rule_metadata_cover_and_replaces():
    r = _result([_block("Revision C   (2026-04-20)"), _block("Replaces Rev. B, 2024-02")])
    md = enrich.rule_metadata(r, {})
    assert md.fields["revision"].value == "C"
    assert md.fields["issue_date"].value == date(2026, 4, 20)
    assert md.replaces.value == "B"


def test_part_supersession_is_not_document_supersession():
    r = _result([_block("Supersedes 18-0355 (Halden SB-2025-018).")])
    assert enrich.rule_metadata(r, {}).replaces is None


class _Stub:
    def __init__(self, out):
        self.out = out

    def complete_json(self, model, prompt, schema, prompt_version):
        return self.out


def test_model_metadata_keeps_only_verified_answers():
    r = _result([_block("Issue date 2023-05-22"), _block("Halden pumps")])
    md = enrich.Metadata()
    stub = _Stub({"fields": [
        {"field": "issue_date", "value": "2023-05-22", "quote": "Issue date 2023-05-22",
         "block_id": "b0"},
        {"field": "revision", "value": "D", "quote": "Revision D", "block_id": "b1"},
    ]})
    enrich.model_metadata(r, md, ["revision", "issue_date"], stub, "m", "x.pdf", None)
    assert md.fields["issue_date"].value == date(2023, 5, 22)
    assert "revision" not in md.fields
    assert [(i.kind, i.field) for i in md.review] == [("metadata_unverified", "revision")]


# --- bulletin rules and evaluation (R8) --------------------------------------------------------

def test_bulletin_table_parsing():
    t = _block("", type_="table",
               header=["Model", "Serial numbers", "Market", "Valve fitted", "Status"],
               rows=[["NK-600", "NK600-220001 to NK600-231999", "EU deliveries",
                      "EXV-2 rev 2", "In campaign NK-C25-14"],
                     ["NK-600", "NK600-232000 and later", "All", "EXV-2 rev 3",
                      "Not affected"]])
    rules = enrich.bulletin_rules(_result([t]), "d")
    assert [(r.serial_from, r.serial_to, r.market_condition, r.outcome, r.campaign_code)
            for r in rules] == [
        ("NK600-220001", "NK600-231999", "EU deliveries", "in_campaign", "NK-C25-14"),
        ("NK600-232000", None, None, "not_affected", None)]


def test_firmware_matching():
    assert enrich.firmware_matches("5.0", "5.0.0 to 5.0.3")
    assert not enrich.firmware_matches("5.1", "5.0.0 to 5.0.3")
    assert enrich.firmware_matches("4.8", "4.x")
    assert enrich.firmware_matches("5.1", "5.1.0")
    assert enrich.firmware_matches(None, "5.1.0") is None


def test_evaluate_firmware_and_newer_than_listed():
    rules = [_rule(rule_id="a", serial_from="VRS110-210001", firmware_condition="5.0.0 to 5.0.3"),
             _rule(rule_id="b", serial_from="VRS110-210001", firmware_condition="5.1.0",
                   outcome="not_affected")]
    out = {s.asset_id: s.status for s in enrich.evaluate(rules, [
        _asset("A", "VRS-110", "VRS110-230877", "5.0"),
        _asset("B", "VRS-110", "VRS110-250102", "5.2"),
        _asset("C", "VRS-110", "VRS110-250103", None),
        _asset("D", "VRS-75", "VRS75-1", "5.0")], "d", partial=False)}
    assert out == {"A": "affected", "B": "not_affected", "C": "check_on_site"}


def test_evaluate_market_undecidable_is_check_on_site():
    rules = [_rule(model="NK-600", serial_from="NK600-220001", serial_to="NK600-231999",
                   market_condition="EU deliveries", outcome="in_campaign")]
    [s] = enrich.evaluate(rules, [_asset("A", "NK-600", "NK600-230415", region=None)], "d",
                          partial=False)
    assert s.status == "check_on_site"


def test_partial_bulletin_never_clears_a_unit():
    rules = [_rule(model="VRS-45", serial_from="VRS45-230001", serial_to="VRS45-251399"),
             _rule(rule_id="n", model="VRS-45", serial_from="VRS45-251400",
                   outcome="not_affected")]
    out = {s.asset_id: s.status for s in enrich.evaluate(rules, [
        _asset("A", "VRS-45", "VRS45-240511"), _asset("B", "VRS-45", "VRS45-260001")],
        "d", partial=True)}
    assert out == {"A": "affected", "B": "check_on_site"}


def test_condition_widens_scope_to_check_on_site():
    rules = [_rule(model="HCP-350", serial_from="HCP350-210001", serial_to="HCP350-239999",
                   outcome="not_affected"),
             _rule(rule_id="b", model="HCP-350", serial_from="HCP350-240001")]
    quote = "A pump before HCP350-240001 that has been fitted with a replacement cover"
    rules += enrich.condition_rules([enrich.Condition(
        "HCP-350", *enrich.quoted_serial_bound(quote), "affected", quote, 1)], "d")
    out = {s.asset_id: s.status for s in enrich.evaluate(rules, [
        _asset("old", "HCP-350", "HCP350-221034"), _asset("new", "HCP-350", "HCP350-241187")],
        "d", partial=False)}
    assert out == {"old": "check_on_site", "new": "affected"}


def test_conditions_without_quoted_serial_scope_are_ignored():
    r = _result([_block("Units delivered from February 2026 leave the factory with 5.1.0.")])
    stub = _Stub({"conditions": [{"model": "VRS-110", "serial_from": "VRS110-260001",
                                  "serial_before": None, "outcome_if_met": "affected",
                                  "quote": "Units delivered from February 2026 leave the "
                                           "factory with 5.1.0.", "block_id": "b0"}]})
    kept, notes = enrich.bulletin_conditions(r, [_rule()], stub, "m")
    assert kept == [] and notes[0].startswith("ignored")


# --- supersession ------------------------------------------------------------------------------

def _doc(doc_id, revision, issued, models=("VRS-75",)):
    return Document(doc_id=doc_id, title=doc_id, doc_type="service_manual", authority_tier=3,
                    controlled=False, models=list(models), revision=revision,
                    issue_date=issued, status="active", extractor_version="1", origins=[])


def test_supersession_uses_replaces_quote():
    docs = {"b": _doc("b", "B", date(2024, 2, 12)), "c": _doc("c", "C", date(2026, 4, 20)),
            "x": _doc("x", "A", date(2023, 1, 1), models=("VRS-110",))}
    md = {"c": enrich.Metadata(replaces=enrich.Evidence("B", "Replaces Rev. B, 2024-02", 1,
                                                        "cover"))}
    [rel] = enrich.supersessions(docs, md)
    assert (rel.from_doc, rel.to_doc, rel.quote) == ("c", "b", "Replaces Rev. B, 2024-02")
