import re

from bs4 import BeautifulSoup, NavigableString, Tag

from copilot_ingest.models import Anchor, Block, ExtractResult, PageCoverage

VERSION = "html-1"
_MACRO = re.compile(r"confluence-information-macro-(warning|note|information|tip)")
_LABEL = {"warning": "WARNING", "note": "NOTE", "information": "INFO", "tip": "TIP"}
_WS = re.compile(r"\s+")


def _text(el: Tag) -> str:
    """Element text with whitespace collapsed to single spaces."""
    return _WS.sub(" ", el.get_text(" ", strip=True)).strip()


def extract(path, rel_path: str, fingerprint: str) -> ExtractResult:
    """Extract a Confluence page export: main content only, info macros become warnings, the
    space prefix is stripped from the title, page metadata and breadcrumbs go to flags."""
    soup = BeautifulSoup(path.read_bytes(), "lxml")
    root = soup.select_one("#main-content") or soup.select_one(".wiki-content") or soup.body
    title = soup.title.get_text(strip=True) if soup.title else None
    if title and " : " in title:
        title = title.split(" : ", 1)[1]
    flags: dict = {}
    meta = soup.select_one(".page-metadata")
    if meta:
        flags["page_metadata"] = _text(meta)
    crumbs = soup.select_one("#breadcrumb-section")
    if crumbs:
        flags["breadcrumbs"] = _text(crumbs)

    blocks: list[Block] = []
    heading_path: list[str] = []
    table_no = 0

    def add(btype, text, **kw):
        """Append a block under the current heading path; empty text is dropped."""
        if text:
            blocks.append(Block(type=btype, text=text, heading_path=list(heading_path),
                                anchor=Anchor(section_path=list(heading_path),
                                              table=kw.pop("table", None)), **kw))

    def walk(el: Tag):
        """Emit blocks for recognised children and recurse into other containers. Bare text
        becomes a paragraph only at the root; inside nested wrappers it is dropped."""
        nonlocal heading_path, table_no
        for child in el.children:
            if isinstance(child, NavigableString):
                text = _WS.sub(" ", str(child)).strip()
                if text and el is root:
                    add("paragraph", text)
                continue
            if not isinstance(child, Tag):
                continue
            classes = " ".join(child.get("class") or [])
            if child.name in ("script", "style") or "toc-macro" in classes \
                    or "expand-control" in classes.split():
                continue
            m = _MACRO.search(classes)
            if m and "confluence-information-macro-body" not in classes and \
                    "confluence-information-macro-icon" not in classes:
                add("warning", f"{_LABEL[m.group(1)]}: {_text(child)}")
                continue
            if re.fullmatch(r"h[1-6]", child.name):
                level = int(child.name[1])
                heading_path = heading_path[: level - 1] + [_text(child)]
                add("heading", _text(child), level=level)
            elif child.name == "p":
                add("paragraph", _text(child))
            elif child.name in ("ol", "ul"):
                for n, li in enumerate(child.find_all("li", recursive=False), start=1):
                    fields = {"number": n} if child.name == "ol" else None
                    add("list_item", (f"{n}. " if fields else "") + _text(li), fields=fields)
            elif child.name == "table":
                rows = [[_text(c) for c in tr.find_all(["th", "td"])] for tr in
                        child.find_all("tr")]
                rows = [r for r in rows if any(r)]
                if rows:
                    add("table", "\n".join(" | ".join(r) for r in rows), header=rows[0],
                        rows=rows[1:], table=table_no)
                    table_no += 1
            elif child.name in ("pre", "blockquote"):
                add("paragraph", _text(child))
            else:
                walk(child)

    walk(root)
    return ExtractResult(path=rel_path, fingerprint=fingerprint, extractor="html",
                         extractor_version=VERSION, title=title, blocks=blocks,
                         pages=[PageCoverage(page=1, status="text",
                                             chars=sum(len(b.text) for b in blocks))],
                         flags=flags)
