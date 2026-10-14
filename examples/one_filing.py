"""Fetch one filing and one original document through the public API.

Examples:
    python examples/one_filing.py --market US
    python examples/one_filing.py --market UK
    python examples/one_filing.py --market FI
    python examples/one_filing.py --market ES
    python examples/one_filing.py --market PL
    python examples/one_filing.py --market LV
    python examples/one_filing.py --market HR
    python examples/one_filing.py --market NL
    python examples/one_filing.py --market DK
    python examples/one_filing.py --market SK
    python examples/one_filing.py --market MT
    python examples/one_filing.py --market CY
    python examples/one_filing.py --market HU
    python examples/one_filing.py --market LI
"""

from __future__ import annotations

import argparse
import sys

from opencorpfilings import Company, UnsupportedCapabilityError


EXAMPLES = {
    "US": ("AAPL", "annual", "2024-01-01", None),
    "UK": ("00185647", "annual", "2026-01-01", None),
    "KR": ("00378363", "annual", "2025-06-18", "2025-06-18"),
    "JP": ("7203", "annual", "2026-06-10", "2026-06-10"),
    "FI": ("KONE Oyj", "annual", None, None),
    "FR": ("969500U43TVR8CCVBJ97", "annual", "2025-05-14", "2025-05-14"),
    "ES": ("A-48010615", "annual", None, None),
    "SE": ("502017-7753", "annual", None, None),
    "PL": ("mBank Spółka Akcyjna", "annual", None, None),
    "NL": ("ASML Holding N.V.", "annual", "2026-01-01", None),
    "DK": ("DK-61056416", "annual", "2026-01-01", None),
}


def _prepare_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")


def main() -> None:
    _prepare_output()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market", choices=EXAMPLES, required=True)
    args = parser.parse_args()
    identifier, form, start, end = EXAMPLES[args.market]
    with Company(identifier, market=args.market) as company:
        filing = company.filings(form=form, start=start, end=end, limit=1).latest()
        print("entity:", company.entity.name, company.entity.entity_id)
        print("filing:", filing.filing_id, filing.filing_type_raw, filing.filing_date)
        print("order basis:", company.filings(form=form).order_basis)
        print("source:", filing.source_url)
        print("documents:", [(doc.filename, doc.media_type) for doc in filing.documents])
        document = filing.primary_document
        print("selected document:", document.source_url, len(document.download()), "bytes")
        if document.media_type == "application/zip":
            print("archive members:", len(document.members))
        try:
            print("text characters:", len(filing.text()))
        except UnsupportedCapabilityError:
            print("text: unsupported for the selected source format")


if __name__ == "__main__":
    main()
