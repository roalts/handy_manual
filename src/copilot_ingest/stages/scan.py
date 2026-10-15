"""Scanned pages: two independent reads and a value cross-check (research.md R5).

Read A is Tesseract (two page-segmentation modes, free, local). Read B is a hosted vision model
asked to transcribe verbatim; it supplies the text and structure. A critical value (number with
unit, range, table value, part number, thread, model code) is kept only if read A shows the same
value on the line aligned with it; otherwise it is replaced by a withheld marker and sent to review.
The reads are cached per file; the cross-check is recomputed on every build.
"""
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from pydantic import BaseModel
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from copilot_ingest.artifacts import load_artifact, save_artifact
from copilot_ingest.models import Anchor, Block, ExtractResult, ReviewItem
from copilot_ingest.providers.base import ProviderUnavailable
from copilot_ingest.review import Decisions, item_id

VERSION = "scan-1"
PROMPT_OCR = "ocr-transcribe-1"
TESSERACT_MODES = (4, 6)
VIEW_DPI = 200
OCR_DPI = 300
LABEL_MATCH = 75  # rapidfuzz partial_ratio for aligning a vision line with a Tesseract line


class ScanPage(BaseModel):
    page: int
    image: str  # PNG for viewing and for the vision read, relative to the data dir
    tesseract: dict[str, str]  # mode -> text
    vision: dict  # raw structured transcription


class ScanResult(BaseModel):
    fingerprint: str
    model: str
    pages: list[ScanPage]


_PROMPT = """Transcribe this scanned page exactly as printed.

Rules:
- Copy every character as printed: digits, decimal commas or points, units, spacing, umlauts.
- Never guess, complete or correct anything. If a character cannot be read, write [?] in its place.
- Return content blocks in reading order. Keep line breaks inside a block as \\n.
- heading: section titles; level 1 for "3 ..." and level 2 for "3.2 ...".
- table: header = cells of the header row, rows = body rows; one string per cell, line breaks
  inside a cell as \\n; text = the caption printed above the table (empty if none).
- warning: safety notices (GEFAHR, WARNUNG, VORSICHT, ACHTUNG, DANGER, WARNING, CAUTION).
- list_item: one numbered or bulleted item per block.
- paragraph: everything else.
- page_furniture: running header and footer lines (company line, document code, page number).
For non-table blocks set header and rows to null; for non-heading blocks set level to null."""

_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["blocks", "page_furniture"],
    "properties": {
        "blocks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "level", "text", "header", "rows"],
            "properties": {
                "type": {"type": "string",
                         "enum": ["heading", "paragraph", "list_item", "warning", "table"]},
                "level": {"type": ["integer", "null"]},
                "text": {"type": "string"},
                "header": {"type": ["array", "null"], "items": {"type": "string"}},
                "rows": {"type": ["array", "null"],
                         "items": {"type": "array", "items": {"type": "string"}}},
            }}},
        "page_furniture": {"type": "array", "items": {"type": "string"}},
    },
}


# --- the two reads (cached) --------------------------------------------------------------------

def _tesseract(png_gray_tiff: bytes, mode: int) -> str:
    """Tesseract text (German + English) of a grayscale TIFF in one page-segmentation mode."""
    # Leptonica on this machine cannot open some paths; stdin works.
    out = subprocess.run(["tesseract", "stdin", "stdout", "-l", "deu+eng", "--psm", str(mode)],
                         input=png_gray_tiff, capture_output=True, check=True)
    return out.stdout.decode("utf-8", "replace")


def read_pages(pdf_path: Path, r: ExtractResult, data_dir: Path, provider, model: str
               ) -> ScanResult | None:
    """Both reads for every scanned page, cached by file fingerprint. None if the vision read is
    unavailable (no key, offline, or out of credits): the pages then stay 'scanned'."""
    cached = load_artifact(r.fingerprint, "scan", f"{VERSION}-{PROMPT_OCR}-{model}", ScanResult)
    if cached is not None:
        return cached
    if provider is None or not model:
        return None
    doc = pymupdf.open(pdf_path)
    img_dir = data_dir / "page_images" / r.fingerprint
    img_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    try:
        for cov in r.pages:
            if cov.status != "scanned":
                continue
            page = doc[cov.page - 1]
            png = page.get_pixmap(dpi=VIEW_DPI).tobytes("png")
            png_path = img_dir / f"page-{cov.page}.png"
            png_path.write_bytes(png)
            gray = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
            tiff = gray.pil_tobytes(format="TIFF")
            tess = {str(m): _tesseract(tiff, m) for m in TESSERACT_MODES}
            vision = provider.transcribe_image(model, png, _PROMPT, _SCHEMA, PROMPT_OCR)
            pages.append(ScanPage(page=cov.page, image=str(png_path.relative_to(data_dir)),
                                  tesseract=tess, vision=vision))
    except ProviderUnavailable:
        return None
    result = ScanResult(fingerprint=r.fingerprint, model=model, pages=pages)
    save_artifact(r.fingerprint, "scan", f"{VERSION}-{PROMPT_OCR}-{model}", result)
    return result


