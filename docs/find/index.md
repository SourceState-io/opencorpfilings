---
title: 'Find a company by name, ticker, ISIN or LEI'
description: 'Search company lists across SEC, EDINET, AMF, Brazil CVM, Chile CMF and ESEF. Get the identifier and Python code to open a company and retrieve its filings.'
hide:
  - toc
---

# Find a company

Type a company name, ticker, securities code, CVM code, CNPJ, RUT, ISIN or LEI. Each match gives the
market and the exact identifier to pass to `Company`, ready to copy.

<div class="ocf-find" markdown="0">
  <input id="ocf-find-query" type="search" autocomplete="off" spellcheck="false"
         placeholder="Toyota, AAPL, Petrobras, Copec, CNPJ, RUT …" aria-label="Company, ticker or code">
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
issuers on the AMF/DILA lists, active Brazilian CVM registrations, active
Chilean CMF securities issuers, and the issuers in the filings.xbrl.org ESEF
index. Register membership does not guarantee a report for every company or
period. Brazil and Chile use regulator identifiers; no local ticker mapping
is inferred. The list is rebuilt weekly; the date it was built is shown below.

The UK has no list of listed companies that may be republished, so UK names
are not on this page. Each search links to Companies House's own search, and
`find_company()` searches Companies House live. Korea is not listed: Open
DART's terms do not cover republishing its company list.

Contains information from [CVM Informação Cadastral](https://dados.cvm.gov.br/dataset/cia_aberta-cad),
made available under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
[Download the Brazil search directory](https://sourcestate-io.github.io/opencorpfilings/find/cvm-companies.json) under that license;
OpenCorpFilings filters active registrations, collapses duplicate venue rows
and adds source-name/CNPJ aliases. This data license is separate from the MIT
software license. Chilean issuer information is attributed to
[CMF Chile](https://www.cmfchile.cl/institucional/mercados/consulta.php?mercado=V&Estado=VI&entidad=RVEMI).

<p id="ocf-find-sources" class="ocf-find-sources"></p>

<script src="find.js"></script>
