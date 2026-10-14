---
title: 'UK Companies House accounts in Python'
description: 'Find UK companies and download filed accounts from Companies House using public pages or an optional API key.'
---

# United Kingdom (Companies House)

<span class="ocf-tier ocf-tier--supported">supported</span> · market `UK` · provider `companies_house` · regulator Companies House

## Source

Without a key, the route reads the public
[Find and update company information](https://find-and-update.company-information.service.gov.uk/)
pages. With `OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY` it uses the
authenticated [REST and Document APIs](https://developer.company-information.service.gov.uk/)
instead.

## Identifiers

| Identifier | Example |
|---|---|
| company number: eight digits, or two letters and six digits; a shorter all-digit number is zero-padded (`"185647"` is `00185647`) | `Company("00185647", market="UK")`, `"SC702856"` |
| exact company name | resolved only when exactly one company has that name; otherwise `AmbiguousEntityError` or `EntityNotFoundError` |

`search_companies("Greggs", market="UK")` searches Companies House by name.
The public route follows source pagination until it has the requested number
of unique companies or reaches a 20-page bound. Results are any registered
company, not only listed issuers; the UK has no official list of listed
companies.

## Forms

| Category | Native forms |
|---|---|
| `annual` | filed accounts: types `AA`, `AAMD` and `AA02` in the source's accounts category |
| `other` | everything else, including reference-date changes (`AA01`) |

Exact Companies House filing types are accepted, case-insensitively, such as
`form="AA"`. A type ending in `AMD`, or a description containing "amend", is
an amendment; `form="annual"` excludes amendments by default.

## Dates

| Field | Source value |
|---|---|
| `filing_date` | the filing history date; `start=`/`end=` filter on it, and listing stops at the first filing older than `start` (the history is newest first) |
| `period_end` | the accounts "made up to" date (the API's `made_up_date`, or the public page's text) |
| `title` | the source description, such as `Group of companies' accounts made up to 27 December 2025` |

`order_basis` is `filing_date`. With an API key, `form="annual"` asks the
source for its `accounts` category only; keyless pages ignore that filter, so
the route filters the rows itself.

## Direct lookup

With an API key, `Company("00185647", market="UK").get_filing("<transaction_id>")`
requests one filing history item and validates its company and transaction
link. Keyless pages have no individual transaction page, so without a key
`get_filing()` scans the newest `max_scan` records.

## Documents and content

- Public pages: PDF, XHTML or ZIP as linked. API: the Document API's
  representations.
- Documents have the `report` role. The primary is the source's preferred
  representation.
- Text from XHTML and from the report XHTML inside an accounts ZIP. PDFs give
  text with the `pdf` extra when they have a text layer.
- Raw inline XBRL facts from XHTML accounts or the report inside a ZIP. Many
  companies file PDF accounts, which carry no facts.

## Example

From the [text, tables and facts notebook](https://github.com/sourcestate-io/opencorpfilings/blob/main/examples/notebooks/04_text_tables_and_facts.ipynb):

```python
from opencorpfilings import Company

accounts = Company("00185647", market="UK").filings(form="annual").latest()
frame = accounts.facts_to_pandas()
print(len(frame), "facts")
```

```text
762 facts
```

J Sainsbury's inline XBRL was generated from a PDF, so values such as
`33,6 4 7` keep the spaces that are in the filed text; see
[Tagged facts](../guide/text-tables-facts.md#tagged-facts).

```bash
ocf filings 00185647 --market UK --form annual --limit 3
ocf download 00502851 --market UK --form annual --limit 5 --output-dir greggs/
```

## Authentication and limits

No credentials are needed. A free API key from a
[developer account](https://developer.company-information.service.gov.uk/)
switches the route to the REST and Document APIs and enables direct lookup.
The public site [is not intended for bulk downloads](https://www.gov.uk/guidance/searching-the-companies-house-register);
the library retrieves individual filings with paced requests.

## Known gaps

- The public-page route skips filing history rows without a document link,
  because those rows expose no source transaction ID.
- The public pages send `no-store`, so the local response cache does not reuse
  them.
- Only `annual` and `other` categories exist: there is no interim category.
- A first `filing.text()` on a large accounts package downloads the whole
  package.

See also the [Companies House terms in Source access](../reference/source-access.md).
