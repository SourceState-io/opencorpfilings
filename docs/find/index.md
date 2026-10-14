---
title: 'Find a company by name, ticker, ISIN or LEI'
description: 'Search company lists across SEC, EDINET, AMF and ESEF. Get the identifier and Python code to open a company and retrieve its filings.'
hide:
  - toc
---

# Find a company

Type a company name, ticker, securities code, ISIN or LEI. Each match gives the
market and the exact identifier to pass to `Company`, ready to copy.

<div class="ocf-find" markdown="0">
  <input id="ocf-find-query" type="search" autocomplete="off" spellcheck="false"
         placeholder="Toyota, AAPL, 7203, FR0010307819, 969500XXRPGD7HCAFA90 …" aria-label="Company, ticker or code">
  <p id="ocf-find-status" class="ocf-find-status" aria-live="polite">Loading the company list…</p>
  <ol id="ocf-find-results" class="ocf-find-results"></ol>
  <p id="ocf-find-uk" class="ocf-find-uk" hidden></p>
</div>

The same search runs in Python, including a live UK search:

```python
from opencorpfilings import find_company

find_company("Toyota")[0].company()
```

## What this page searches

It searches the official lists `find_company()` downloads: US companies with
SEC tickers, listed Japanese companies on the EDINET code list, the French
issuers on the AMF/DILA lists, and the issuers in the filings.xbrl.org ESEF
index. The list is rebuilt weekly; the date it was built is shown below.

The UK has no list of listed companies that may be republished, so UK names
are not on this page. Each search links to Companies House's own search, and
`find_company()` searches Companies House live. Korea is not listed: Open
DART's terms do not cover republishing its company list.

<p id="ocf-find-sources" class="ocf-find-sources"></p>

<script src="find.js"></script>