# --- cross-check (recomputed every build) ------------------------------------------------------

_NUM = r"\d+(?:[.,]\d+)?"
_UNIT = (r"(?:mm|m³/h|m3/h|m\^3/h|m²|m|bar|°C|°F|kW|N-?m|Nm|1/min|rpm|min-1|Hz|kg|g|dB\(A\)|%|"
         r"V|A|l|L|h)")
_EXPR = rf"{_NUM}(?:\s*(?:-|–|bis|to)\s*{_NUM})?\s*{_UNIT}(?![\w])"
_CODE = r"(?:[A-Z]{2,4}-\d{2,4}(?:-\d+)?|\d{2}-\d{4}|M\d{1,2}|DN\s?\d{2,3}|PN\s?\d{1,3})"
_VALUE = re.compile(rf"(?<![\w.,])(?:{_EXPR}|{_CODE})(?![\w])")
_CELL_VALUE = re.compile(rf"(?<![\w.,])(?:{_EXPR}|{_CODE}|{_NUM})(?![\w])")
_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")
_MODEL = re.compile(r"\b[A-Z]{3}-\d{3}\b")
_NOISE = re.compile(r"[\[\]|{}]")


def _tokens(text: str) -> list[str]:
    """Model codes whole, everything else by its digits: Tesseract often fuses a code's letters
    with neighbouring noise, so letters cannot be compared reliably."""
    text = _NOISE.sub(" ", text)
    models = _MODEL.findall(text)
    return models + [t.replace(",", ".") for t in _DIGITS.findall(_MODEL.sub(" ", text))]


def correct_models(text: str, fleet_models: set[str], log: list, page: int,
                   read_by: str = "vision") -> str:
    """Model codes one edit away from a fleet model are corrected and logged (HGP-200)."""
    def fix(m):
        """The code itself, or the single fleet model one edit away from it."""
        code = m.group(0)
        if code in fleet_models:
            return code
        near = [f for f in fleet_models if Levenshtein.distance(code, f) == 1]
        if len(near) == 1:
            entry = {"page": page, "read_by": read_by, "read": code, "corrected": near[0]}
            if entry not in log:
                log.append(entry)
            return near[0]
        return code
    return _MODEL.sub(fix, text)


def _lines(text: str) -> list[str]:
    """Stripped non-empty lines."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _is_furniture(line: str, furniture: list[str]) -> bool:
    """Whether a Tesseract line matches a running header or footer the vision read reported.
    Short lines never count, since partial matching would hit them by chance."""
    return len(line) > 15 and any(fuzz.partial_ratio(line, f) >= 80 for f in furniture)


def _context(probe: str, tess_lines: dict[str, list[str]]) -> list[str] | None:
    """Tokens on the Tesseract line(s) aligned with `probe`, merged over modes."""
    probe = probe.strip()
    if len(probe) < 4:
        return None
    found = None
    min_len = max(6, int(len(probe) * 0.6))  # partial_ratio scores any tiny line as a match
    for lines in tess_lines.values():
        if not lines:
            continue
        scores = [fuzz.partial_ratio(probe, ln) if len(ln) >= min_len else 0 for ln in lines]
        best = max(range(len(lines)), key=scores.__getitem__)
        if scores[best] < LABEL_MATCH:
            continue
        found = (found or []) + _tokens(" ".join(lines[best:best + 2]))
    return found


@dataclass
class PageCheck:
    blocks: list[Block] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    checked: int = 0
    verified: int = 0
    withheld: int = 0
    reviewer: int = 0


def _check_text(text: str, context: list[str] | None, pattern: re.Pattern, make_item,
                decisions: Decisions | None, pc: PageCheck, page: int, label: str) -> str:
    """`text` with each value not confirmed by the aligned Tesseract tokens replaced by the
    reviewer's value or a withheld marker; updates the counts and review items in `pc`."""
    out, last = [], 0
    for k, m in enumerate(pattern.finditer(text)):
        expr = m.group(0)
        pc.checked += 1
        pool = list(context or [])
        ok = context is not None
        for t in _tokens(expr):
            if t in pool:
                pool.remove(t)
            else:
                ok = False
        if ok:
            pc.verified += 1
            continue
        item = make_item(k, expr, label, context)
        decided = decisions.get(item) if decisions else None
        out.append(text[last:m.start()])
        if isinstance(decided, str) and decided != "withhold":
            out.append(decided)
            pc.reviewer += 1
        else:
            out.append(f"[[unverified:{item_id(item)}|page={page}]]")
            pc.withheld += 1
            pc.review.append(item)
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def _flat(cell: str) -> str:
    """Multi-line cell text joined into one line."""
    return " ".join(part.strip() for part in cell.split("\n") if part.strip())


