from copilot_ingest.models import ExtractResult, PageCoverage
from copilot_ingest.review import Decisions, item_id
from copilot_ingest.stages import scan, translate

FLEET = {"HCP-200", "HCP-350", "HCP-500"}


def _page(rows, tesseract, paragraphs=()):
    blocks = [{"type": "heading", "level": 1, "text": "3 Technische Daten\nTechnical data",
               "header": None, "rows": None},
              {"type": "table", "level": None, "text": "Tabelle / Table 3.1",
               "header": ["Benennung\nDesignation", "Wert\nValue"], "rows": rows}]
    blocks += [{"type": "paragraph", "level": None, "text": t, "header": None, "rows": None}
               for t in paragraphs]
    return scan.ScanPage(page=3, image="page_images/fp/page-3.png",
                         tesseract={"4": tesseract, "6": ""},
                         vision={"blocks": blocks, "page_furniture": ["HDN-BA-200 Rev. A"]})


def _apply(sp, decisions=None):
    r = ExtractResult(path="manuals/hcp200.pdf", fingerprint="fp", extractor="pdf",
                      extractor_version="x", pages=[PageCoverage(page=3, status="scanned")])
    return scan.apply(r, scan.ScanResult(fingerprint="fp", model="m", pages=[sp]), FLEET,
                      decisions)


def _table(check):
    return next(b for b in check.result.blocks if b.type == "table")


def test_agreeing_values_are_verified_across_decimal_comma():
    sp = _page([["NPSH erforderlich\nNPSH required", "3,2 m"]],
               "NPSH erforderlich | 3.2 m\nNPSH required")
    check = _apply(sp)
    assert check.stats["verified"] == 1 and check.stats["withheld"] == 0
    assert _table(check).rows == [["NPSH erforderlich NPSH required", "3,2 m"]]


def test_disagreeing_value_is_withheld_with_marker_and_review_item():
    sp = _page([["Spaltmaß Laufrad - Gehäuse (diametral)\nImpeller-to-casing clearance",
                 "0.38 - 0.50 mm"]],
               "Spaltmaß Laufrad - Gehäuse (diametral) 2.10 050 mm\nImpeller-to-casing")
    check = _apply(sp)
    [item] = check.review
    assert item.kind == "ocr_value_mismatch" and item.candidates["vision"] == "0.38 - 0.50 mm"
    cell = _table(check).rows[0][1]
    assert cell == f"[[unverified:{item_id(item)}|page=3]]"
    text = " ".join(b.text for b in check.result.blocks)
    assert "0.38" not in text and "2.10" not in text


def test_value_without_aligned_tesseract_line_is_withheld():
    sp = _page([["Laufraddurchmesser\nImpeller diameter", "265 mm"]], "nothing similar here")
    check = _apply(sp)
    assert check.stats["withheld"] == 1
    assert check.review[0].reason.startswith("no Tesseract line")


def test_reviewer_value_replaces_marker():
    sp = _page([["Laufraddurchmesser\nImpeller diameter", "265 mm"]], "nothing similar here")
    item = _apply(sp).review[0]
    check = _apply(sp, Decisions({item_id(item): "265 mm"}))
    assert _table(check).rows[0][1] == "265 mm" and check.stats["reviewer"] == 1
    assert check.review == []


def test_paragraph_values_checked_per_line():
    sp = _page([], "Dauerbetrieb zwischen 30 % und 110 % des Förderstroms",
               ["Dauerbetrieb zwischen 30 % und 110 % des Förderstroms"])
    check = _apply(sp)
    assert check.stats == {**check.stats, "checked": 2, "verified": 2, "withheld": 0}


def test_model_code_one_edit_from_fleet_is_corrected_and_logged():
    log = []
    assert scan.correct_models("Baureihe HGP-200", FLEET, log, 3, "tesseract-6") == \
        "Baureihe HCP-200"
    assert log == [{"page": 3, "read_by": "tesseract-6", "read": "HGP-200",
                    "corrected": "HCP-200"}]


def test_model_code_with_two_near_fleet_models_is_left_alone():
    assert scan.correct_models("HCP-300", {"HCP-200", "HCP-350", "HCP-301", "HCP-302"}, [],
                               1) == "HCP-300"


def test_scanned_pages_become_text_with_flags():
    sp = _page([["NPSH erforderlich\nNPSH required", "3,2 m"]], "NPSH erforderlich 3.2 m")
    r = _apply(sp).result
    assert [p.status for p in r.pages] == ["text"]
    assert r.flags["ocr_pages"] == [3] and r.flags["page_furniture"] == ["HDN-BA-200 Rev. A"]


# --- translation guard -------------------------------------------------------------------------

def test_translation_must_keep_numbers_and_codes():
    assert translate.preserved("persdruk c1 10,9 bar, L-01", "discharge pressure c1 10.9 bar, L-01")
    assert not translate.preserved("persdruk 10,9 bar", "discharge pressure high")


def test_translation_must_not_add_values_or_touch_markers():
    marker = "[[unverified:r_0123456789abcdef|page=3]]"
    assert not translate.preserved(f"Laufrad {marker}", "impeller 265 mm")
    assert not translate.preserved(f"Laufrad {marker}", "impeller 265 mm " + marker)
    assert translate.preserved(f"Laufrad {marker}", f"impeller {marker}")


def test_bilingual_text_is_not_translated():
    text = ("Die Angaben gelten für die Normalausführung der Pumpe.\n"
            "The data are valid for the standard design of the pump.")
    assert translate.is_bilingual(text)
    assert not translate.is_bilingual("controle, olieniveau ok, condensaatafvoer werkt prima")
