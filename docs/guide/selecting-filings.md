---
title: 'Select annual, quarterly and current filings'
description: 'Filter company filings by form, date and amendment status. Select the latest filing or look up a source filing ID in Python.'
---

# Selecting filings

```python
company.filings(*, form=None, start=None, end=None, include_amendments=None, limit=None)
```

`Company.filings()` returns a `FilingCollection`. It checks the request
against the route's profile before contacting the source, so a form, date
filter or amendment filter the route cannot serve fails at once with the
allowed values. Building a collection resolves the issuer but lists no
filings; filings are read when you iterate, call `head()`, `latest()` or
`get()`, or download.

```python
annuals = company.filings(form="annual", start="2023-01-01", end="2025-12-31", limit=10)
newest = annuals.latest()          # one Filing
three = annuals.latest(3)          # a list of up to three
for filing in annuals:             # newest first, at most 10
    print(filing.filing_id, filing.filing_date)
```

## Forms

`form=` takes either a **category** or an exact **native form**.

### Categories

A category is one of the names in `FILING_CATEGORIES`, written in lower case:
`annual`, `quarterly`, `interim`, `current`, `prospectus`, `ownership`,
`other`. Each route declares the categories it can select:

| Route | Categories |
|---|---|
| US SEC | annual, quarterly, interim, current, prospectus, ownership, other |
| UK Companies House | annual, other |
| JP EDINET | annual, interim, quarterly, current, other |
| FR Info-Financiere | annual, interim, quarterly |
| ESEF index | annual |
| KR Open DART | annual, interim, quarterly, other |
| ES, NL, DK, FI | annual, interim |
| SE | annual, interim, quarterly |
| PL | annual |

Each market page lists the native codes behind each category. The category a
filing was matched to is `filing.filing_type_normalized` (upper case, such as
`ANNUAL`); the source's own code stays in `filing.filing_type_raw`. A
normalized value is `None` when the source cannot justify a category.

```python
from opencorpfilings import Company

greggs = Company("00502851", market="UK")
greggs.filings(form="interim")
```

```text
UnsupportedCapabilityError: UK/companies_house cannot select form='interim'; its categories are: annual, other (exact native source forms are also accepted)
```

A near-miss of a category name, on a route that accepts native forms, raises
with a suggestion (`did you mean 'annual'?`) instead of searching for a form
that does not exist.

### Native forms

An exact native form means exactly that form. On the SEC route,
`form="10-K"` excludes `10-K/A`, which `form="10-K/A"` selects. Routes differ
in whether they accept native forms (`provider_info(market).native_forms`):

| Route | Native forms |
|---|---|
| US SEC | accepted, such as `10-K`, `10-Q`, `8-K`, `4`, `S-1` |
| UK Companies House | accepted, such as `AA` (case-insensitive) |
| FR Info-Financiere | the category codes only: `003000`, `004000`, `005000`, `005001`, `005002`; see [France](../markets/fr.md#forms) |
| all other routes | not accepted; use a category |

## Amendments

A category request returns **original reports** by default on routes whose
source flags amendments (`provider_info(market).amendment_filter` is `True`:
US, UK, JP, FR, KR and PL). A later Part III 10-K/A does not displace the
10-K. Pass `include_amendments=True` to list amendments as well.

An exact native form, or no form at all, lists every matching record,
amendments included. `include_amendments=False` on a route that cannot tell
amendments apart raises `UnsupportedCapabilityError`.

`filing.amendment` is `True`, `False`, or `None` when the source does not say.

## Dates

`start=` and `end=` accept ISO date strings, `datetime.date` objects or the
calendar date of a `datetime`. Both bounds are inclusive, and `start` must not
be after `end`.

The date a route filters on is its source date for the filing, usually
`filing_date`. Japan filters on EDINET's source file date instead, so a
narrow window can miss a backdated submission; see [Japan](../markets/jp.md#dates).
Routes without a source filing date refuse date filters:

```text
UnsupportedCapabilityError: IT/esef_index has no source filing date to filter on; call filings() without start/end
```

This applies to the ESEF index and to Sweden.

## Order

Every collection yields newest first in its route's `order_basis`, which is
also `collection.order_basis`:

| `order_basis` | Routes | Meaning |
|---|---|---|
| `filing_date` | US, UK, KR, ES, NL | the regulator's filing date |
| `source_file_date` | JP | EDINET's source file date |
| `published_at` | FR, FI, DK | the source's publication time |
| `report_period` | ESEF index | report period end, preferred language first within a period |
| `report_period_label` | SE | the source's year/month label |
| `source_search_order` | PL | the order of KNF's search results (receipt date) |

`latest()` returns the first record in that order. On the ESEF index it is the
newest report period, not the most recently filed record.

## Reading a collection

| Call | Returns |
|---|---|
| `iter(collection)` | every matching filing, newest first, bounded by `limit` |
| `collection.head(n)` | the first `n` filings, read with a bounded listing |
| `collection[i]`, `collection[:n]`, `collection[i:j]` | a filing or list by position, reading only that far; `IndexError` past the end. Negative positions and open-ended slices like `[2:]` need `limit=` |
| `collection.latest()` | the newest filing; `FilingNotFoundError` if there is none |
| `collection.latest(n)` | the newest `n` as a list (same as `head(n)`) |
| `collection.get(filing_id, *, max_scan=500)` | one exact source filing ID within this collection |
| `collection.to_pandas(n)` | the first `n` filings as a DataFrame (needs the `pandas` extra) |
| `collection.download(directory, ...)` | see [Downloading a company's filings](downloads.md) |

`n` is required for `to_pandas` because source histories are paged:

```python
apple = Company("AAPL", market="US")
apple.filings(form="quarterly").to_pandas(4)[["filing_id", "filing_type_raw", "filing_date", "period_end"]]
```

```text
              filing_id filing_type_raw filing_date  period_end
0  0000320193-26-000020            10-Q  2026-07-31  2026-06-27
1  0000320193-26-000013            10-Q  2026-05-01  2026-03-28
2  0000320193-26-000006            10-Q  2026-01-30  2025-12-27
3  0000320193-25-000073            10-Q  2025-08-01  2025-06-28
```

`limit=n` yields at most `n` records; the bound is applied at the provider
and again in the collection.

## One exact filing

```python
company.get_filing(filing_id, *, start=None, end=None, max_scan=500)
```

Pass the source's own filing ID. Routes that declare `direct_filing_lookup`
read the record directly and check that it belongs to the company:

| Route | ID form | Example |
|---|---|---|
| US SEC | accession number | `Company("320193", market="US").get_filing("0000320193-25-000079")` |
| UK Companies House, with an API key | transaction ID | `Company("00185647", market="UK").get_filing("<transaction_id>")` |
| FR Info-Financiere | `diffuser:UIN` | `Company("AB SCIENCE", market="FR").get_filing("432:628645_20260513")` |
| ESEF index | numeric record ID | `Company("5299006UDSEJCTTEJS30", market="AT", source="esef_index").get_filing("24793")` |
| NL, DK | the source record ID | |

Other routes scan the newest `max_scan` records (500 by default); pass
`start=`/`end=` to reach an older record. The date bounds also apply to a
direct result, which is refused if the route has no source date for it.

`collection.get(filing_id)` uses the same direct lookup on a collection
without `limit`, and then checks the collection's form, date and amendment
filters on the returned record. A collection with `limit` checks membership
within its bounded listing instead.
