---
title: 'Peru SMV financial reports and XBRL in Python'
description: 'Search Peruvian main-market issuers and retrieve original financial statements, PDF notes and raw XBRL facts from the public SMV portal.'
---

# Peru (SMV)

<span class="ocf-tier ocf-tier--experimental">experimental</span> · market `PE` · provider `peru_smv`

## Find an issuer and its reports

The [SMV public portal](https://www.smv.gob.pe/SIMV/Default.aspx) has a
financial-information selector under **Emisores → Mercado Principal**.
No API key is required:

```python
from opencorpfilings import Company, search_companies

matches = search_companies("Alicorp", market="PE")
company = Company(matches[0])
# Equivalent: Company("73", market="PE")
report = company.filings(form="annual", limit=1).latest()
report.primary_document.download("alicorp-statements.pdf")
facts = report.facts
print(len(facts))  # 1,004 in the October 2026 check
```

The identifier is SMV's **issuer selector ID**, not a RUC, ticker or XBRL
context identifier. Exact selector names also resolve. This route covers the
main-market issuer selector, including foreign issuers; it does not cover every
Peruvian company, inactive issuer or supervised participant. Use
`search_companies()` for this market. Peru is not in `find_company()` or the
browser directory; the selector's redistribution terms have not been established.

## Annual and interim originals

`annual` selects **Anual**. `interim` and `quarterly` both select
**Intermedio**, keeping normalized type `INTERIM` and the source's Roman
quarter in `provider_metadata["source_quarter"]`. Consolidated reports are
the default; `Company(..., consolidated=False)` selects individual reports.

Rows are grouped by **N° Expediente** within the issuer/year/type/balance
selection. The adapter checks the returned controls and every row's issuer
name. It submits both the source's company name field and numeric selector,
using fresh public form state for each query. A paginated selection raises
an error instead of returning an incomplete case list.

Where provided, **Estados Financieros y Dictamen** is the primary PDF.
The generic **Informacion Financiera** upload is also retained; foreign
issuers can file an original home-market annual report under that label.
Some cases provide the full statements as original XBRL and a separate
**Notas a los Estados Financieros** PDF. In those cases XBRL is primary;
the notes remain an exhibit, not the complete financial statements. The
portal's rendered financial-detail view is not an uploaded original and
is not listed as one. Inspect `report.documents` before assuming a PDF.
Document filenames are generated from source GUIDs because the listing
does not supply original filenames. Selected originals can stream to disk.

`report.facts` preserves classic XBRL occurrences, contexts, units, dimensions,
values and source locations. Several source files declare UTF-8 but contain
Windows-1252 bytes. For those files the parser uses Windows-1252 decoding and
records `parser_encoding` and an `encoding_note` on each fact's provenance.
The downloaded original bytes and their hash remain unchanged. Other malformed
XML raises `ParseError`; external taxonomies are not fetched and accounting
concepts are not normalized. PDF text requires the `pdf` extra and a text layer.

## Dates, ordering and bounds

`filing_date` is the source's **Fecha de Presentación** calendar date.
The clock is preserved raw; its timezone is not invented, so `published_at`
stays `None`. `period_end` is also `None`: the query year/quarter alone does
not establish an issuer's exact fiscal closing date. XBRL facts retain their
own explicit context dates.

`order_basis` is `report_year`: newest selected report year first, then
presentation date and expediente within that year. A later submission of an
older year's report can therefore appear after a newer report year.
`start=`/`end=` filtering is unsupported because bounded report-year browsing
cannot guarantee discovery of every submission within a filing-date window.
Amendments are not classified; amendment exclusion is unsupported.

The filing key combines `<selector ID>:<year>:<A or T>:<C or I>:<expediente>`,
for example `73:2025:A:C:2026015256`. The native expediente alone remains
`provenance.source_id`. `get_filing(key)` reselects and verifies that case.
Discovery checks five source report years by default. Increase
`Company(..., max_years=10)` up to 30; reaching the bound raises an error.
Report selections are reused within a provider session; reopen the company
to refresh them. See [source access and rights](../reference/source-access.md).
