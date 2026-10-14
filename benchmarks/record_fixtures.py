"""Record one issuer's real discovery responses per supported route into tests/fixtures/recorded/.

Example:
    python benchmarks/record_fixtures.py US FR

Runs entity resolution, one filing selection and document listing; it does not
download originals. Writes `responses.json`, gzip bodies and `expected.json`, a
snapshot of what the library returned. Review `expected.json` against the
source before committing: the replay test freezes it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path

import httpx

try:
    from recording import RecordingTransport
except ImportError:  # imported as benchmarks.record_fixtures by the replay test
    from benchmarks.recording import RecordingTransport
from opencorpfilings import Company
from opencorpfilings.transport import HttpTransport

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "recorded"


def _scenarios():
    from opencorpfilings.providers.companies_house import CompaniesHouseProvider
    from opencorpfilings.providers.edinet import EDINETProvider
    from opencorpfilings.providers.esef import ESEFProvider
    from opencorpfilings.providers.france_oam import FranceOAMProvider
    from opencorpfilings.providers.open_dart import OpenDARTProvider
    from opencorpfilings.providers.sec import SECProvider

    agent = os.environ["OPENCORPFILINGS_SEC_USER_AGENT"]
    return {
        # Powell Industries: a small filer keeps the submissions JSON small.
        "US": ("80420", "US", lambda t: SECProvider(user_agent=agent, transport=t), {"form": "annual"}),
        "UK": ("00502851", "UK", lambda t: CompaniesHouseProvider(transport=t), {"form": "annual"}),
        # One EDINET day: Toyota's annual report was filed 2026-06-10.
        "JP": ("7203", "JP", lambda t: EDINETProvider(transport=t),
               {"form": "annual", "start": "2026-06-10", "end": "2026-06-10"}),
        # An explicit end: without one, Open DART sends today's date and the recorded key would expire.
        "KR": ("005930", "KR", lambda t: OpenDARTProvider(transport=t),
               {"form": "annual", "start": "2026-01-01", "end": "2026-10-08"}),
        "FR": ("969500XXRPGD7HCAFA90", "FR", lambda t: FranceOAMProvider(transport=t), {"form": "annual"}),
        "ESEF-AT": ("5299006UDSEJCTTEJS30", "AT", lambda t: ESEFProvider(market="AT", transport=t), {"form": "annual"}),
    }


def snapshot(filing) -> dict:
    documents = filing.documents
    primary = filing.primary_document
    return {
        "entity_id": filing.entity_id,
        "filing_id": filing.filing_id,
        "filing_type_raw": filing.filing_type_raw,
        "filing_type_normalized": filing.filing_type_normalized,
        "period_end": filing.period_end.isoformat() if filing.period_end else None,
        "filing_date": filing.filing_date.isoformat() if filing.filing_date else None,
        "amendment": filing.amendment,
        "language": filing.language,
        "document_count": len(documents),
        "primary_filename": primary.filename,
        "primary_role": primary.role,
        "roles": dict(sorted(Counter(document.role or "none" for document in documents).items())),
    }


def record(route: str) -> dict:
    identifier, market, build, query = _scenarios()[route]
    directory = ROOT / route
    shutil.rmtree(directory, ignore_errors=True)
    recorder = RecordingTransport(directory)
    transport = HttpTransport(min_interval=0.25, client=httpx.Client(transport=recorder, follow_redirects=True))
    with Company(identifier, market=market, provider=build(transport)) as company:
        result = {"identifier": identifier, "market": market, "query": query,
                  **snapshot(company.filings(**query).latest())}
    recorder.save()
    (directory / "expected.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("routes", nargs="+")
    args = parser.parse_args()
    for route in args.routes:
        print(route, json.dumps(record(route), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
