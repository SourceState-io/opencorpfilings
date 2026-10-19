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

## Dependency updates

Dependabot checks Python dependencies and GitHub Actions monthly. Routine
minor and patch version updates are grouped into one PR per ecosystem;
major upgrades remain individual PRs. Dependency security alerts stay enabled.
Version-update scheduling and grouping do not change security-alert delivery.
Updates require maintainer review; automatic merging is disabled.

For an update:

1. Read the upstream release notes, including breaking changes and runner
   requirements. Check each major upgrade separately, even when several
   reviewed upgrades are incorporated into one maintenance change.
2. Run the offline tests, README checks and strict documentation build. All
   package, base-install and documentation CI jobs must pass. CI builds the
   wheel and source archive and verifies installation with only declared
   dependencies on Python 3.11–3.13, plus base installs on Windows and Linux.
3. Changes to the Pages actions also need a successful real deployment:
   directory refresh, strict site build, artifact upload and Pages publication.
   Check the live site and company search after deployment. If publication
   fails, fix or revert the workflow before considering the update complete.

The monthly dependency checks are separate from the documentation site's
company-directory refresh, which runs weekly. See the
[contributor guide](https://sourcestate-io.github.io/opencorpfilings/contributing/#dependency-updates)
for local verification commands.

Code contributed here must be original or carry a recorded compatible source
license and attribution. Source-data access rights are separate from software
licenses; a licensed scraper implementation does not itself grant permission
to query or redistribute a regulator's data. Review [source access and document
rights](SOURCE_ACCESS.md) when changing provider behavior.
