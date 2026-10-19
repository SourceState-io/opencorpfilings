---
title: 'Brazil CVM company filings in Python'
description: 'Find Brazilian company filings by CVM code or CNPJ and download original IPE annual statements and material announcements as PDF.'
---

# Brazil (CVM)

<span class="ocf-tier ocf-tier--experimental">experimental</span> · market `BR` · provider `brazil_cvm`

## Start with an issuer

The [CVM open-data catalogue](https://dados.cvm.gov.br/dataset/cia_aberta-doc-ipe)
lists original periodic and event-driven IPE documents. No API key is required.
Use a CVM code, a CNPJ with or without punctuation, or an exact registry name:

```python
from opencorpfilings import Company, search_companies

matches = search_companies("Petrobras", market="BR")
petrobras = Company(matches[0])
# Equivalent: Company("9512", market="BR")
# Equivalent: Company("33.000.167/0001-01", market="BR")
report = petrobras.filings(form="annual", limit=1).latest()
print(report.period_end, report.filing_date)
report.primary_document.download("petrobras-annual.pdf")
```

With the `pdf` extra, `report.primary_document.page(1).text` reads the first
page. Search uses the official company register, prioritizing active issuers
and exact trade-name matches; tickers are not inferred.
Multiple trading-venue rows for one CVM code become one issuer candidate,
with the original rows retained in metadata. Active CVM registrations also appear in
`find_company()` and the browser [Find a company](../find/index.md) page.
Search legal/trade names, CVM codes or CNPJs; no B3 ticker mapping is inferred.
Inactive registrations remain accessible through market-specific source search.
Registry membership does not guarantee an available annual IPE report.

## Forms and originals

| Request | Source classification |
|---|---|
| `annual` | `Tipo` equals `Demonstrações Financeiras Anuais Completas` |
| `current` | `Categoria` equals `Fato Relevante` |
| `other` | remaining IPE documents |
| exact native label | matches `Tipo` or `Categoria` |

Each selected record has one source-linked original PDF. The separate
structured DFP and ITR datasets are outside this route: there are no raw
XBRL facts, quarterly convenience category or standardized financial statements.
An annual financial statement is not necessarily the issuer's narrative annual report.

## Dates, versions and bounds

`filing_date` is `Data_Entrega` (delivery date); `start=` and `end=` filter
that date, inclusively. `period_end` is `Data_Referencia` for annual
statements only. Other reference dates remain raw metadata. `published_at`
is unset. Ordering is newest delivery date first, then source version.

`AP - Apresentação` marks an original; `RA - Reapresentação` marks a
restatement. Category requests select originals by default; pass
`include_amendments=True` to include restatements. Unknown flags stay `None`.

A filing key combines delivery archive year, `Protocolo_Entrega` and
`Versao`, for example `2026:009512IPE311220250151708258-10:1`. Where CVM
leaves the delivery protocol empty, `rad-<numProtocolo>` uses the source's
RAD download key; the empty original field is preserved. `get_filing(key)`
checks the selected issuer's CVM code and CNPJ in that year's metadata.

Discovery reads at most five delivery-year metadata archives by default;
`Company(..., max_years=10)` raises that bound (maximum 20). Explicit date
ranges exceeding it raise an error. The CVM catalogue describes a five-year
current window and older archives since 2003; older archives are not all
subject to the current update policy. Metadata is cached for one provider
session; reopen the company to refresh it. Only selected originals download.

The data host publishes a ten-second crawl delay, which the default
transport observes. This can make the first request slower than other routes.
CVM updates current and previous-year metadata weekly, so discovery is not
a real-time announcement feed. See [source access and attribution](../reference/source-access.md).
