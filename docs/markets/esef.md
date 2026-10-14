---
title: 'European ESEF annual reports and iXBRL packages'
description: 'Retrieve ESEF annual reports by LEI from filings.xbrl.org across 21 EU and EEA countries, with explicit index coverage and freshness limits.'
---

# ESEF index (filings.xbrl.org)

<span class="ocf-tier ocf-tier--limited">limited</span> · source `esef_index` · provider `esef_index` · 21 countries

## Source

The [filings.xbrl.org](https://filings.xbrl.org/docs/api) index collects
annual financial reports in the European Single Electronic Format (ESEF). It
is a **secondary, incomplete index**, not a national filing register, and it
lags the regulators by months. Use it for several years of tagged annual
reports, not for a company's latest report.

```python
from opencorpfilings import provider_info

print(provider_info("IT", source="esef_index").coverage_note)
```

```text
Secondary index of ESEF annual reports by LEI; it lags regulators by months and is incomplete. On 2026-10-08 it held 974 FY2025 December-year-end reports against 2,142 for FY2024 (45%), with whole countries at 0%.
```

`benchmarks/esef_index_freshness.py` in the repository measures how much of
the latest fiscal year has arrived, country by country. Measured 2026-10-08
(December year-end reports; the earlier year stands in for the population):

| Country | FY2024 | FY2025 | FY2025 / FY2024 |
|---|---:|---:|---:|
| AT | 89 | 77 | 87% |
| BE | 125 | 47 | 38% |
| DK | 239 | 261 | 109% |
| EE | 3 | 0 | 0% |
| ES | 105 | 0 | 0% |
| FI | 209 | 161 | 77% |
| FR | 192 | 152 | 79% |
| GR | 45 | 0 | 0% |
| HR | 30 | 0 | 0% |
| HU | 29 | 0 | 0% |
| IS | 27 | 16 | 59% |
| IT | 192 | 118 | 61% |
| LT | 38 | 17 | 45% |
| LU | 54 | 0 | 0% |
| MT | 46 | 0 | 0% |
| NL | 121 | 106 | 88% |
| NO | 220 | 0 | 0% |
| PT | 7 | 0 | 0% |
| SE | 339 | 0 | 0% |
| SI | 18 | 8 | 44% |
| SK | 14 | 11 | 79% |
| **All** | 2,142 | 974 | 45% |

## Countries

AT, BE, DK, EE, ES, FI, FR, GR, HR, HU, IS, IT, LT, LU, MT, NL, NO, PT, SE,
SI and SK.

- Where a national route exists (DK, ES, FI, FR, NL, SE), it is the default
  and `source="esef_index"` selects the index.
- In every other listed country, the index is the market's only route and
  the default.
- CZ, CY, RO, LV and PL were dropped on 2026-10-08 because the index stopped
  receiving them (newest periods 2020 to 2023; PL's last record was added in
  July 2024).
- Norway is index-only: NewsWeb's source terms reserve non-private
  downloading and storage to separately authorized users.

## Identifiers

LEI only:

```python
from opencorpfilings import Company

Company("WOCMU6HCI0OJWNPRZS33", market="IT", source="esef_index")
Company("5299006UDSEJCTTEJS30", market="AT")    # AT has no national route
```

The route has no name search; `search_companies()` raises
`UnsupportedCapabilityError`. [`find_company`](../guide/finding-companies.md)
indexes the index's issuers by country and returns matches with
`source="esef_index"`.

## Forms

Every record is typed `filing_type_raw="ESEF"`,
`filing_type_normalized="ANNUAL"`, because ESEF tagging is mandated for annual
financial reports and the index has no form field. `form="annual"` is accepted;
other forms, native codes, date filters and amendment filters raise
`UnsupportedCapabilityError`.

## Dates and order

| Field | Source value |
|---|---|
| `filing_date` | `None`: the index supplies no regulator filing date |
| `index_added_at` | when the index received the record; never substituted for a filing date |
| `period_end` | the report period end from the index |
| `language` | the report language |

`order_basis` is `report_period`: newest period first, with the preferred
language first within a period. English is preferred by default; the
`prefer_language=` provider option changes it:

```python
Company("WOCMU6HCI0OJWNPRZS33", market="IT", source="esef_index", prefer_language="it")
```

```python
enel = Company("WOCMU6HCI0OJWNPRZS33", market="IT", source="esef_index")
[(filing.period_end, filing.language) for filing in enel.filings(form="annual").head(4)]
```

```text
[(datetime.date(2024, 12, 31), 'en'), (datetime.date(2024, 12, 31), 'it'),
 (datetime.date(2023, 12, 31), 'en'), (datetime.date(2023, 12, 31), 'it')]
```

Discovery reads at most 20 index pages per issuer and raises if more are
needed; the `max_pages=` provider option widens it.

## Direct lookup

`filing_id` is the index's numeric record ID. Direct lookup fetches one record
and checks its LEI and country:

```python
Company("5299006UDSEJCTTEJS30", market="AT", source="esef_index").get_filing("24793")
```

Because the index has no filing date, `start=`/`end=` cannot filter this
result.

## Documents and content

| Document | `document_type` | Role | Primary |
|---|---|---|---|
| indexed report XHTML | `report_xhtml` | `report` | yes, when present |
| source ZIP package | `source_package` | `report` | when there is no indexed XHTML |
| derived xBRL-JSON | `derived_xbrl_json` | `data` | no |

From the [name-to-files notebook](https://github.com/sourcestate-io/opencorpfilings/blob/main/examples/notebooks/05_find_a_company_and_get_its_files.ipynb):

```python
from opencorpfilings import find_company

verbund = find_company("Verbund", limit=1, live=False)[0].company()
filing = verbund.filings(form="annual").latest()
filing, [(document.filename, document.role) for document in filing.documents]
```

```text
(<Filing 24793 ESEF ANNUAL period=2025-12-31 AT/esef_index>,
 [('verbundag-2025-12-31-1-en.xhtml', 'report'),
  ('5299006UDSEJCTTEJS30-2025-12-31.xbri', 'report'),
  ('verbundag-2025-12-31-1-en.json', 'data')])
```

- Text comes from the indexed XHTML, or from all report XHTML members of a
  source ZIP when that is the only document.
- `filing.facts` uses the xBRL-JSON when the index supplies it, keeping its
  JSON fact identifiers; otherwise the original inline XBRL tags, with each
  report member's source location.
- A source ZIP is checked against the index's SHA-256 when one is present.

## Authentication and limits

No credentials. The index may change its API terms or limits. Source packages
and xBRL-JSON can carry issuer and taxonomy material; preserve the original
filing and index URLs when reusing output.

## Known gaps

- Incomplete and months behind the regulators; whole countries can have no
  records for the latest fiscal year.
- Annual reports only; no filing date, so no date filters.
- An LEI and period match between an index record and a national record does
  not prove the documents are the same; compare `document.sha256()`.
- Index records do not establish national OAM coverage in any country.

See also the [ESEF index terms in Source access](../reference/source-access.md)
and the [ESEF provider notes](https://github.com/sourcestate-io/opencorpfilings/blob/main/PROVIDER_NOTES.md#esef-index).
