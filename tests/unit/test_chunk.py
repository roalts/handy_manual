from copilot_ingest.models import Anchor, Block, ExtractResult
from copilot_ingest.stages.chunk import PROCEDURE_MAX, SECTION_MAX, chunk, tokens


def _b(type_, text, path, **kw):
    return Block(type=type_, text=text, heading_path=path, anchor=Anchor(section_path=path), **kw)


def _result(blocks):
    return ExtractResult(path="x.docx", fingerprint="fp", extractor="docx",
                         extractor_version="t", blocks=blocks)


def _procedure(n_steps: int, words: int):
    sec = ["6. Procedure"]
    blocks = [_b("heading", "5. Safety", ["5. Safety"], level=1),
              _b("warning", "WARNING: The DC bus holds a lethal charge.", ["5. Safety"]),
              _b("heading", "6. Procedure", sec, level=1)]
    for sub in range(2):
        path = sec + [f"6.{sub + 1} Part"]
        blocks.append(_b("heading", f"6.{sub + 1} Part", path, level=2))
        for i in range(n_steps // 2):
            n = sub * (n_steps // 2) + i + 1
            blocks.append(_b("procedure_step", f"Step: {n} | Action: " + "word " * words, path,
                             fields={"number": n}))
    return blocks


def test_small_procedure_is_one_passage_with_safety():
    ps = chunk(_result(_procedure(6, 10)), "doc")
    proc = [p for p in ps if "procedure_step" in p.block_types]
    assert len(proc) == 1 and proc[0].role == "standard"
    assert "Step: 1 |" in proc[0].text_original and "Step: 6 |" in proc[0].text_original
    assert "lethal charge" in proc[0].text_original


def test_large_procedure_has_parent_and_children():
    ps = chunk(_result(_procedure(12, 60)), "doc")
    parents = [p for p in ps if p.role == "parent"]
    children = [p for p in ps if p.role == "child"]
    assert len(parents) == 1 and tokens(parents[0].text_original) > PROCEDURE_MAX
    assert all(c.parent_passage_id == parents[0].passage_id for c in children)
    for n in range(1, 13):
        assert f"Step: {n} |" in parents[0].text_original
        assert any(f"Step: {n} |" in c.text_original for c in children)
    assert all(c.heading_path[:1] == ["6. Procedure"] for c in children)


def test_split_table_repeats_header():
    path = ["3. Data"]
    rows = [[f"row{i}", "value " * 20] for i in range(60)]
    table = _b("table", "\n".join(" | ".join(r) for r in [["Name", "Value"], *rows]), path,
               header=["Name", "Value"], rows=rows)
    ps = chunk(_result([_b("heading", "3. Data", path, level=1), table]), "doc")
    assert len(ps) > 1
    for p in ps:
        assert "Name | Value" in p.text_original
        assert tokens(p.text_original) <= SECTION_MAX + 50
        assert p.heading_path == path


def test_short_section_stays_whole():
    path = ["1. Purpose"]
    ps = chunk(_result([_b("heading", "1. Purpose", path, level=1),
                        _b("paragraph", "First paragraph.", path),
                        _b("paragraph", "Second paragraph.", path)]), "doc")
    assert len(ps) == 1 and "Second paragraph." in ps[0].text_original


def test_messages_are_one_passage_each():
    msgs = [Block(type="message", text=f"From: a\n\nbody {i}",
                  anchor=Anchor(message_id=f"m{i}")) for i in range(3)]
    ps = chunk(_result(msgs), "doc")
    assert [p.anchor.message_id for p in ps] == ["m0", "m1", "m2"]


def test_identifiers_extracted():
    path = ["7. Faults"]
    ps = chunk(_result([_b("heading", "7. Faults", path, level=1),
                        _b("paragraph", "On TAC-C-0142 (VRS110-230877) e-14 repeated; replaced "
                           "41-2207, see SF 00041207. Revised 15-03-2021.", path)]), "doc")
    p = ps[0]
    assert p.fault_codes == ["E-14"] and p.asset_ids == ["TAC-C-0142"]
    assert p.part_numbers == ["41-2207"] and p.case_numbers == ["00041207"]
    assert "VRS-110" in p.models and p.serials == ["VRS110-230877"]
