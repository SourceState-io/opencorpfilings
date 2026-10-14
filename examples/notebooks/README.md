# Example notebooks

| Notebook | Shows |
|---|---|
| `01_quickstart.ipynb` | one SEC filing: route profile, document roles, text, an Item, facts |
| `02_find_companies_and_filings.ipynb` | search by name in UK, FR, JP; early errors; a filings table |
| `03_documents_and_downloads.ipynb` | exhibits, ESEF package members, per-company download, `file_types` |
| `04_text_tables_and_facts.ipynb` | facts in UK and FR, an HTML table, the ESEF index's history |
| `05_find_a_company_and_get_its_files.ipynb` | `find_company` by name, ticker, code, ISIN or LEI; opening a match; `file_types` downloads |

Install with `pip install '.[pdf,markdown,pandas]'` and Jupyter. In the first
code cell, uncomment the SEC identity example and replace it with your name
or organization and a working contact email:

```python
import os

os.environ["OPENCORPFILINGS_SEC_USER_AGENT"] = "Alex Morgan alex@example.com"
```

The format is a name, a space, then an email. `Example Research
filings@example.com` illustrates an organization contact. These are examples,
not default values: use your own details. This identifies your SEC requests;
no SEC account or API key is needed. An identity already set in your process
environment works too. See the [setup guide](../../docs/getting-started.md#sec-request-identity).

Japan also needs `OPENCORPFILINGS_EDINET_API_KEY`. Stored outputs come from
`python scripts/run_notebooks.py
examples/notebooks/*.ipynb`; downloads land in `examples/notebooks/downloads/`.
