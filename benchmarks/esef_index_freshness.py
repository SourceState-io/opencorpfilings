"""Measure how far the ESEF index lags: indexed reports per country for two fiscal years.

Example:
    python benchmarks/esef_index_freshness.py --latest 2025 --previous 2024

Counts December year-end annual reports (period_end YYYY-12-31) per index
country and prints a Markdown table for the README. The previous year stands
in for the population, so the ratio shows how much of the latest year has
arrived; it is not regulator coverage, which the index does not claim. One
count request per country and year, paced at four per second.
"""

from __future__ import annotations

import argparse
import time
from datetime import date

import httpx

from opencorpfilings.providers.esef import INDEX_COUNTRIES

API = "https://filings.xbrl.org/api/filings"


def count(client: httpx.Client, country: str, year: int) -> int:
    response = client.get(API, params={"filter[country]": country, "filter[period_end]": f"{year}-12-31",
                                       "page[size]": 1})
    response.raise_for_status()
    time.sleep(0.25)
    return int(response.json()["meta"]["count"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest", type=int, required=True)
    parser.add_argument("--previous", type=int, required=True)
    args = parser.parse_args()
    rows = []
    with httpx.Client(timeout=30) as client:
        for country in sorted(INDEX_COUNTRIES):
            rows.append((country, count(client, country, args.previous), count(client, country, args.latest)))
    total_previous = sum(row[1] for row in rows)
    total_latest = sum(row[2] for row in rows)
    print(f"Measured {date.today().isoformat()}: December year-end reports in the index.\n")
    print(f"| Country | FY{args.previous} | FY{args.latest} | FY{args.latest} / FY{args.previous} |")
    print("|---|---:|---:|---:|")
    for country, previous, latest in rows:
        ratio = f"{latest / previous:.0%}" if previous else "-"
        print(f"| {country} | {previous:,} | {latest:,} | {ratio} |")
    print(f"| **All** | {total_previous:,} | {total_latest:,} | {total_latest / total_previous:.0%} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
