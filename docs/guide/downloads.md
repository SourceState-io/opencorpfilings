---
title: 'Download one company''s filings with a manifest'
description: 'Save a bounded selection of company filings with source URLs, SHA-256 checksums and a manifest that supports resuming downloads.'
---

# Downloading a company's filings

```python
collection.download(directory, *, documents="primary", file_types=None, all_history=False)
```

`FilingCollection.download()` saves one company's selected filings into a
folder, with a resumable `manifest.json`. It covers **one company** and needs
an explicit **bound**. There is no multi-company or bulk download.

```python
from opencorpfilings import Company

greggs = Company("00502851", market="UK")
greggs.filings(form="annual", limit=2).download("downloads/greggs")
```

```text
{'manifest': 'downloads\\greggs\\manifest.json', 'filings': 2, 'downloaded': 2, 'skipped': 0, 'failed': 0}
```

The summary counts this run: `filings` processed, and files downloaded,
skipped as already saved, or failed. The manifest keeps every run's filings.

## The bound

The collection must have `limit=`, a `start=`/`end=` window, or you pass
`all_history=True`. Otherwise `download()` raises `ValueError`:

```python
company.filings(form="annual", limit=5).download("out/")
company.filings(form="annual", start="2020-01-01").download("out/")
company.filings(form="annual").download("out/", all_history=True)
```

## Choosing documents

| Argument | Saves |
|---|---|
| `documents="primary"` (default) | each filing's [primary document](documents.md#the-primary-document) |
| `documents="all"` | every document of each filing |
| `documents=("report", "exhibit")` | documents whose [role](documents.md#roles) is in the tuple |
| `file_types=(".pdf",)` | documents whose filename has one of these extensions; with `file_types`, `"primary"` widens to every document, since the primary file may not be of that type |

```python
apple = Company("AAPL", market="US")
apple.filings(form="annual", limit=1).download("downloads/apple-xbrl", file_types=(".xsd", ".xml"))
```

```text
{'manifest': 'downloads\\apple-xbrl\\manifest.json', 'filings': 1, 'downloaded': 7, 'skipped': 0, 'failed': 0}
```

A filing type such as SEC Form 4 is chosen with `form="4"` on the collection,
not with `file_types`.

## Layout and manifest

Each filing gets a folder named by its source filing ID, made safe as a path
segment (France's `diffuser:UIN` IDs, for example, contain `:`, which becomes
`_`). Files keep their source filenames; a repeated name within one filing,
compared ignoring case as Windows and macOS file systems do, gets a `-2`,
`-3`, ... suffix.

`manifest.json` holds the company and the request, then one entry per filing:

```text
{
 "entity_id": ..., "entity_name": ..., "market": ..., "provider": ...,
 "order_basis": ..., "form": ...,
 "filings": [
  {
   "filing": { ...filing.to_dict()... },
   "status": "ok" | "failed",
   "error": "...",                       (failed filings only)
   "documents": [
    { ...document.to_dict()..., "path": "<filing folder>/<filename>",
      "status": "downloaded" | "skipped", "sha256": ..., "bytes": ... }
   ]
  }
 ]
}
```

Reading it back, as in the
[name-to-files notebook](https://github.com/sourcestate-io/opencorpfilings/blob/main/examples/notebooks/05_find_a_company_and_get_its_files.ipynb):

```python
import json

result = apple.filings(form="annual", limit=1).download("downloads/apple-taxonomy", file_types=(".xsd", ".xml"))
manifest = json.load(open(result["manifest"], encoding="utf-8"))
[(d["filename"], d["role"], d["bytes"]) for d in manifest["filings"][0]["documents"]]
```

```text
[('aapl-20250927.xsd', 'data', 56313), ('aapl-20250927_cal.xml', 'data', 153156),
 ('aapl-20250927_def.xml', 'data', 224664), ('aapl-20250927_htm.xml', 'data', 1416841),
 ('aapl-20250927_lab.xml', 'data', 763631), ('aapl-20250927_pre.xml', 'data', 496062),
 ('FilingSummary.xml', 'generated', 42775)]
```

## Resuming and failures

- A rerun into the same folder skips any file that exists and whose SHA-256
  matches the manifest:

    ```python
    greggs.filings(form="annual", limit=2).download("downloads/greggs")
    ```

    ```text
    {'manifest': 'downloads\\greggs\\manifest.json', 'filings': 2, 'downloaded': 0, 'skipped': 2, 'failed': 0}
    ```

- A filing that raises an `OpenCorpFilingsError` is recorded with
  `"status": "failed"` and its error, and the other filings continue.
- The manifest is rewritten atomically after each filing, so an interrupted
  run keeps what it finished.
- The returned `filings` count is the number of filing entries in the
  manifest, including entries from earlier runs into the same folder.

Each file is saved through the same validated path as
[`document.download(path)`](documents.md#downloading-one-original).

## Command line

```bash
ocf download 00502851 --market UK --form annual --limit 5 --output-dir greggs/
ocf download AAPL --market US --form annual --limit 1 --output-dir apple/ --file-type xsd --file-type xml
```

`--output-dir` needs `--limit`, `--start`/`--end` or `--all-history`;
`--all-documents` saves every document. See [Command line](cli.md).
