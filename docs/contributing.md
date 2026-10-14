---
title: 'Contribute to OpenCorpFilings'
description: 'Set up development, run offline tests and contribute source adapters that preserve filing identities, original documents and provenance.'
---

# Contributing

The public contract gives developers one path from a company to its original
filing documents. Provider implementations may differ internally, but they
must preserve the source's own identifiers, dates, form names and URLs. The
full guidance is
[CONTRIBUTING.md](https://github.com/sourcestate-io/opencorpfilings/blob/main/CONTRIBUTING.md)
in the repository.

## Development setup

```bash
git clone https://github.com/sourcestate-io/opencorpfilings.git
cd opencorpfilings
pip install -e ".[dev]"
pytest tests
```

The tests make no live regulator requests. `tests/test_recorded_sources.py`
replays real recorded responses for the supported routes, and the public
workflow is also tested with a fake provider. For an optional live check after
setting a provider's environment variables:

```bash
python examples/one_filing.py --market US
```

It fetches one example filing and one selected document. Live checks stay out
of regular CI.

## Adding or improving a route

1. Implement `FilingProvider` in `src/opencorpfilings/providers/` and register
   its explicit market route. Keep credentials in environment variables or
   constructor options; never store them in source records, tests or logs.
2. Declare only capabilities the adapter actually supports. A missing form,
   document, text representation or raw fact must raise a clear error or
   remain absent; do not fabricate parity with another source.
3. Add offline fixtures for issuer lookup, paginated filing listing,
   form/date mapping, one original document, provenance and an error path.
4. Add one documented example issuer, source coverage limits, authentication
   instructions and a capability-matrix row.
5. Keep downloads per company. Do not add multi-company bulk or corpus
   acquisition, global accounting mappings or proprietary research logic.

Changes to `Entity`, `Filing`, `FilingDocument`, `FilingFact`, common errors,
ordering semantics or public signatures require a shared-contract review.
Provider-specific source mechanics can evolve within their adapter.

Code contributed here must be original or carry a recorded compatible source
license and attribution. Source-data access rights are separate from software
licenses: a licensed scraper does not itself grant permission to query or
redistribute a regulator's data. Review
[Source access and rights](reference/source-access.md) when changing provider
behavior.

## Writing your own provider

!!! warning "Provisional"
    `FilingProvider` is a provisional extension point. Its hook methods are
    outside the version 1 [stability promise](stability.md) and may change in
    a minor release.

To serve a source the package does not, subclass `FilingProvider` and pass an
instance as `Company(..., provider=...)`. Four methods are abstract:

| Method | Returns |
|---|---|
| `resolve_entity(identifier)` | one `Entity` for a market-scoped identifier |
| `iter_filings(entity, *, form, start, end, include_amendments, limit)` | `Filing` objects newest first in `order_basis`, already filtered |
| `list_documents(filing)` | the filing's `FilingDocument` objects |
| `download_document(document)` | the original bytes of one document |

Optional hooks have defaults that raise `UnsupportedCapabilityError` or fall
back: `search_entities`, `resolve_search_result`, `get_filing`,
`get_primary_document`, `save_document`, `extract_text`, `raw_facts`,
`extract_sections`, `filing_date_for_filter` and `filing_matches_form`.

Class attributes declare the route profile that `Company.filings()` checks
before calling the provider: `name`, `market`, `regulator`, `capabilities`
(names from the provider's capability set, such as `entity_lookup`,
`filing_discovery`, `document_download`, `text`, `raw_facts`), `tier`,
`identifier_kinds`, `forms`, `native_forms`, `date_filters`,
`identifies_amendments`, `order_basis`, `auth` and `coverage_note`.

A minimal provider, run offline:

```python
from datetime import date

from opencorpfilings import (Company, Entity, Filing, FilingDocument, FilingProvider,
                             Provenance)


class ExampleProvider(FilingProvider):
    name = "example"
    market = "XX"
    regulator = "Example Regulator"
    capabilities = frozenset({"entity_lookup", "filing_discovery", "document_download"})
    identifier_kinds = ("registry number",)
    forms = ("annual",)
    native_forms = False

    def resolve_entity(self, identifier):
        url = f"https://registry.example/companies/{identifier}"
        return Entity(entity_id=identifier, name="Example plc", jurisdiction=self.market,
                      provider=self.name, source_url=url,
                      provenance=Provenance(self.name, self.regulator, self.market, url, identifier))

    def iter_filings(self, entity, *, form=None, start=None, end=None,
                     include_amendments=True, limit=None):
        url = f"https://registry.example/filings/{entity.entity_id}-2025"
        yield Filing(
            filing_id=f"{entity.entity_id}-2025", entity_id=entity.entity_id,
            jurisdiction=self.market, provider=self.name, regulator=self.regulator,
            source_url=url, provenance=Provenance(self.name, self.regulator, self.market, url,
                                                  f"{entity.entity_id}-2025"),
            filing_type_raw="AR", filing_type_normalized="ANNUAL", filing_date=date(2026, 3, 31),
        )

    def list_documents(self, filing):
        url = f"{filing.source_url}/report.pdf"
        return [FilingDocument(
            document_id=f"{filing.filing_id}:report", filing_id=filing.filing_id,
            filename="report.pdf", source_url=url,
            provenance=Provenance(self.name, self.regulator, self.market, url, f"{filing.filing_id}:report"),
            media_type="application/pdf", is_primary=True, role="report",
        )]

    def download_document(self, document):
        return b"%PDF-1.7 example"


with Company("12345", market="XX", provider=ExampleProvider()) as company:
    filing = company.filings(form="annual").latest()
    print(company, filing)
    print(filing.primary_document, filing.primary_document.download())
```

```text
<Company 12345 'Example plc' XX/example> <Filing 12345-2025 AR ANNUAL filed=2026-03-31 XX/example>
<FilingDocument report.pdf application/pdf report primary> b'%PDF-1.7 example'
```

The common layer verifies what the provider returns: every filing must match
the selected entity's ID and market and the provider's name, its provenance
must name the same provider and market, and a filing outside the requested
form, dates or amendment filter raises `ProviderError`. Documents must name
their filing and carry provenance whose URL equals their `source_url`. A
provider you pass in does not emit `ExperimentalRouteWarning`, and the caller
owns its connection: leaving the `Company` context does not close it.