def check_page(sp: ScanPage, r: ExtractResult, fleet_models: set[str],
               decisions: Decisions | None, corrections: list,
               heading_path: list[str]) -> PageCheck:
    """Blocks for one scanned page from the vision read, with critical values cross-checked
    against Tesseract. Updates `heading_path` in place so it carries over to the next page."""
    pc = PageCheck()
    furniture = sp.vision.get("page_furniture", [])
    tess = {m: [ln for ln in _lines(correct_models(t, fleet_models, corrections, sp.page,
                                                   f"tesseract-{m}"))
                if not _is_furniture(ln, furniture)]
            for m, t in sp.tesseract.items()}

    def item_for(bi, ri, ci):
        """Review-item builder for values at one block, row and cell position."""
        def make(k, expr, label, context):
            """Review item for the k-th unverified value at this position."""
            return ReviewItem(
                kind="ocr_value_mismatch", path=r.path,
                anchor={"page": sp.page, "block": bi, "row": ri, "cell": ci, "value": k},
                field="value",
                candidates={"vision": expr, "label": label,
                            "tesseract": " ".join(context) if context else None},
                reason=("Tesseract shows a different value on the aligned line" if context
                        else "no Tesseract line aligned with this text"),
                fingerprint=r.fingerprint, stage="scan")
        return make

    table_no = 0
    for bi, b in enumerate(sp.vision.get("blocks", [])):
        kind = b["type"]
        text = correct_models(b["text"], fleet_models, corrections, sp.page)
        if kind == "heading":
            level = b.get("level") or 1
            heading_path[:] = heading_path[:level - 1] + [_flat(text)]
            pc.blocks.append(Block(type="heading", text=_flat(text), level=level,
                                   heading_path=list(heading_path),
                                   anchor=Anchor(page=sp.page, section_path=list(heading_path))))
            continue
        anchor = Anchor(page=sp.page, section_path=list(heading_path))
        if kind == "table":
            header = [_flat(c) for c in (b.get("header") or [])]
            rows = []
            for ri, row in enumerate(b.get("rows") or []):
                cells = [correct_models(c, fleet_models, corrections, sp.page) for c in row]
                label = cells[0].split("\n")[0] if cells else ""
                # position numbers and fault codes are too short to align on
                probe = label if len(re.findall(r"[^\W\d]", label)) >= 6 else \
                    " ".join(c.split("\n")[0] for c in cells)
                context = _context(probe, tess)
                out = [_check_text(_flat(cells[0]), context, _VALUE, item_for(bi, ri, 0),
                                   decisions, pc, sp.page, label)] if cells else []
                for ci, c in enumerate(cells[1:], 1):
                    out.append(_check_text(_flat(c), context, _CELL_VALUE, item_for(bi, ri, ci),
                                           decisions, pc, sp.page, label))
                rows.append(out)
            anchor.table = table_no
            table_no += 1
            body = "\n".join(" | ".join(x) for x in [header, *rows])
            caption = _flat(text)
            pc.blocks.append(Block(type="table", text=(caption + "\n" if caption else "") + body,
                                   header=header, rows=rows, anchor=anchor,
                                   heading_path=list(heading_path)))
            continue
        lines = []
        for li, line in enumerate(text.split("\n")):
            context = _context(line, tess)
            lines.append(_check_text(line, context, _VALUE, item_for(bi, li, None), decisions,
                                     pc, sp.page, line))
        btype = kind if kind in ("paragraph", "list_item", "warning") else "paragraph"
        pc.blocks.append(Block(type=btype, text="\n".join(lines).strip(), anchor=anchor,
                               heading_path=list(heading_path)))
    return pc


@dataclass
class ScanCheck:
    result: ExtractResult
    review: list[ReviewItem]
    stats: dict


def apply(r: ExtractResult, scan: ScanResult, fleet_models: set[str],
          decisions: Decisions | None) -> ScanCheck:
    """A copy of `r` with scanned pages replaced by checked transcriptions."""
    out = r.model_copy(deep=True)
    by_page = {sp.page: sp for sp in scan.pages}
    corrections: list = []
    heading_path: list[str] = []
    review, per_page, blocks = [], {}, []
    for cov in out.pages:
        if cov.page in by_page:
            pc = check_page(by_page[cov.page], r, fleet_models, decisions, corrections,
                            heading_path)
            blocks += pc.blocks
            review += pc.review
            cov.status = "text"
            cov.chars = sum(len(b.text) for b in pc.blocks)
            per_page[cov.page] = {"checked": pc.checked, "verified": pc.verified,
                                  "withheld": pc.withheld, "reviewer": pc.reviewer}
        else:
            blocks += [b for b in r.blocks if b.anchor.page == cov.page]
    out.blocks = blocks
    furniture = [line for sp in scan.pages for line in sp.vision.get("page_furniture", [])]
    out.flags.update({
        "ocr_pages": sorted(by_page), "ocr_model": scan.model,
        "ocr_images": {str(sp.page): sp.image for sp in scan.pages},
        "ocr_corrections": corrections, "page_furniture": sorted(set(furniture))})
    totals = {k: sum(p[k] for p in per_page.values())
              for k in ("checked", "verified", "withheld", "reviewer")}
    return ScanCheck(result=out, review=review,
                     stats={"pages": len(per_page), **totals, "corrections": corrections,
                            "per_page": per_page})
