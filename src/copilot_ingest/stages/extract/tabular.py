import pandas as pd

from copilot_ingest.models import ExtractResult, PageCoverage

VERSION = "tabular-1"


def extract(path, rel_path: str, fingerprint: str, source_cfg: dict) -> ExtractResult:
    """Read every column as text; parsing of dates and numbers happens per source convention."""
    df = pd.read_csv(path, sep=source_cfg.get("delimiter", ","), dtype=str,
                     keep_default_na=False, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    records = [{"_row": i + 2, **{k: v.strip() for k, v in row.items()}}
               for i, row in enumerate(df.to_dict(orient="records"))]
    return ExtractResult(path=rel_path, fingerprint=fingerprint, extractor="tabular",
                         extractor_version=VERSION, title=path.name, records=records,
                         pages=[PageCoverage(page=1, status="text", chars=path.stat().st_size)],
                         flags={"columns": list(df.columns), "rows": len(records)})
