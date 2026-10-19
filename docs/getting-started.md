---
title: 'Install OpenCorpFilings and download your first filing'
description: 'Install OpenCorpFilings from GitHub, configure source credentials and download your first annual report with Python.'
---

# Getting started

## Install

OpenCorpFilings needs Python 3.11, 3.12 or 3.13. Install from
[GitHub](https://github.com/sourcestate-io/opencorpfilings); the package is not
on PyPI.

Install a tagged release directly:

```bash
pip install "opencorpfilings[pdf,markdown,pandas] @ git+https://github.com/sourcestate-io/opencorpfilings@v1.1.1"
```

Or clone the repository and install from source:

```bash
git clone https://github.com/sourcestate-io/opencorpfilings.git
cd opencorpfilings
pip install .                       # base install
pip install ".[pdf,markdown,pandas]" # with every optional extra
```

The base install depends only on `httpx` and `beautifulsoup4`, plus `tzdata` on
Windows, which has no time-zone database of its own. The extras are
optional:

| Extra | Adds | Needed for |
|---|---|---|
| `pdf` | pypdf | PDF text: `document.pages`, `document.page(n)`, `text()` on a PDF |
| `markdown` | markdownify | `filing.markdown()`, `document.markdown()`, `member.markdown()` |
| `pandas` | pandas | `filing.facts_to_pandas()`, `collection.to_pandas(n)` |

Calling a method whose extra is missing raises `UnsupportedCapabilityError`.

Check the install:

```bash
ocf --version
```

```text
ocf 1.1.1
```

## Credentials

Credentials come from keyword arguments (`user_agent=`, `api_key=`) or from
environment variables. An explicit argument takes precedence, then the
`OPENCORPFILINGS_*` name, then the shorter name where one exists. The library
reads the process environment; it does not load `.env` files.

| Market | Setting | Required | How to get it |
|---|---|---|---|
| US (SEC EDGAR) | `user_agent=` or `OPENCORPFILINGS_SEC_USER_AGENT` | yes | your name or organization and a contact email; no registration ([SEC fair-access rules](https://www.sec.gov/os/accessing-edgar-data)) |
| UK (Companies House) | `api_key=` or `OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY` | no; public pages are used without it | free [developer account](https://developer.company-information.service.gov.uk/) |
| JP (EDINET) | `api_key=`, `OPENCORPFILINGS_EDINET_API_KEY` or `EDINET_API_KEY` | yes | free, after registering on the [EDINET API site](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html) |
| KR (Open DART, experimental) | `api_key=`, `OPENCORPFILINGS_DART_API_KEY` or `OPENDART_API_KEY` | yes | free key from [Open DART](https://engopendart.fss.or.kr/) |
| FR, the ESEF index, ES, NL, DK, SE, PL, FI | none | | |

Without an SEC identity, `Company(..., market="US")` raises
`AuthenticationError` before any request is made.

### SEC request identity

`OPENCORPFILINGS_SEC_USER_AGENT` is a label that identifies your requests to
the SEC. It is not an API key, and you do not need an SEC account. Use your
name or organization, a space, then a working contact email:

```text
Alex Morgan alex@example.com
Example Research filings@example.com
```

These are illustrative values. Replace the name and email with your own;
do not use a placeholder contact for live requests. For Python or a notebook:

```python
import os

os.environ["OPENCORPFILINGS_SEC_USER_AGENT"] = "Alex Morgan alex@example.com"
```

Set it before creating a US `Company` or calling `find_company()`. To set it
in a terminal instead:

```bash
# macOS / Linux
export OPENCORPFILINGS_SEC_USER_AGENT="Alex Morgan alex@example.com"
```

```powershell
# Windows PowerShell
$env:OPENCORPFILINGS_SEC_USER_AGENT = "Alex Morgan alex@example.com"
```

You can also pass the same value to `Company(..., user_agent=...)` for that
company, or `ocf ... --user-agent "Alex Morgan alex@example.com"` for one CLI
command. The label is sent to the SEC with each request; use a contact you
are comfortable sharing with the regulator. Keep API keys out of source code,
notebooks and logs.

### Response cache

Successful GET responses up to 2 MB are reused in memory for up to five
minutes, shortened by the source's own freshness limit. To reuse responses
across processes, pass `cache_dir=` to `Company` or `search_companies()`, or
set `OPENCORPFILINGS_CACHE_DIR`:

```python
company = Company("AAPL", market="US", cache_dir="~/.cache/opencorpfilings")
```

The local cache holds at most 128 response files, checksums each entry, keeps
credentials out of filenames and honors `no-store`, `no-cache`, `max-age`,
`Age` and `Expires`. It does not store authenticated or cookie-backed pages,
POST forms or streamed document saves. `OPENCORPFILINGS_CACHE_DIR` is also
where [`find_company`](guide/finding-companies.md) keeps its company index
(default `~/.cache/opencorpfilings`).

## Your first filing

Need a company identifier? [Find a company](find/index.md) searches by name, ticker,
ISIN or LEI in your browser and gives you a ready-to-copy `Company(...)` line.

Open a company with the identifier its market uses, select a filing, and read
its documents. The outputs below come from the
[quickstart notebook](https://github.com/sourcestate-io/opencorpfilings/blob/main/examples/notebooks/01_quickstart.ipynb).

```python
import os
from opencorpfilings import Company

os.environ["OPENCORPFILINGS_SEC_USER_AGENT"] = "Your Name you@example.com"

apple = Company("AAPL", market="US")
filing = apple.filings(form="annual").latest()
filing
```

```text
<Filing 0000320193-25-000079 10-K ANNUAL period=2025-09-27 filed=2025-10-31 US/sec>
```

The printed line shows the source filing ID, the raw form, the category, the
report period, the filing date and the route. Printing never contacts the
source.

```python
filing.to_dict()["filing_date"], filing.period_end, filing.source_url
```

```text
('2025-10-31', datetime.date(2025, 9, 27), 'https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/0000320193-25-000079-index.htm')
```

An EDGAR filing lists many files. Each has a `role`, and `primary_document` is
the report itself:

```python
from collections import Counter

Counter(document.role for document in filing.documents)
filing.primary_document
```

```text
Counter({'generated': 78, 'exhibit': 6, 'data': 6, 'other': 2, 'report': 1})
<FilingDocument aapl-20250927.htm text/html 10-K report primary>
```

Read the text, one 10-K Item, and the tagged facts:

```python
text = filing.text()
print(len(text), "characters")        # 208385 characters

item_7 = filing.section("Item 7")
print(item_7.title)                   # Management’s Discussion and Analysis of ...

facts = filing.facts_to_pandas()      # needs the pandas extra
facts[facts["concept_raw"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"][
    ["value", "unit", "period_start", "period_end"]].head(3)
```

```text
           value         unit period_start  period_end
89  307003000000  iso4217:USD   2024-09-29  2025-09-27
90  294866000000  iso4217:USD   2023-10-01  2024-09-28
91  298085000000  iso4217:USD   2022-09-25  2023-09-30
```

Save the original:

```python
saved = filing.primary_document.download("apple-10k.htm")   # returns the Path
raw = filing.primary_document.download()                    # returns the bytes
```

### Closing connections

A `Company` that creates its own provider owns its HTTP connection. Use it as
a context manager, or call `close()`, when you are done:

```python
with Company("00185647", market="UK") as sainsbury:
    accounts = sainsbury.filings(form="annual").latest()
```

A provider you pass in with `provider=` stays open, so it can be reused for
another company.

## Speed expectations

Sources differ in speed:

- **Japan.** EDINET has no per-company listing, so the JP route reads its
  daily filing lists. `filings(form="annual").latest()` without a date window
  took 30 seconds to two minutes in October 2026. A `start=`/`end=` window
  around the expected filing date makes it a few seconds. See
  [Japan](markets/jp.md).
- **Large packages.** A first `filing.text()` on a large French or UK report
  downloads the whole package, which can take a minute.
- **`find_company`.** The first call builds a local index from official lists
  in about 20 seconds; later calls reuse it for seven days.

## Next steps

- [Find a company](guide/finding-companies.md) when you do not know its identifier.
- [Select filings](guide/selecting-filings.md) by category, native form, date and amendment status.
- Read the [market page](markets/index.md) for the source you use.
