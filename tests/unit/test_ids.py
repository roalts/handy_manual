from copilot_ingest.ids import (
    doc_id_for,
    file_fingerprint,
    normalize_text,
    passage_id_for,
    review_item_id,
)


def test_fingerprint_is_content_hash(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert file_fingerprint(a) == file_fingerprint(b)
    b.write_bytes(b"different")
    assert file_fingerprint(a) != file_fingerprint(b)


def test_normalization_ignores_layout_noise():
    assert normalize_text("Pump  casing\nbolts") == normalize_text("pump casing bolts")
    assert normalize_text("tighten-\ning") == "tightening"
    assert normalize_text("ﬁlter") == "filter"  # NFKC ligature


def test_ids_are_deterministic():
    d = doc_id_for("Some document text")
    assert d == doc_id_for("some   document\ntext") and d.startswith("doc_")
    p1 = passage_id_for(d, '{"page":1}', "Step 1")
    assert p1 == passage_id_for(d, '{"page":1}', "step  1")
    assert p1 != passage_id_for(d, '{"page":2}', "Step 1")
    assert review_item_id("fp", "ocr", "a", "f") == review_item_id("fp", "ocr", "a", "f")
