---
title: 'Argentina CNV company filings in Python'
description: 'Search Argentine issuers by name or CUIT and download original financial-statement PDFs from CNV and the AIF public submission service.'
---

# Argentina (CNV)

<span class="ocf-tier ocf-tier--experimental">experimental</span> · market `AR` · provider `argentina_cnv`

## Find an issuer and its statements

The [CNV issuer register](https://www.cnv.gov.ar/SitioWeb/Reportes/ListadoSociedadesEmisorasPorRegimen)
supplies company names and CUITs. No API key is required. Search the live
register, then pass the result to `Company`:

```python
from opencorpfilings import Company, search_companies

matches = search_companies("Central Puerto", market="AR")
company = Company(matches[0])
# Equivalent: Company("33-65030549-9", market="AR")
report = company.filings(form="annual", limit=1).latest()
print(report.period_end, report.filing_date)
report.primary_document.download("central-puerto-statements.pdf")
```

An exact register name or an eleven-digit CUIT, with or without hyphens,
also resolves the company. Duplicate register rows for different regulatory
regimes become one candidate; their categories and statuses remain in metadata.
This is an issuer register, not every Argentine company. Tickers are not inferred.
Use `search_companies()` for this market; Argentina is not in the cross-market
`find_company()` index or the browser directory.

## Forms and original attachments

The route reads the company's **Estados Contables** section. It maps the
source's numeric periodicity: `1` to `annual`, `2` to `interim`, and `3` to
`quarterly`. The complete source description remains `filing_type_raw`.
Individual and consolidated submissions remain distinct; no balance preference
is imposed. Rows explicitly marked as related-company reports are excluded.

`report.documents` lists the original PDF attachments of the AIF financial
submission. **ABEstadoContable** is the financial-statements document;
management reports, auditor reports and other attachments retain their source
property and filename. CNV's separate generated spreadsheet is not presented
as an issuer original. There are no raw XBRL facts on this route.

Install the `pdf` extra for page text. Some originals are scanned and have no
extractable text; no OCR is performed. Source descriptions and attachment
contents can disagree. The adapter retains the submitted metadata and original
file rather than rewriting either or guaranteeing the issuer's classification.
The attachment's opaque source hash is retained as `source_hash`; its algorithm
is unspecified and it is not treated as a verified SHA-256. `document.sha256()`
computes the hash of the bytes actually downloaded.

## Dates, identifiers and bounds

`filing_date` is the date shown in CNV's company listing. `start=` and `end=`
filter it inclusively. `period_end` is the explicit **Fecha Cierre**.
The source clock has no published timezone, so `published_at` stays `None`.
Listing order is newest filing date, source clock and presentation UUID.
Amendment status is unknown; requesting `include_amendments=False` raises an error.

The filing ID is the UUID from the public AIF presentation URL. Its separate
numeric presentation number remains `provenance.source_id`.
`company.get_filing(uuid)` verifies the presentation's CUIT. A direct lookup
does not establish a filing date, so `filing_date` is `None` unless the same
provider session already discovered that submission in a dated listing.

Discovery defaults to five calendar years ending today. Supply date bounds
for older windows and increase `Company(..., max_years=10)` where needed
(maximum 30). This is bounded discovery, not a completeness claim for all history.

CNV's public attachment service issues a temporary download grant. The adapter
uses the public site's GET-grant/POST-download protocol; grants never become
document URLs or provenance. A selected PDF is buffered before saving, so
Argentina does not advertise streamed downloads. Requests are paced and only
selected attachments download. See [source access and rights](../reference/source-access.md).
