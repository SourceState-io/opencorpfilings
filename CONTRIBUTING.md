# Contributing to OpenCorpFilings

The public contract gives developers one path from a company to its original
filing documents. Provider implementations may differ internally, but they must
preserve the source's own identifiers, dates, form names and URLs.

## Add or improve a provider

1. Implement `FilingProvider` in `src/opencorpfilings/providers/` and register
   its explicit market route. Keep credentials in environment variables or
   constructor options; never store them in source records, tests or logs.
2. Declare only capabilities the adapter actually supports. A missing form,
   document, text representation or raw fact must raise a clear error or remain
   absent; do not fabricate parity with another source.
3. Add offline fixtures for issuer lookup, paginated filing listing, form/date
   mapping, one original document, provenance and an error path. Live regulator
   checks are optional and must be kept out of regular CI.
4. Add one documented example issuer, source coverage limits, authentication
   instructions and a capability-matrix row.
5. Keep downloads per company. `document.download()` and `filing.download()`
   save one selected document (or archive member or filing package);
   `FilingCollection.download(directory, ...)` saves a bounded selection of one
   company's filings (`filings(limit=...)`, `start=`/`end=`, or
   `all_history=True`) with a manifest. Do not add multi-company bulk or corpus
   acquisition, global accounting mappings, or proprietary research logic to
   this package.

Changes to `Entity`, `Filing`, `FilingDocument`, `FilingFact`, common errors,
ordering semantics or public signatures require a shared-contract review.
Provider-specific source mechanics can evolve within their adapter.

## Development

Install from this directory with `pip install -e .` in an existing Python
environment, then run `pytest tests`. The repository also tests the public
workflow with a fake provider so no regulator request is needed to check the
core contract.

For an optional source check after setting that provider's environment
variables, run `python examples/one_filing.py --market US` (or another
supported market). It fetches one example filing and one selected document.

Code contributed here must be original or carry a recorded compatible source
license and attribution. Source-data access rights are separate from software
licenses; a licensed scraper implementation does not itself grant permission
to query or redistribute a regulator's data. Review [source access and document
rights](SOURCE_ACCESS.md) when changing provider behavior.
