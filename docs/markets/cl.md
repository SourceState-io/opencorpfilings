---
title: 'Chile CMF financial reports and XBRL in Python'
description: 'Find Chilean issuers by RUT and retrieve original CMF IFRS financial reports, PDFs, XBRL packages and source-located raw facts.'
---

# Chile (CMF)

<span class="ocf-tier ocf-tier--experimental">experimental</span> · market `CL` · provider `chile_cmf`

## Start with an issuer

The [CMF public issuer register](https://www.cmfchile.cl/institucional/mercados/consulta.php?mercado=V&Estado=VI&entidad=RVEMI)
provides active securities issuers and their IFRS financial reports. No API
key is required. Use the listed RUT, its numeric body, or an exact issuer name:

```python
from opencorpfilings import Company, search_companies

matches = search_companies("Copec", market="CL")
copec = Company(matches[0])
# Equivalent: Company("90690000-9", market="CL")
report = copec.filings(form="annual", limit=1).latest()
print(report.period_end)                     # 2025-12-31 in the October 2026 check
report.primary_document.download("copec-annual.pdf")
facts = report.facts                        # original classic XBRL occurrences
print(len(facts))                           # 10,274 in that check
```

Active securities issuers also appear in `find_company()` and the browser
[Find a company](../find/index.md) page, searchable by name or RUT.
`search_companies(..., market="CL")` queries the source register directly.
Registry membership does not guarantee a financial report for every period.
This route covers the securities-issuer register and its IFRS portal, rather
than every CMF-supervised institution or a separate banking reporting system.

## Forms and documents

| Request | Report period |
|---|---|
| `annual` | December |
| `interim` | June |
| `quarterly` | March, June and September; June keeps normalized type `INTERIM` |

Consolidated reports are the default. `Company(..., consolidated=False)`
selects individual reports. The route submits the public financial-report
selector, then verifies the issuer RUT, printed period and balance type
before exposing its original links. Unfiled periods are skipped.

The primary document is **Estados financieros (PDF)**. Where supplied,
**Estados financieros (XBRL)** is a ZIP with the classic instance and
taxonomy files. Other source annexes remain separate documents. `report.facts`
reads the original `.xbrl` instance, retaining contexts, units, dimensions,
filed values, entry paths and source URLs. It does not fetch external taxonomies
or normalize accounting concepts. PDF text and pages require the `pdf` extra.

## Dates, identifiers and bounds

`order_basis` is `report_period`; `period_end` comes from the source's
verified month and year. **The portal's “Fecha de consulta” is the query
time**, not the filing time. `filing_date` and `published_at` remain `None`.
Date filters and amendment exclusion raise `UnsupportedCapabilityError`;
the portal selection does not establish submission history or correction status.

The filing key identifies a portal selection: `<RUT body>:<YYYYMM>:<C or I>`,
for example `90690000:202512:C`. It is not an announcement receipt number.
`get_filing(key)` queries that selection directly. Provenance retains the
public form URL and the submitted period/balance fields. Document filenames
are generated from that selection; they are not claimed to be issuer filenames.

Discovery checks at most 20 completed report periods from the source's year
selector. `Company(..., max_periods=40)` raises the bound (maximum 100).
Reaching it before satisfying a request raises an error. Report selections
are reused within a provider session; reopen the company for fresh links.

CMF supplies signed public download links. These can expire: reselect the
report to obtain current links. The adapter follows only source-supplied CMF
download URLs, uses an identifying OpenCorpFilings User-Agent and paces
requests. Attribute CMF and retain original URLs when using the results;
see [source access and rights](../reference/source-access.md).
