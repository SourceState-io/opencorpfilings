---
title: 'OpenCorpFilings CLI: search and download filings'
description: 'Use the ocf command line to find companies, list filings and documents, and download original reports as a bounded workflow.'
---

# Command line

The `ocf` command is installed with the package. It uses the same public API,
respects the same market and source routing as `Company`, and prints one JSON
object per command with source URLs.

```text
usage: ocf [-h] [--version]
           {markets,find,search,company,filings,documents,download} ...
```

| Command | Does |
|---|---|
| `ocf markets` | list every market route with its tier, identifiers and forms |
| `ocf find QUERY` | search all markets for a company; prints the identifier to use |
| `ocf search QUERY --market M` | find source-listed companies in one market |
| `ocf company ID --market M` | show one source-resolved company |
| `ocf filings ID --market M` | list a few filing records |
| `ocf documents ID --market M` | list one filing's original documents without downloading them |
| `ocf download ID --market M` | save one original document, or with `--output-dir` a bounded set of one company's filings |

```bash
ocf markets
ocf find Toyota --limit 3
ocf search Greggs --market UK --limit 5
ocf company 00185647 --market UK
ocf filings 00185647 --market UK --form annual --limit 3
ocf documents 00185647 --market UK --form annual --latest
ocf download 00185647 --market UK --form annual --latest --output annual.zip
ocf download 00502851 --market UK --form annual --limit 5 --output-dir greggs/
ocf filings AAPL --market US --form annual --limit 3 --user-agent "Your Name you@example.com"
```

## Options shared by `search`, `company`, `filings`, `documents` and `download`

| Option | Meaning |
|---|---|
| `identifier` (positional) | company identifier, exact name, or search query |
| `--market MARKET` | required; market code such as `US`, `UK` or `JP` |
| `--source SOURCE` | explicit source route, such as `esef_index` |
| `--cache-dir DIR` | optional local metadata response cache |
| `--user-agent UA` | identifying SEC User-Agent for this command; US only (otherwise set `OPENCORPFILINGS_SEC_USER_AGENT`) |

Other credentials come from the [environment variables](../getting-started.md#credentials).

## `ocf markets`

Prints `{"routes": [...]}`: one entry per route, with `market`, `source`,
`provider`, `tier`, `identifiers`, `forms`, `native_forms`, `date_filters`,
`auth` and `coverage_note`. It needs no credentials or network access. A
market with both a national route and the ESEF index appears twice.

```json
{"market": "JP", "source": null, "provider": "edinet", "tier": "supported",
 "identifiers": ["four-digit securities code", "EDINET code"],
 "forms": ["annual", "interim", "quarterly", "current", "other"],
 "native_forms": false, "date_filters": true,
 "auth": "required API key: api_key=, OPENCORPFILINGS_EDINET_API_KEY or EDINET_API_KEY",
 "coverage_note": "Discovery scans EDINET's daily lists one day per request: about 30 s for a recent filing, minutes for one filed many months back unless start= narrows it. Quarterly reports ended in April 2024."}
```

## `ocf find`

```text
ocf find [--market MARKETS] [--limit LIMIT] [--no-live] [--refresh] query
```

| Option | Meaning |
|---|---|
| `--market` | limit to a market (repeatable) |
| `--limit` | maximum results (default 10) |
| `--no-live` | skip the live Companies House search |
| `--refresh` | rebuild the cached company index first |

Prints `{"query": ..., "results": [...]}` with `name`, `market`,
`identifier`, `source`, `tier`, `tickers`, `isins`, `lei`, `exchange` and
`listed_by` for each match. See [`find_company`](finding-companies.md#find_company).

## `ocf search`

`--limit` sets the maximum issuer candidates (default 10). Prints
`{"market": ..., "results": [...]}` with `entity_id`, `name`,
`jurisdiction`, `provider`, `source_url`, `search_source_url`, `source_id`
and `requires_resolution` for each candidate.

```bash
ocf search KONE --market FI --limit 5
ocf filings 552 --market FI --form annual --limit 1   # 552 is the source-listed KONE ID
```

## `ocf company`

Prints `entity_id`, `name`, `jurisdiction`, `provider` and `source_url` of the
resolved issuer.

## `ocf filings`

| Option | Meaning |
|---|---|
| `--form` | convenience category or exact source form |
| `--start`, `--end` | filing date bounds, `YYYY-MM-DD` |
| `--limit` | maximum filing records (default 5) |

Prints `{"order_basis": ..., "filings": [...]}` with `filing_id`,
`filing_date`, `filing_type_raw`, `filing_type_normalized` and `source_url`
for each filing.

## `ocf documents`

Selects one filing with `--latest` (the default; `--form`, `--start`, `--end`
narrow it) or `--filing-id ID`, and prints `{"filing_id": ..., "source_url":
..., "documents": [...]}`, each document as `document.to_dict()`. The
`filename` and `document_type` values are what `ocf download` selects by.
Nothing is downloaded.

## `ocf download`

Without `--output-dir`, saves **one document** from one filing:

| Option | Meaning |
|---|---|
| `--latest` / `--filing-id ID` | select the latest matching filing (default) or one exact source filing ID |
| `--form`, `--start`, `--end` | narrow `--latest`; `--form` cannot be combined with `--filing-id` |
| `--document-type`, `--filename` | select one exact source document; otherwise the primary document |
| `--output PATH` | destination (default: the source filename in the current directory) |
| `--overwrite` | replace an existing destination; without it an existing file is an error |

Prints `filing_id`, `document_id`, `source_url` and the saved `path`.

With `--output-dir DIR`, saves a **bounded selection of one company's
filings** with a manifest, as
[`FilingCollection.download()`](downloads.md) does:

| Option | Meaning |
|---|---|
| `--limit N` | the newest N matching filings |
| `--start`, `--end` | a date window |
| `--all-history` | every matching filing when no `--limit`/`--start`/`--end` is given |
| `--all-documents` | every document of each filing, not only the primary |
| `--file-type EXT` | keep documents with this extension (repeatable), such as `pdf` |

One of `--limit`, `--start`/`--end` or `--all-history` is required, and
`--output-dir` cannot be combined with `--filing-id` or `--output`. It prints
the same summary as the Python call (`manifest`, `filings`, `downloaded`,
`skipped`, `failed`).

## Exit status

| Code | When | stderr |
|---|---|---|
| `0` | success | |
| `1` | an `OpenCorpFilingsError` | `ocf: <ErrorClass>: <message>` |
| `2` | invalid arguments or a local file error (`ValueError`, `OSError`) | `ocf: <message>` |

```text
$ ocf filings X --market GB
ocf: UnsupportedMarketError: unsupported market 'GB' (did you mean 'UK'?); `ocf markets` or supported_markets() lists the routes
```

`ocf find` reports any error with exit code `2`.
