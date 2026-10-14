"""Measure bounded issuer-to-filing metadata coverage without downloading files.

Example:
    python benchmarks/coverage_probe.py US AAPL MSFT NVDA --form annual

Print one JSON line per issuer and a summary. This developer benchmark lists
only the latest filing and its document metadata for each issuer. It does not
download original documents or enable a disk cache. A provider whose document
listing delivers original bytes is reported without enumerating documents.
Providers still apply
their own request pacing; run a small sample and respect source limits.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from time import perf_counter

from opencorpfilings import Company, FilingNotFoundError


MAX_ISSUERS = 20


def _emit(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=True, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("market")
    parser.add_argument("identifiers", nargs="+")
    parser.add_argument("--source", help="explicit national or esef_index source route")
    parser.add_argument("--form", default="annual")
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    if len(args.identifiers) > MAX_ISSUERS:
        parser.error(f"at most {MAX_ISSUERS} issuers per run")

    if args.market.upper() == "US" and not os.getenv("OPENCORPFILINGS_SEC_USER_AGENT"):
        name, email = os.getenv("SEC_ACC_NAME"), os.getenv("SEC_ACC_EMAIL")
        if name and email:
            os.environ["OPENCORPFILINGS_SEC_USER_AGENT"] = f"{name} {email}"

    counts: Counter[str] = Counter()
    for identifier in args.identifiers:
        started = perf_counter()
        row = {"market": args.market.upper(), "identifier": identifier, "source": args.source}
        stage = "entity"
        try:
            options = {"source": args.source} if args.source else {}
            with Company(identifier, market=args.market, **options) as company:
                entity = company.entity
                row["entity_id"] = entity.entity_id
                row["entity_name"] = entity.name
                row["entity_source_url"] = entity.source_url
                stage = "filing"
                try:
                    filing = company.filings(form=args.form, start=args.start, end=args.end, limit=1).latest()
                except FilingNotFoundError:
                    filing = None
                if filing is None:
                    row["status"] = "no_filing"
                else:
                    row["filing_id"] = filing.filing_id
                    row["filing_date"] = str(filing.filing_date) if filing.filing_date else None
                    row["filing_source_url"] = filing.source_url
                    stage = "documents"
                    if company.provider.supports("document_listing_embeds_originals"):
                        row["status"] = "document_listing_requires_originals"
                    else:
                        documents = filing.documents
                        row["document_count"] = len(documents)
                        row["document_media_types"] = sorted({
                            document.media_type or "unknown" for document in documents
                        })
                        row["unknown_media_count"] = sum(
                            not document.media_type for document in documents
                        )
                        row["provenance"] = bool(
                            filing.source_url and documents
                            and all(document.source_url for document in documents)
                        )
                        row["status"] = "ok" if documents and row["provenance"] else "incomplete"
        except Exception as exc:
            row.update(status="error", failed_stage=stage, error_type=type(exc).__name__)
        row["seconds"] = round(perf_counter() - started, 3)
        counts[row["status"]] += 1
        _emit(row)

    _emit({"status": "summary", "market": args.market.upper(), "total": len(args.identifiers),
           "counts": dict(counts)})
    return 0 if counts == {"ok": len(args.identifiers)} else 1


if __name__ == "__main__":
    raise SystemExit(main())
