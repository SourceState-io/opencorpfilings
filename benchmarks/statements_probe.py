"""Experiment: find the three primary statements among an iXBRL report's filed tables.

Example:
    python benchmarks/statements_probe.py --out statements.jsonl

Rule, declared 2026-10-09 before the run: a table's tagged concepts classify
it. Cash-flow concepts make it the cash-flow statement; otherwise total assets
(or total liabilities and equity) make it the balance sheet; otherwise revenue
or profit make it the income statement. Equity alone does not make a balance
sheet (that is the statement of changes in equity). Tables with fewer than
eight tagged values are ignored. Per kind, the table with the most tagged
values is picked. For each pick the script prints the table's first rows so a
person can judge it; the judgement is recorded in BENCHMARKS.md.
"""

from __future__ import annotations

import argparse
import json
import re
from time import perf_counter

from bs4 import BeautifulSoup

from opencorpfilings import Company
from opencorpfilings.packages import best_reports

KINDS = {
    "cashflow": re.compile(r":(CashFlowsFromUsedInOperatingActivities\w*|NetCashProvidedByUsedInOperatingActivities\w*"
                           r"|NetCashFlowsFromUsedInOperatingActivities\w*|NetCashFlowFromOperatingActivities\w*"
                           r"|CashFlowsFromOperatingActivities\w*)$"),
    "balance": re.compile(r":(Assets|LiabilitiesAndStockholdersEquity|EquityAndLiabilities|TotalAssets\w*"
                          r"|NetAssetsLiabilities\w*|TotalAssetsLessCurrentLiabilities)$"),
    "income": re.compile(r":(Revenues?|RevenueFromContract\w*|NetSales\w*|Turnover\w*|OperatingRevenue\w*"
                         r"|ProfitLoss\w*|NetIncomeLoss|ProfitLossAttributableToOwnersOfParent\w*|OrdinaryIncome\w*)$"),
}
MIN_TAGGED = 8
TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)
TAG = re.compile(r"<ix:nonFraction\b[^>]*\bname=\"([^\"]+)\"", re.I)

SAMPLE = [
    ("US", "AAPL", {"form": "annual"}, None), ("US", "LIN", {"form": "annual"}, None),
    ("US", "DE", {"form": "annual"}, None), ("US", "CROX", {"form": "annual"}, None),
    ("US", "PNC", {"form": "annual"}, None),
    ("UK", "00185647", {"form": "annual"}, None),
    ("AT", "5299006UDSEJCTTEJS30", {"form": "annual"}, "esef_index"),
    ("IT", "WOCMU6HCI0OJWNPRZS33", {"form": "annual"}, "esef_index"),
    ("NO", "OW6OFBNCKXC4US5C7523", {"form": "annual"}, "esef_index"),
    ("PT", "2138003319Y7NM75FG53", {"form": "annual"}, "esef_index"),
    ("LU", "2EULGUTUI56JI9SAL165", {"form": "annual"}, "esef_index"),
    ("FR", "969500KMUQ2B6CBAF162", {"form": "annual"}, "esef_index"),
    ("DK", "529900VSWLQF0O3GA946", {"form": "annual"}, "esef_index"),
    ("FI", "743700WUIPC24LVMLO66", {"form": "annual"}, "esef_index"),
    ("JP", "7203", {"form": "annual", "start": "2026-06-10", "end": "2026-06-10"}, None),
    ("JP", "6501", {"form": "annual", "start": "2026-06-01", "end": "2026-06-30"}, None),
    ("JP", "2809", {"form": "annual", "start": "2026-01-15", "end": "2026-03-15"}, None),
    ("JP", "8306", {"form": "annual", "start": "2026-06-01", "end": "2026-06-30"}, None),
    ("FR", "969500XXRPGD7HCAFA90", {"form": "annual"}, None),
]


def report_html(filing) -> str:
    document = filing.primary_document
    if filing.jurisdiction == "JP":
        parts = [m for m in document.members
                 if "/publicdoc/" in m.entry_path.lower() and m.entry_path.lower().endswith(".htm")]
        return "\n".join(member.html() for member in sorted(parts, key=lambda m: m.entry_path))
    if document.media_type == "application/zip":
        return best_reports(document)[0].html()
    return document.html()


def classify(names: list[str]) -> str | None:
    for kind in ("cashflow", "balance", "income"):
        if any(KINDS[kind].search(name) for name in names):
            return kind
    return None


def first_rows(table_html: str, count: int = 4) -> list[str]:
    soup = BeautifulSoup(table_html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        text = " | ".join(cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"]))
        text = " ".join(text.split())
        if text.strip(" |"):
            rows.append(text[:140])
        if len(rows) >= count:
            break
    return rows


def probe(market, identifier, query, source):
    started = perf_counter()
    options = {"source": source} if source else {}
    filing = Company(identifier, market=market, **options).filings(**query).latest()
    tables = TABLE.findall(report_html(filing))
    picks = {}
    for index, table in enumerate(tables):
        names = TAG.findall(table)
        if len(names) < MIN_TAGGED:
            continue
        kind = classify(names)
        if kind and (kind not in picks or len(names) > picks[kind]["tagged"]):
            picks[kind] = {"index": index, "tagged": len(names), "rows": first_rows(table)}
    return {"market": market, "identifier": identifier, "filing_id": filing.filing_id, "tables": len(tables),
            "picks": picks, "seconds": round(perf_counter() - started, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    with open(args.out, "w", encoding="utf-8") as out:
        for market, identifier, query, source in SAMPLE:
            try:
                row = probe(market, identifier, query, source)
            except Exception as exc:
                row = {"market": market, "identifier": identifier, "error": f"{type(exc).__name__}: {exc}"[:200]}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(json.dumps({k: row.get(k) for k in ("market", "identifier", "tables", "error", "seconds")},
                             ensure_ascii=False))
            for kind, pick in row.get("picks", {}).items():
                print(f"   {kind:8} table {pick['index']} ({pick['tagged']} tagged): {pick['rows'][:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
