import re

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from copilot_ingest.models import Anchor, Block, ExtractResult, PageCoverage

VERSION = "docx-1"
_SIGNAL = re.compile(r"^(?:(DANGER|WARNING|CAUTION|NOTE|STOP|IMPORTANT)\b[:\s]"
                     r"|(Danger|Warning|Caution|Note|Important):)")
_STEP_HEADERS = {"step", "steg", "schritt", "stap", "#", "no.", "nr"}
_HEADING_LEVEL = re.compile(r"Heading (\d)")


_NUM_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
_NUM_STEP = re.compile(r"^(\d+(?:\.\d+)+)\t")


def _direct_heading_level(p: Paragraph, text: str) -> int | None:
    """Documents without heading styles: fully bold, short, numbered lines are headings."""
    runs = [r for r in p.runs if r.text.strip()]
    if not runs or len(text) > 100 or "\t" in text or not all(r.bold for r in runs):
        return None
    m = _NUM_HEADING.match(text)
    return m.group(1).count(".") + 1 if m else None


def _is_list(p: Paragraph) -> bool:
    """True for paragraphs with direct numbering or a `List...` style."""
    ppr = p._p.pPr
    return (ppr is not None and ppr.numPr is not None) or p.style.name.startswith("List")


def _num_id(p: Paragraph) -> str | None:
    """Numbering definition of a numbered paragraph (direct, else inherited from its style)."""
    for ppr in (p._p.pPr, p.style.element.pPr if p.style is not None else None):
        if ppr is not None and ppr.numPr is not None and ppr.numPr.numId is not None:
            return str(ppr.numPr.numId.val)
    return None


def extract(path, rel_path: str, fingerprint: str) -> ExtractResult:
    """Walk the body in document order into heading, step, warning, list, paragraph and table
    blocks; the whole document is reported as a single page."""
    d = docx.Document(str(path))
    blocks: list[Block] = []
    heading_path: list[str] = []
    title = None
    table_no = 0
    flags: dict = {}
    counters: dict[str, int] = {}

    def anchor(**kw) -> Anchor:
        """Anchor at the current heading path."""
        return Anchor(section_path=list(heading_path), **kw)

    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            text = p.text.strip()
            if not text:
                continue
            m = _HEADING_LEVEL.match(p.style.name)
            direct = None if m else _direct_heading_level(p, text)
            if m or p.style.name == "Title" or direct:
                level = int(m.group(1)) if m else direct or 1
                heading_path = heading_path[: level - 1] + [text]
                blocks.append(Block(type="heading", text=text, level=level, anchor=anchor(),
                                    heading_path=list(heading_path)))
            elif title is None and not blocks:
                title = text
            elif _NUM_STEP.match(text):
                number = _NUM_STEP.match(text).group(1)
                blocks.append(Block(type="procedure_step", text=text.replace("\t", " "),
                                    anchor=anchor(), heading_path=list(heading_path),
                                    fields={"number": number}))
            elif _SIGNAL.match(text):
                blocks.append(Block(type="warning", text=text, anchor=anchor(),
                                    heading_path=list(heading_path)))
            elif _is_list(p):
                fields = None
                if "Number" in p.style.name:
                    key = _num_id(p) or p.style.name
                    counters[key] = counters.get(key, 0) + 1
                    fields = {"number": counters[key]}
                    text = f"{counters[key]}. {text}"
                blocks.append(Block(type="list_item", text=text, anchor=anchor(),
                                    heading_path=list(heading_path), fields=fields))
            else:
                blocks.append(Block(type="paragraph", text=text, anchor=anchor(),
                                    heading_path=list(heading_path)))
        elif tag == "tbl":
            t = Table(child, d)
            rows = []
            for r in t.rows:
                cells, last = [], None
                for c in r.cells:
                    # merged cells repeat the same object; keep one copy
                    if c._tc is last:
                        continue
                    last = c._tc
                    cells.append(c.text.replace("\n", " / ").strip())
                rows.append(cells)
            rows = [r for r in rows if any(r)]
            if not rows:
                continue
            a = anchor(table=table_no)
            table_no += 1
            if len(rows) == 1 and len(rows[0]) == 1:
                text = rows[0][0]
                btype = "warning" if _SIGNAL.match(text) else "paragraph"
                blocks.append(Block(type=btype, text=text, anchor=a,
                                    heading_path=list(heading_path)))
                continue
            header, body = rows[0], rows[1:]
            if header and header[0].strip().lower() in _STEP_HEADERS:
                for r in body:
                    fields = dict(zip(header, r, strict=False))
                    text = " | ".join(f"{h}: {v}" for h, v in fields.items() if v)
                    num = re.match(r"\d+", r[0] or "")
                    blocks.append(Block(type="procedure_step", text=text, anchor=a,
                                        heading_path=list(heading_path), header=header,
                                        fields={**fields,
                                                "number": int(num.group()) if num else None}))
                continue
            if not blocks or (table_no == 1 and not heading_path):
                # metadata table at the top of controlled documents (document no., revision...)
                kv = {}
                for r in rows:
                    for i in range(0, len(r) - 1, 2):
                        kv[r[i]] = r[i + 1]
                flags["doc_properties"] = kv
            text = "\n".join(" | ".join(r) for r in rows)
            blocks.append(Block(type="table", text=text, anchor=a, header=header, rows=body,
                                heading_path=list(heading_path)))

    props = d.core_properties
    flags["core_title"] = props.title or None
    body = d.element.body
    flags["tracked_insertions"] = len(body.findall(".//" + qn("w:ins")))
    flags["tracked_deletions"] = len(body.findall(".//" + qn("w:del")))
    flags["comments"] = len(body.findall(".//" + qn("w:commentReference")))
    chars = sum(len(b.text) for b in blocks)
    return ExtractResult(path=rel_path, fingerprint=fingerprint, extractor="docx",
                         extractor_version=VERSION, title=title or props.title or None,
                         blocks=blocks, pages=[PageCoverage(page=1, status="text", chars=chars)],
                         flags=flags)
