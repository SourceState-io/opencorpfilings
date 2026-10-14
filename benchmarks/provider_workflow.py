"""Time one source-preserving filing workflow, split by public API stage.

Example:
    python benchmarks/provider_workflow.py UK 00185647 --form annual --start 2026-01-01

Run one market and one filing per invocation. This script does not enable a
disk cache or download a corpus. Configure any required provider credentials
through the same environment variables as the public library.
"""

from __future__ import annotations

import argparse
import json
import os
from time import perf_counter

from opencorpfilings import Company, OpenCorpFilingsError, UnsupportedCapabilityError

REPLACEMENT = chr(0xFFFD)  # a decoded byte that was not valid text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("market")
    parser.add_argument("identifier")
    parser.add_argument("--source", help="explicit source route, such as oam or esef_index")
    parser.add_argument("--form", default="annual")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--facts", action="store_true", help="also read raw facts from this filing")
    args = parser.parse_args()

    if args.market.upper() == "US" and not os.getenv("OPENCORPFILINGS_SEC_USER_AGENT"):
        name, email = os.getenv("SEC_ACC_NAME"), os.getenv("SEC_ACC_EMAIL")
        if name and email:
            os.environ["OPENCORPFILINGS_SEC_USER_AGENT"] = f"{name} {email}"

    started = perf_counter()
    options = {"source": args.source} if args.source else {}
    report = {"market": args.market.upper(), "source": args.source, "form": args.form}
    stage = "entity"
    try:
        with Company(args.identifier, market=args.market, **options) as company:
            entity = company.entity
            report["entity_id"] = entity.entity_id
            report["entity_name"] = entity.name
            report["entity_source_url"] = entity.source_url
            resolved = perf_counter()
            stage = "latest"
            filing = company.filings(form=args.form, start=args.start, end=args.end, limit=1).latest()
            report["filing_id"] = filing.filing_id
            report["filing_type_raw"] = filing.filing_type_raw
            report["filing_type_normalized"] = filing.filing_type_normalized
            report["filing_date"] = str(filing.filing_date) if filing.filing_date else None
            report["period_end"] = str(filing.period_end) if filing.period_end else None
            report["amendment"] = filing.amendment
            selected = perf_counter()
            stage = "documents"
            documents = filing.documents
            enumerated = perf_counter()
            document = filing.primary_document
            report["document_id"] = document.document_id
            report["media_type"] = document.media_type
            report["role"] = document.role
            stage = "download"
            content = document.download()
            downloaded = perf_counter()
            stage = "text"
            pdf_page_count = None
            pdf_pages_with_text = None
            try:
                body = filing.text()
                text_status, text_characters = ("available" if body.strip() else "empty"), len(body)
                if body:
                    readable = sum((ch.isprintable() or ch.isspace()) and ch != REPLACEMENT for ch in body)
                    report["printable_ratio"] = round(readable / len(body), 4)
                if document.media_type == "application/pdf":
                    pages = document.pages
                    pdf_page_count = len(pages)
                    pdf_pages_with_text = sum(bool(page.text.strip()) for page in pages)
            except UnsupportedCapabilityError:
                text_status, text_characters = "unsupported", None
            extracted = perf_counter()
            fact_count = None
            if args.facts:
                stage = "facts"
                try:
                    fact_count = len(filing.facts)
                except UnsupportedCapabilityError:
                    fact_count = None
            finished = perf_counter()
    except OpenCorpFilingsError as exc:
        print(json.dumps({
            **report, "status": "error", "failed_stage": stage,
            "error_type": type(exc).__name__, "error": str(exc)[:300],
            "elapsed_seconds": round(perf_counter() - started, 3),
        }, sort_keys=True))
        return 1

    print(json.dumps({
        **report, "status": "ok", "document_count": len(documents),
        "original_bytes": len(content), "text_characters": text_characters,
        "text_status": text_status, "pdf_page_count": pdf_page_count,
        "pdf_pages_with_text": pdf_pages_with_text,
        "raw_fact_count": fact_count,
        "provenance": bool(filing.source_url and document.source_url and document.provenance.source_url),
        "seconds": {
            "entity": round(resolved - started, 3),
            "latest": round(selected - resolved, 3),
            "documents": round(enumerated - selected, 3),
            "download": round(downloaded - enumerated, 3),
            "text": round(extracted - downloaded, 3),
            "facts": round(finished - extracted, 3) if args.facts else None,
            "total": round(finished - started, 3),
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
