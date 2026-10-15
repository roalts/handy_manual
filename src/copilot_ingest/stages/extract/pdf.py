import io
import re
from collections import Counter

import pikepdf
import pymupdf

from copilot_ingest.models import Anchor, Block, ExtractResult, PageCoverage

VERSION = "pdf-4"
SIGNAL_WORDS = {"DANGER", "WARNING", "CAUTION", "NOTE", "STOP", "GEFAHR", "WARNUNG", "VORSICHT",
                "HINWEIS", "ACHTUNG", "VARNING", "WAARSCHUWING", "LET OP"}
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
_STEP = re.compile(r"^(\d{1,2})(?:[.)]\s*|\s+)(?=[A-ZÄÖÜÅ])")
_DIGITS = re.compile(r"\d+")
_LETTERS = re.compile(r"[A-Za-zÄÖÜäöüÅåß]{3}")
_SIGNAL_START = re.compile(r"^(" + "|".join(sorted(SIGNAL_WORDS, key=len, reverse=True)) +
                           r"|IMPORTANT)\b", re.I)
MIN_TEXT_CHARS = 25

pymupdf.TOOLS.mupdf_display_errors(False)


_DAMAGE = re.compile(r"zlib error|read error|treating as end of file|non-page object|"
                     r"syntax error|unknown compression", re.I)


def _open(path, flags: dict) -> pymupdf.Document:
    """Open with PyMuPDF, falling back to a pikepdf-repaired copy if opening fails or finds no
    pages. Open warnings and errors are recorded in `flags`."""
    pymupdf.TOOLS.mupdf_warnings(reset=True)
    try:
        doc = pymupdf.open(path)
        warnings = pymupdf.TOOLS.mupdf_warnings(reset=True)
        if warnings:
            flags["open_warnings"] = warnings.splitlines()[:10]
        if doc.page_count > 0:
            return doc
    except Exception as e:  # noqa: BLE001
        flags["open_error"] = str(e)
    flags["repaired_with"] = "pikepdf"
    return _repaired(path)


def _signature(text: str) -> str:
    """Key for spotting repeated headers/footers: digits masked so page numbers still match."""
    return _DIGITS.sub("#", text.strip().lower())[:22]


def _merge_wrapped_rows(rows: list[list[str]]) -> list[list[str]]:
    """Borderless tables split a wrapped cell into an extra row with an empty first cell."""
    out: list[list[str]] = []
    for r in rows:
        if out and len(r) == len(out[-1]) and not r[0] and len(out) > 1:
            out[-1] = [f"{a} {b}".strip() for a, b in zip(out[-1], r, strict=False)]
        else:
            out.append(list(r))
    return out


def _merge_baseline(lines: list[dict]) -> list[dict]:
    """Join spans printed on the same baseline (e.g. '5.3' + 'Changing the oil')."""
    rows: list[list[dict]] = []
    for ln in sorted(lines, key=lambda ln: ln["y0"]):
        mid = (ln["y0"] + ln["y1"]) / 2
        row = next((r for r in rows if r[0]["y0"] - 1 <= mid <= r[0]["y1"] + 1), None)
        if row is None:
            rows.append([ln])
        else:
            row.append(ln)
    out: list[dict] = []

    def finish(parts: list[dict]):
        """Append the left-to-right parts to `out` as one line."""
        merged = dict(parts[0])
        merged["text"] = " ".join(p["text"] for p in parts)
        merged["x1"] = parts[-1]["x1"]
        merged["block"] = parts[-1]["block"]
        # chapter numbers are often printed large and regular next to a bold title;
        # boldness and size are judged on the parts that carry words
        worded = [p for p in parts if _LETTERS.search(p["text"])] or parts
        merged["bold"] = all(p["bold"] for p in worded)
        merged["size"] = max(p["size"] for p in worded)
        out.append(merged)

    for row in rows:
        row.sort(key=lambda ln: ln["x0"])
        parts = [row[0]]
        for ln in row[1:]:
            if ln["x0"] - parts[-1]["x1"] > 120:  # separate column, keep apart
                finish(parts)
                parts = [ln]
            else:
                parts.append(ln)
        finish(parts)
    return out


