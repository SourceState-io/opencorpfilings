"""Build the data file behind the docs site's "Find a company" page.

    OPENCORPFILINGS_SEC_USER_AGENT="Name contact@example.com" python scripts/build_find_index.py docs/find/companies.json

It downloads the same official lists `find_company()` uses and writes them as one
compact JSON file for in-browser search. Only lists whose terms allow republishing
with attribution are included (SOURCE_ACCESS.md); the UK has no such list, so the
page links to Companies House's own search instead. A list that fails to download
fails the build, so a published page never silently loses a market.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from opencorpfilings.directory import _fetch_rows, _tier
from opencorpfilings.transport import HttpTransport

#: what each list's terms ask a republisher to say
SOURCES = {
    "sec": ("SEC EDGAR company_tickers_exchange.json", "https://www.sec.gov/files/company_tickers_exchange.json"),
    "edinet": ("EDINET code list (FSA), under Public Data License 1.0; processed by OpenCorpFilings",
               "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"),
    "france_lei": ("DILA/AMF Info-Financière, codes-lei dataset",
                   "https://www.info-financiere.gouv.fr/explore/dataset/codes-lei/"),
    "france_isin": ("DILA/AMF Info-Financière, liste-code-isi dataset",
                    "https://www.info-financiere.gouv.fr/explore/dataset/liste-code-isi/"),
    "esef": ("filings.xbrl.org (XBRL International) ESEF index", "https://filings.xbrl.org/"),
}


def main(target: str) -> None:
    with HttpTransport(min_interval=0.25) as transport:
        rows, status = _fetch_rows(transport)
    failed = {name: entry["error"] for name, entry in status.items() if not entry.get("ok", True)}
    if failed:
        sys.exit(f"lists failed to download, not publishing: {failed}")
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "built_at": built,
        "sources": [{"name": name, "url": url, "retrieved": built[:10]} for name, url in SOURCES.values()],
        "fields": ["name", "market", "identifier", "source", "tier", "tickers", "isins", "lei", "aliases"],
        "rows": [[row["name"], row["market"], row["identifier"], row["source"], _tier(row), row["tickers"],
                  row["isins"], row["lei"], row["aliases"]] for row in rows],
    }
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rows)} companies -> {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/find/companies.json")
