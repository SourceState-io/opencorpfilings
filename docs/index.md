---
title: 'Company filings in Python'
description: 'Find and download company filings from SEC EDGAR, Companies House, EDINET, AMF and ESEF with one Python API and source provenance.'
hide:
  - navigation
---

# OpenCorpFilings { .ocf-sr-only }

<div class="ocf-hero" markdown>
![OpenCorpFilings](assets/brand/opencorpfilings-logo-tagline.svg#only-light)
![OpenCorpFilings](assets/brand/opencorpfilings-logo-tagline-on-dark.svg#only-dark)
</div>

OpenCorpFilings finds a public company's filings at the regulator that holds
them and returns the original documents through one Python API. Every filing
keeps the regulator's own identifiers, dates and URLs as provenance.

The library normalizes **access**, not accounting meaning. It does not build
comparable financial statements, map concepts across taxonomies or download
filings in bulk across companies. A download covers one company and needs an
explicit bound.

!!! info "Release status"
    Version 1.1.0, Python 3.11 to 3.13, MIT
    licensed. Install from GitHub; the package is not published to PyPI.
    See [Getting started](getting-started.md) to install it.

## A filing in five lines

```python
from opencorpfilings import Company

apple = Company("AAPL", market="US", user_agent="Your Name you@example.com")
filing = apple.filings(form="annual").latest()
print(filing)
filing.primary_document.download("apple-10k.htm")
```

```text
<Filing 0000320193-25-000079 10-K ANNUAL period=2025-09-27 filed=2025-10-31 US/sec>
```

That is Apple's 10-K for fiscal 2025, saved byte for byte from EDGAR. The
same calls work on every route; only the identifier and the credentials
change:

```python
Company("00185647", market="UK").filings(form="annual").latest()            # Companies House number
Company("969500XXRPGD7HCAFA90", market="FR").filings(form="annual").latest() # LEI
Company("7203", market="JP").filings(form="annual", start="2026-06-01", end="2026-06-30").latest()
```

```text
<Filing MzUzNDA4NzU2M2FkaXF6a2N4 AA ANNUAL period=2026-02-28 filed=2026-07-21 UK/companies_house>
<Filing 370:623156_20260408 300005 ANNUAL filed=2026-04-08 FR/france_oam>
<Filing S100Y8NY 120 ANNUAL period=2026-03-31 filed=2026-06-10 JP/edinet>
```

Each regulator keeps its own filing ID and form code (`10-K`, `AA`, `300005`,
`120`). `form="annual"` selects across them; the native code stays on the
filing as `filing_type_raw`. Outputs on this site were captured from the live
sources in October 2026; a later run returns later filings.

## Coverage at a glance

| Market | Source | Identify a company by | Forms | Credentials | Tier |
|---|---|---|---|---|---|
| [US](markets/us.md) | SEC EDGAR | ticker, CIK | annual, quarterly, interim, current, prospectus, ownership, other | identifying User-Agent | <span class="ocf-tier ocf-tier--supported">supported</span> |
| [UK](markets/uk.md) | Companies House | company number, exact company name | annual, other | none; optional API key | <span class="ocf-tier ocf-tier--supported">supported</span> |
| [JP](markets/jp.md) | EDINET | four-digit securities code, EDINET code | annual, interim, quarterly, current, other | API key | <span class="ocf-tier ocf-tier--supported">supported</span> |
| [FR](markets/fr.md) | AMF / DILA Info-Financiere OAM | LEI, exact source issuer name | annual, interim, quarterly | none | <span class="ocf-tier ocf-tier--supported">supported</span> |
| [21 countries](markets/esef.md) | ESEF index (filings.xbrl.org) | LEI | annual | none | <span class="ocf-tier ocf-tier--limited">limited</span> |
| [BR](markets/br.md) | CVM IPE | CVM code, CNPJ, exact name | annual, current, other | none | <span class="ocf-tier ocf-tier--experimental">experimental</span> |
| [CL](markets/cl.md) | CMF IFRS | RUT, exact name | annual, interim, quarterly | none | <span class="ocf-tier ocf-tier--experimental">experimental</span> |
| [KR](markets/experimental.md#korea-open-dart) | Open DART | stock code, corporation code | annual, interim, quarterly, other | API key | <span class="ocf-tier ocf-tier--experimental">experimental</span> |
| [ES, NL, DK, SE, PL, FI](markets/experimental.md) | national officially appointed mechanisms (OAMs) | varies by market | annual, interim (SE also quarterly; PL annual only) | none | <span class="ocf-tier ocf-tier--experimental">experimental</span> |

The [market overview](markets/index.md) has the full route matrix and the
tier definitions. `provider_info()` and `ocf markets` return the same profile
for any route without credentials or network access.

## Where to go next

- [Getting started](getting-started.md): install, credentials, your first filing.
- [Guide](guide/finding-companies.md): finding companies, selecting filings,
  documents, text, tables and facts, per-company downloads, the `ocf` command.
- [Markets](markets/index.md): a page per source with identifiers, form
  codes, dates and known gaps.
- [Identifiers, dates and provenance](concepts/identifiers-dates-provenance.md):
  what each field on a filing means.
- [API reference](reference/api.md), generated from the public names.
- [Stability](stability.md): what the version number promises.
