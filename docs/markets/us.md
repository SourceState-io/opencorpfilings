---
title: 'SEC EDGAR filings in Python'
description: 'Find US companies by ticker or CIK. Download SEC 10-K, 10-Q, 8-K and other original filings; read sections and raw XBRL facts.'
---

# United States (SEC EDGAR)

<span class="ocf-tier ocf-tier--supported">supported</span> · market `US` · provider `sec` · regulator US Securities and Exchange Commission

## Source

Filings come from [SEC EDGAR](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data):
the submissions profile for listings, and the original filing index and
archive for documents.

## Identifiers

| Identifier | Example |
|---|---|
| ticker | `Company("AAPL", market="US")` |
| CIK | `Company("320193", market="US")` |

Exact ticker lookup uses the SEC's ticker/CIK map and verifies the ticker
against the submissions profile; a miss or stale mapping falls back to the
exchange list, also verified. `search_companies("Apple", market="US")` searches
the SEC's exchange ticker list by name.

A ticker resolves to the **current** SEC registrant. A corporate
reorganization can put older filings under another CIK: current `XOM`
resolves to `0002115436`, while its predecessor's 2026 annual filing is under
`Company("0000034088", market="US")`. The library does not combine those
entities.

## Forms

| Category | Native forms |
|---|---|
| `annual` | `10-K`, `20-F`, `40-F`, `10-KT`; before 2009 also `10-K405`, `10-KSB`, `10-KSB40`, `10-KT405` |
| `quarterly` | `10-Q`, `10-QT`, `10-QSB` |
| `interim` | the same filings as `quarterly` |
| `current` | `8-K`, `6-K` |
| `prospectus` | forms starting `S-1`, `F-1` or `424B` |
| `ownership` | `3`, `4`, `5`, `SC 13D`, `SC 13G`, and since December 2024 `SCHEDULE 13D`, `SCHEDULE 13G`. For XML forms the primary document is the filed XML, not SEC's rendered view |
| `other` | every other form |

An amendment (`/A`) belongs to its base form's category. Category requests
return originals by default; `include_amendments=True` adds amendments. Any
exact EDGAR form is accepted: `form="10-K"` excludes `10-K/A`, which
`form="10-K/A"` selects.

## Dates

| Field | Source value |
|---|---|
| `filing_date` | EDGAR filing date; `start=`/`end=` filter on it |
| `published_at` | the acceptance date-time from the submissions profile |
| `period_end` | the report date |

`order_basis` is `filing_date`. For date-filtered listings, the provider skips
older submission files whose SEC-declared date range cannot contain a match.

## Direct lookup

`company.get_filing(accession)` reads the original EDGAR index page directly,
checking the CIK and the accession:

```python
Company("320193", market="US").get_filing("0000320193-25-000079")
```

The accession prefix need not equal the issuer CIK: Microsoft's
`0001193125-26-323660` resolves under Microsoft's CIK `0000789019`. A filing
read this way keeps the page's displayed acceptance time raw, because the
page does not state its time zone.

## Documents and content

- `filing.primary_document`, `filing.text()` and `filing.download()` use the
  primary filename EDGAR supplies, without listing the whole archive.
- `filing.documents` combines the typed rows of the filing index with the
  full archive directory. Exhibits keep their EDGAR type
  (`select_document(document_type="EX-21.1")`), `description`, and
  `provider_metadata["index_sequence"]`. Generated files stay visible with no
  invented type.
- Roles: the primary file is `report`; `EX-101` and XBRL files are `data`;
  other `EX-` types are `exhibit`; EDGAR renderings and indexes are
  `generated`.
- Raw facts come from the original XBRL instance or the inline XBRL tags in
  the primary document.
- [Item sections](../guide/text-tables-facts.md#sec-item-sections) for
  qualifying original 10-K, 10-Q and 8-K HTML, with page and exhibit
  pointers for 10-Ks that use a cross-reference index.

## Example

From the [quickstart notebook](https://github.com/sourcestate-io/opencorpfilings/blob/main/examples/notebooks/01_quickstart.ipynb):

```python
from opencorpfilings import Company

apple = Company("AAPL", market="US", user_agent="Your Name you@example.com")
filing = apple.filings(form="annual").latest()
filing, filing.primary_document
```

```text
(<Filing 0000320193-25-000079 10-K ANNUAL period=2025-09-27 filed=2025-10-31 US/sec>,
 <FilingDocument aapl-20250927.htm text/html 10-K report primary>)
```

```bash
ocf filings AAPL --market US --form annual --limit 3 --user-agent "Your Name contact@example.com"
```

## Authentication and limits

Every SEC request needs an identifying User-Agent with a name or organization
and a contact email: `user_agent=`, `OPENCORPFILINGS_SEC_USER_AGENT`, or
`--user-agent` on the command line. No registration is needed. Without one,
`Company(..., market="US")` raises `AuthenticationError`.

For example, `Alex Morgan alex@example.com` means a name followed by a
contact email, separated by a space. Replace both with your own details.
See [SEC request identity](../getting-started.md#sec-request-identity) for
Python, notebook and terminal setup.

The SEC's [fair-access policy](https://www.sec.gov/os/accessing-edgar-data)
sets an aggregate limit of 10 requests per second. The provider paces its own
requests below that; if several processes share an IP address, their combined
traffic must stay within the limit.

## Known gaps

- Item sections require an original with verifiable Item boundaries; amended
  filings (`10-K/A`, `10-Q/A`, `8-K/A`) and ambiguous layouts raise
  `UnsupportedCapabilityError`.
- `interim` and `quarterly` select the same filings (the quarterly forms).
- Predecessor and successor registrants are separate entities.

See also the [SEC terms in Source access](../reference/source-access.md) and
the [SEC provider notes](https://github.com/sourcestate-io/opencorpfilings/blob/main/PROVIDER_NOTES.md#sec).
