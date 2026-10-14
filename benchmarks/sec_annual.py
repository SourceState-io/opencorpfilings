"""Time the same single-filing SEC workflow in OpenCorpFilings or EdgarTools.

Run each implementation in a fresh process. Set OPENCORPFILINGS_SEC_USER_AGENT,
EDGAR_IDENTITY, or both SEC_ACC_NAME and SEC_ACC_EMAIL before running. This
script does not enable a disk cache or download a corpus.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from importlib.metadata import version
from pathlib import Path
from time import perf_counter


def _identity() -> str:
    identity = os.getenv("OPENCORPFILINGS_SEC_USER_AGENT") or os.getenv("EDGAR_IDENTITY")
    if identity:
        return identity
    name, email = os.getenv("SEC_ACC_NAME"), os.getenv("SEC_ACC_EMAIL")
    if name and email:
        return f"{name} {email}"
    raise SystemExit("Set OPENCORPFILINGS_SEC_USER_AGENT, EDGAR_IDENTITY, or SEC_ACC_NAME and SEC_ACC_EMAIL")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", choices=("opencorpfilings", "edgartools"))
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--form", choices=("annual", "quarterly"), default="annual")
    parser.add_argument("--text-output", type=Path)
    parser.add_argument("--edgartools-path", type=Path, help="isolated install target for EdgarTools")
    args = parser.parse_args()
    identity = _identity()
    if args.edgartools_path is not None:
        sys.path.insert(0, str(args.edgartools_path))

    if args.library == "edgartools":
        import edgar

        edgar.set_identity(identity)
        start = perf_counter()
        company = edgar.Company(args.ticker)
        looked_up = perf_counter()
        filing = company.get_filings(form={"annual": "10-K", "quarterly": "10-Q"}[args.form]).latest()
        selected = perf_counter()
        content = filing.text()
        finished = perf_counter()
        accession = filing.accession_number
        package_version = version("edgartools")
    else:
        from opencorpfilings import Company

        os.environ["OPENCORPFILINGS_SEC_USER_AGENT"] = identity
        start = perf_counter()
        with Company(args.ticker, market="US") as company:
            _ = company.entity
            looked_up = perf_counter()
            filing = company.filings(form=args.form).latest()
            selected = perf_counter()
            content = filing.text()
            finished = perf_counter()
            accession = filing.filing_id
        package_version = version("opencorpfilings")

    if args.text_output is not None:
        args.text_output.write_text(content, encoding="utf-8")
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", content.lower())
    print({
        "library": args.library,
        "version": package_version,
        "form": args.form,
        "accession": accession,
        "characters": len(content),
        "word_tokens": len(words),
        "lookup_seconds": round(looked_up - start, 3),
        "select_seconds": round(selected - looked_up, 3),
        "text_seconds": round(finished - selected, 3),
        "total_seconds": round(finished - start, 3),
    })


if __name__ == "__main__":
    main()
