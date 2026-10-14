---
title: 'Company filing sources and market coverage'
description: 'Compare supported, limited and experimental filing sources, company identifiers, credentials and report categories by market.'
---

# Markets

A **market** is a country code; a **route** is the source that serves it.
Most markets have one route. Where a country has both a national route and
the ESEF index, the national route is the default and
`source="esef_index"` selects the index.

```python
from opencorpfilings import provider_info, supported_markets

print(supported_markets())
route = provider_info("JP")
print(route.tier, route.identifiers, route.forms, route.date_filters, route.auth)
print(provider_info("IT", source="esef_index").coverage_note)
```

```text
('AT', 'BE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'HU', 'IS', 'IT', 'JP', 'KR', 'LT', 'LU', 'MT', 'NL', 'NO', 'PL', 'PT', 'SE', 'SI', 'SK', 'UK', 'US')
supported ('four-digit securities code', 'EDINET code') ('annual', 'interim', 'quarterly', 'current', 'other') True required API key: api_key=, OPENCORPFILINGS_EDINET_API_KEY or EDINET_API_KEY
Secondary index of ESEF annual reports by LEI; it lags regulators by months and is incomplete. On 2026-10-08 it held 974 FY2025 December-year-end reports against 2,142 for FY2024 (45%), with whole countries at 0%.
```

`provider_info()` needs no credentials or network access; `ocf markets`
prints every route's profile as JSON. `Company.filings()` checks each request
against this profile before contacting the source.

## Tiers

| Tier | Meaning | Routes |
|---|---|---|
| <span class="ocf-tier ocf-tier--supported">supported</span> | qualified on fresh issuers: every sampled latest-annual workflow passed the release qualification | US, UK, JP, FR |
| <span class="ocf-tier ocf-tier--limited">limited</span> | useful history with documented gaps | the ESEF index |
| <span class="ocf-tier ocf-tier--experimental">experimental</span> | implemented but not qualified for this release; opening one emits `ExperimentalRouteWarning` once per route and process | KR, ES, NL, DK, SE, PL, FI |

Experimental and limited routes are outside the [stability promise](../stability.md):
they may change, be promoted or be removed in a minor release. The
qualification runs are recorded in
[BENCHMARKS.md](https://github.com/sourcestate-io/opencorpfilings/blob/main/BENCHMARKS.md#route-qualification-v2-declared-2026-10-09).

## Route matrix

From `provider_info()` for every route in version 1.0.2. The ESEF index
row stands for 21 country routes, selected with `source="esef_index"` where a
national route also exists.

### Identifiers and categories

| Market | Provider | Tier | Identifiers | Categories (`forms`) |
|---|---|---|---|---|
| [US](us.md) | `sec` | supported | ticker, CIK | annual, quarterly, interim, current, prospectus, ownership, other |
| [UK](uk.md) | `companies_house` | supported | company number, exact company name | annual, other |
| [JP](jp.md) | `edinet` | supported | four-digit securities code, EDINET code | annual, interim, quarterly, current, other |
| [FR](fr.md) | `france_oam` | supported | LEI, exact source issuer name | annual, interim, quarterly |
| [ESEF index](esef.md) | `esef_index` | limited | LEI | annual |
| [KR](experimental.md#korea-open-dart) | `open_dart` | experimental | six-character stock code, eight-digit corporation code | annual, interim, quarterly, other |
| [ES](experimental.md#spain-cnmv) | `spain_cnmv` | experimental | issuer NIF | annual, interim |
| [NL](experimental.md#netherlands-afm) | `netherlands_oam` | experimental | exact register issuer name | annual, interim |
| [DK](experimental.md#denmark-danish-fsa) | `denmark_oam` | experimental | source business ID, exact issuer name | annual, interim |
| [SE](experimental.md#sweden-finanscentralen) | `sweden_oam` | experimental | company registration number | annual, interim, quarterly |
| [PL](experimental.md#poland-knf) | `poland_oam` | experimental | exact source issuer name | annual |
| [FI](experimental.md#finland-nasdaq-oam) | `finland_oam` | experimental | exact OAM company name, numeric source company ID | annual, interim |

### Filters, order and credentials

| Market | Native forms | Date filters | Amendment filter | `order_basis` | Auth |
|---|---|---|---|---|---|
| US | yes | yes | yes | `filing_date` | identifying User-Agent (required) |
| UK | yes | yes | yes | `filing_date` | API key optional |
| JP | no | yes | yes | `source_file_date` | API key (required) |
| FR | category codes only | yes | yes | `published_at` | none |
| ESEF index | no | no | no | `report_period` | none |
| KR | no | yes | yes | `filing_date` | API key (required) |
| ES | no | yes | no | `filing_date` | none |
| NL | no | yes | no | `filing_date` | none |
| DK | no | yes | no | `published_at` | none |
| SE | no | no | no | `report_period_label` | none |
| PL | no | yes | yes | `source_search_order` | none |
| FI | no | yes | no | `published_at` | none |

The ESEF index route serves AT, BE, DK, EE, ES, FI, FR, GR, HR, HU, IS, IT,
LT, LU, MT, NL, NO, PT, SE, SI and SK. In DK, ES, FI, FR, NL and SE it is the
alternative to a national route; elsewhere it is the market's only route.

## Capabilities

A capability says a route can perform an operation for qualifying records;
an individual filing can have fewer formats or no facts. Check one with
`company.provider.supports("sections")`.

| Route | Source search | Direct filing lookup | HTML/XHTML | PDF | Packages (ZIP) | Raw facts | SEC sections and printed pages |
|---|---|---|---|---|---|---|---|
| US | yes | yes | yes | | | yes (XBRL, iXBRL) | yes |
| UK | yes | with an API key | yes | yes | | yes (iXBRL) | |
| JP | yes | | | yes | yes | yes (XBRL, iXBRL) | |
| FR | yes | yes | yes | yes | yes | yes (iXBRL) | |
| ESEF index | | yes | yes | | yes | yes (xBRL-JSON or iXBRL) | |
| KR | yes | | | | yes | yes (XBRL) | |
| ES | yes | | yes | yes | yes | yes (XBRL, iXBRL) | |
| NL | yes | yes | yes | yes | yes | yes (iXBRL) | |
| DK | yes | yes | yes | yes | yes | yes (iXBRL) | |
| SE | yes | | yes | | yes | yes (iXBRL) | |
| PL | yes | | yes | | yes | yes (iXBRL) | |
| FI | yes | | yes | yes | yes | yes (iXBRL) | |

Every route declares entity lookup, filing discovery, document download,
streamed saves and text.

## Markets without a route

- **HK** is pending authorized access; `Company(..., market="HK")` raises
  `UnsupportedCapabilityError`.
- **Retired 2026-10-09:** the national routes for IS, LT, LV, HR, RO, SK, EE,
  MT, CY, HU and LI were removed. HR, EE, HU, IS, LT, MT and SK now use the ESEF
  index by LEI. CY, RO, LV and LI have no route and raise
  `UnsupportedMarketError`.
- Any other code raises `UnsupportedMarketError`, with a hint for common
  aliases (`GB` → `UK`, `USA` → `US`, `JPN` → `JP`).

Source access terms for every route, including those without an adapter, are
in [Source access and rights](../reference/source-access.md).
