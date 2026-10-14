---
title: 'Japan EDINET filings in Python'
description: 'Find Japanese companies by securities or EDINET code. Retrieve annual and interim reports with an EDINET API key and a date window.'
---

# Japan (EDINET)

<span class="ocf-tier ocf-tier--supported">supported</span> · market `JP` · provider `edinet` · regulator Financial Services Agency EDINET

## Source

Filings come from the [EDINET API](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html).
Issuers are resolved against the official
[EDINET code list](https://disclosure2.edinet-fsa.go.jp/WEEK0020.aspx).

## Identifiers

| Identifier | Example |
|---|---|
| four-digit securities code | `Company("7203", market="JP")` |
| EDINET code | `Company("E02144", market="JP")` |

Both resolve to the same issuer; `company.entity.entity_id` is the EDINET
code. `search_companies("Toyota", market="JP")` searches the code list by
Japanese or English name, or by code.

## Forms

EDINET document type codes:

| Category | Codes | Amended |
|---|---|---|
| `annual` | `120` annual securities report | `130` |
| `quarterly` | `140` quarterly report | `150` |
| `interim` | `160` half-year report | `170` |
| `current` | `180` extraordinary report | `190` |
| `other` | every other code | |

The code is `filing.filing_type_raw`. Native codes are not accepted as
`form=`; use a category. A filing is an amendment when its code is `130`,
`150`, `170` or `190` or it has a parent document ID; category requests
exclude amendments by default. Quarterly reports ended in April 2024.

## Dates

| Field | Source value |
|---|---|
| `filing_date` | the submission date (`submitDateTime`) |
| `published_at` | the submission time, Japan Standard Time |
| `provider_metadata["source_file_date"]` | the daily list the record was found in |
| `period_start`, `period_end` | the report's own period: EDINET's period fields give the fiscal year, so a half-year report (`160`/`170`) ends six months after the fiscal year starts; a quarterly report (`140`/`150`) has none |

`order_basis` is `source_file_date`, and `start=`/`end=` filter on the source
file date, not the submission date. The two can differ for a backdated paper
or disk submission, so a narrow file-date window is not a complete
submission-date search.

## Discovery speed

EDINET has no per-company listing. Its API returns the filings of **one day
per request**, so the route reads daily lists newest first until it finds a
match:

- Without a window, discovery looks back 550 days (`default_lookback_days`).
  `filings(form="annual").latest()` took 30 seconds to two minutes in October
  2026, growing with the time since the company's last annual report.
  Measured live: Toyota's latest annual in 27.5 s; its half-year report, filed
  330 days earlier, in 92 s.
- **Pass `start=` and `end=`** around the expected filing date to make a
  lookup take seconds.
- Up to four daily requests are in flight, paced at a 0.2-second dispatch
  interval. The provider keeps the 90 most recently read days in memory, so
  an annual and then an interim lookup in one session share recent days.
  EDINET sends daily lists with `Cache-Control: no-cache`, so the response
  cache does not reuse them across processes.

```python
toyota = Company("7203", market="JP")
toyota.filings(form="annual", start="2026-06-01", end="2026-06-30").latest()
```

```text
<Filing S100Y8NY 120 ANNUAL period=2026-03-31 filed=2026-06-10 JP/edinet>
```

## Documents and content

Each filing lists the representations its source flags declare:

| Document | Role | Media type | Language |
|---|---|---|---|
| `S...-original.zip`, the native package (primary) | `report` | ZIP | `ja` |
| `S...-pdf.pdf` | `report` | PDF | `ja` |
| `S...-attachments.zip` | `annex` | ZIP | `ja` |
| `S...-english.zip` | `report` | ZIP | `en` |
| `S...-csv.zip` | `data` | ZIP | `ja` |

Select one with `filing.select_document(language="en")` or
`select_document(document_type="pdf")`. Text comes from the HTML inside the
original or English ZIP. Raw facts come from classic XBRL instances (50 MB
parse limit) or inline XBRL members (100 MB in memory, up to 2 GB from a
file). Toyota's original package yielded 2,182 classic raw facts.

A filing whose current source status (withdrawn, or disclosure restricted)
prevents access has no documents. Rows the daily list repeats for a later
correction or disclosure event are not separate filings; the original day's
row carries the updated metadata.

## Authentication and limits

An API key is required: `api_key=`, `OPENCORPFILINGS_EDINET_API_KEY` or
`EDINET_API_KEY`. It is issued free after registering on the
[EDINET API site](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html).
Without one, `Company(..., market="JP")` raises `AuthenticationError`.
EDINET asks clients to obtain content through the API, pace requests and
avoid short-period mass access.

## Known gaps

- Discovery cost grows with the lookback; there is no issuer-filtered
  listing to shortcut it.
- Date filters use the source file date.
- No exact-native-form selection; categories only.

See also the [EDINET terms in Source access](../reference/source-access.md)
and the [EDINET provider notes](https://github.com/sourcestate-io/opencorpfilings/blob/main/PROVIDER_NOTES.md#edinet).