def _in_any(bbox, rects) -> bool:
    """True if the centre of `bbox` lies inside any of `rects`."""
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in rects)


def _line_text(line) -> str:
    """Text of a PyMuPDF line: its spans joined and stripped."""
    return "".join(s["text"] for s in line["spans"]).strip()


def _repaired(path) -> pymupdf.Document:
    """Rewrite the file through pikepdf's recovery in memory and open the result."""
    buf = io.BytesIO()
    with pikepdf.open(path, attempt_recovery=True) as pdf:
        pdf.save(buf)
    return pymupdf.open(stream=buf.getvalue(), filetype="pdf")


def _text_chars(r: ExtractResult) -> int:
    """Characters on text pages, used to compare original and repaired extractions."""
    return sum(p.chars for p in r.pages if p.status == "text")


def _damaged(r: ExtractResult) -> bool:
    """True if opening or reading pages hit damage, which makes a repair attempt worthwhile."""
    return bool(r.flags.get("open_warnings") or r.flags.get("page_damage")
                or r.flags.get("truncated_pages")
                or any(p.status == "unrecoverable" for p in r.pages))


def extract(path, rel_path: str, fingerprint: str) -> ExtractResult:
    """Extract text; on damage, also extract a qpdf-repaired copy and keep the one that recovers
    more text (research.md R6)."""
    flags: dict = {}
    result = _extract_doc(_open(str(path), flags), rel_path, fingerprint, flags)
    if not _damaged(result) or result.flags.get("repaired_with"):
        return result
    try:
        repaired_flags: dict = {"repaired_with": "pikepdf"}
        pymupdf.TOOLS.mupdf_warnings(reset=True)
        repaired = _extract_doc(_repaired(str(path)), rel_path, fingerprint, repaired_flags)
    except Exception as e:  # noqa: BLE001
        result.flags["repair"] = {"error": str(e)}
        return result
    kept = repaired if _text_chars(repaired) > _text_chars(result) else result
    kept.flags["repair"] = {"original_chars": _text_chars(result),
                            "repaired_chars": _text_chars(repaired),
                            "kept": "repaired" if kept is repaired else "original"}
    return kept


def _extract_doc(doc: pymupdf.Document, rel_path: str, fingerprint: str,
                 flags: dict) -> ExtractResult:
    """Two passes: collect lines, tables and font statistics per page, then classify lines into
    blocks using the body font size, dropping headers/footers repeated on most pages."""
    meta_title = (doc.metadata or {}).get("title") or None

    pages_lines: list[list[dict]] = []
    pages_tables: list[list] = []
    size_chars: Counter = Counter()
    edge_sigs: Counter = Counter()

    page_damage: dict[int, list[str]] = {}
    pymupdf.TOOLS.mupdf_warnings(reset=True)
    for page in doc:
        # warnings since the previous page include those raised while loading this page
        h = page.rect.height
        try:
            page.get_text("text")
        except Exception:  # noqa: BLE001
            pass
        damage = [w for w in pymupdf.TOOLS.mupdf_warnings(reset=True).splitlines()
                  if _DAMAGE.search(w)]
        if damage:
            page_damage[page.number + 1] = damage
        try:
            found = page.find_tables().tables
        except Exception:  # noqa: BLE001
            found = []
        tables = []
        for t in found:
            rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in t.extract()]
            rows = [r for r in rows if any(r)]
            cells = [c for r in rows for c in r]
            fill = sum(1 for c in cells if c) / max(1, len(cells))
            area = pymupdf.Rect(t.bbox).get_area() / page.rect.get_area()
            # layout boxes (covers, framed pages) are detected as sparse tables; their text
            # must flow as normal lines or it would be lost
            if area > 0.4 and fill < 0.6 or fill < 0.2:
                continue
            tables.append((t, _merge_wrapped_rows(rows)))
        rects = [pymupdf.Rect(t.bbox) for t, _ in tables]
        lines = []
        try:
            data = page.get_text("dict")
        except Exception as e:  # noqa: BLE001
            flags.setdefault("page_errors", {})[page.number + 1] = str(e)
            data = {"blocks": []}
        for b_no, b in enumerate(data["blocks"]):
            for line in b.get("lines", []):
                text = _line_text(line)
                if not text or _in_any(line["bbox"], rects):
                    continue
                span = max(line["spans"], key=lambda s: len(s["text"]))
                lines.append({"text": text, "size": round(span["size"], 1),
                              "bold": bool(span["flags"] & 16) or "Bold" in span["font"],
                              "x0": line["bbox"][0], "x1": line["bbox"][2],
                              "y0": line["bbox"][1], "y1": line["bbox"][3], "block": b_no})
        lines = _merge_baseline(lines)
        # margin icons and chapter tabs ("!", "i", "5") carry no text
        lines = [ln for ln in lines if len(ln["text"]) > 2 or ln["text"].isalnum() and
                 ln["x0"] > page.rect.width * 0.1 and ln["x1"] < page.rect.width * 0.9]
        for ln in lines:
            ln["edge"] = ln["y1"] < h * 0.09 or ln["y0"] > h * 0.91
            size_chars[ln["size"]] += len(ln["text"])
            if ln["edge"]:
                edge_sigs[_signature(ln["text"])] += 1
        pages_lines.append(lines)
        pages_tables.append(tables)

    n_pages = doc.page_count
    body_size = size_chars.most_common(1)[0][0] if size_chars else 10.0
    repeated = {s for s, c in edge_sigs.items() if n_pages >= 3 and c >= max(2, n_pages * 0.5)}
    heading_sizes = sorted({s for s in size_chars if s > body_size + 0.4}, reverse=True)

    blocks: list[Block] = []
    coverage: list[PageCoverage] = []
    heading_path: list[str] = []
    pending_signal: str | None = None
    title = None

    def push_heading(text: str, level: int, page_no: int):
        """Update the heading path at `level` and append the heading block."""
        nonlocal heading_path
        heading_path = heading_path[: level - 1] + [text]
        blocks.append(Block(type="heading", text=text, level=level, heading_path=list(heading_path),
                            anchor=Anchor(page=page_no, section_path=list(heading_path))))

    for idx, page in enumerate(doc):
        page_no = idx + 1
        lines = [ln for ln in pages_lines[idx]
                 if not (ln["edge"] and _signature(ln["text"]) in repeated)]
        chars = sum(len(ln["text"]) for ln in lines)
        tables = pages_tables[idx]
        damaged = page_no in page_damage or page_no in flags.get("page_errors", {})
        if chars < MIN_TEXT_CHARS and not tables:
            if page.get_images(full=True):
                status = "scanned"
            elif damaged:
                status = "unrecoverable"
            else:
                status = "blank"
            coverage.append(PageCoverage(page=page_no, status=status, chars=chars))
            continue
        coverage.append(PageCoverage(page=page_no, status="text", chars=chars))
        if damaged:
            # some text decoded before the damaged stream ended; the rest of the page is lost
            flags.setdefault("truncated_pages", []).append(page_no)

        items: list[tuple[float, str, object]] = []
        para: list[dict] = []

        def flush(para=para, items=items):
            """Move the pending paragraph lines into `items` as one item."""
            if para:
                items.append((para[0]["y0"], "para", list(para)))
                para.clear()

        prev = None
        for ln in lines:
            is_heading = (ln["bold"] and ln["size"] > body_size + 0.4 and len(ln["text"]) < 120
                          and not ln["edge"] and _LETTERS.search(ln["text"]) is not None)
            if is_heading:
                flush()
                items.append((ln["y0"], "heading", ln))
            elif ln["bold"] and ln["text"].upper() in SIGNAL_WORDS:
                flush()
                items.append((ln["y0"], "signal", ln))
            else:
                new_para = (prev is None or ln["block"] != prev["block"]
                            or ln["y0"] - prev["y1"] > ln["size"] * 0.8
                            or _STEP.match(ln["text"]))
                if new_para:
                    flush()
                para.append(ln)
            prev = ln
        flush()
        for t_no, (t, rows) in enumerate(tables):
            items.append((t.bbox[1], "table", (t_no, rows)))
        items.sort(key=lambda it: it[0])

        for _, kind, obj in items:
            if kind == "heading":
                text = obj["text"]
                m = _NUMBERED_HEADING.match(text)
                if m:
                    level = m.group(1).count(".") + 1
                else:
                    level = heading_sizes.index(obj["size"]) + 1 if obj["size"] in heading_sizes \
                        else 1
                push_heading(text, min(level, 4), page_no)
            elif kind == "signal":
                pending_signal = obj["text"].upper()
            elif kind == "para":
                text = " ".join(ln["text"] for ln in obj)
                text = re.sub(r"(\w)- (\w)", r"\1\2", text) if text.count("- ") else text
                anchor = Anchor(page=page_no, section_path=list(heading_path))
                first_word = text.split(" ", 1)[0].rstrip(":")
                if pending_signal:
                    blocks.append(Block(type="warning", text=f"{pending_signal}: {text}",
                                        anchor=anchor, heading_path=list(heading_path)))
                    pending_signal = None
                elif first_word in SIGNAL_WORDS or first_word == "IMPORTANT":
                    blocks.append(Block(type="warning", text=text, anchor=anchor,
                                        heading_path=list(heading_path)))
                elif _STEP.match(text):
                    blocks.append(Block(type="list_item", text=text, anchor=anchor,
                                        heading_path=list(heading_path),
                                        fields={"number": int(_STEP.match(text).group(1))}))
                else:
                    blocks.append(Block(type="paragraph", text=text, anchor=anchor,
                                        heading_path=list(heading_path)))
            else:
                t_no, rows = obj
                if not rows:
                    continue
                anchor = Anchor(page=page_no, section_path=list(heading_path), table=t_no)
                text = " ".join(c for r in rows for c in r if c)
                if len(rows) <= 2 and _SIGNAL_START.match(text):
                    blocks.append(Block(type="warning", text=text, anchor=anchor,
                                        heading_path=list(heading_path)))
                    continue
                header, body = rows[0], rows[1:]
                text = "\n".join(" | ".join(r) for r in rows)
                blocks.append(Block(type="table", text=text, anchor=anchor, header=header,
                                    rows=body, heading_path=list(heading_path)))

    # Title: the largest multi-word line on the first text page. Embedded PDF metadata is
    # unreliable in this corpus and is only recorded as a flag.
    first_text = next((i for i, c in enumerate(coverage) if c.status == "text"), None)
    if first_text is not None:
        # skip letter-spaced brand marks such as "N O R D K Y L"
        cands = [ln for ln in pages_lines[first_text]
                 if len(ln["text"].split()) >= 2 and _LETTERS.search(ln["text"])
                 and not re.fullmatch(r"(\w ){2,}\w", ln["text"])]
        page_lines = [ln for ln in pages_lines[first_text] if _LETTERS.search(ln["text"])
                      and not re.fullmatch(r"(\w ){2,}\w", ln["text"]) and not ln["edge"]]
        if page_lines:
            biggest = max(page_lines, key=lambda ln: ln["size"])
            title = biggest["text"]
            if len(title.split()) == 1:
                # model-number covers: "VRS-110" over "Service Manual"
                below = [ln for ln in page_lines if ln["y0"] > biggest["y0"]]
                if below:
                    nxt = max(below, key=lambda ln: (ln["size"], -ln["y0"]))
                    title = f"{title} {nxt['text']}"
        elif cands:
            title = max(cands, key=lambda ln: ln["size"])["text"]
    if title is None:
        title = next((b.text for b in blocks if b.type == "heading"), None)
    flags["metadata_title"] = meta_title
    if page_damage:
        flags["page_damage"] = page_damage
    return ExtractResult(path=rel_path, fingerprint=fingerprint, extractor="pdf",
                         extractor_version=VERSION, title=title, blocks=blocks, pages=coverage,
                         flags=flags)
