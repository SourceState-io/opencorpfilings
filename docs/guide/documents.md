---
title: 'Access original filing documents and ZIP packages'
description: 'Select original report documents, exhibits and archive members. Read nested ESEF ZIP packages while retaining source provenance.'
---

# Documents

A `Filing` lists its original source documents as `FilingDocument` objects.
Listing reads document metadata only; nothing is downloaded until you ask for
content.

```python
filing.documents          # every original the source lists, verified and bound to the filing
filing.primary_document   # the main document
filing.select_document(document_type="EX-21.1")
```

## Roles

Each document has a `role` saying what it is within its filing:

| Role | Meaning |
|---|---|
| `report` | the filed report or statement itself, or its package |
| `exhibit` | an exhibit, such as an SEC `EX-21.1` |
| `annex` | an attachment to the report (EDINET attachments) |
| `announcement` | a cover notice or announcement beside the report |
| `data` | structured data: XBRL instances, schemas, linkbases, xBRL-JSON, CSV |
| `generated` | a file the source system produced: indexes, renderings such as EDGAR's `R*.htm`, the full-submission `.txt` |
| `other` | anything else |

`role` can be `None` when a route does not classify a document.

```python
from collections import Counter

Counter(document.role for document in filing.documents)   # Apple's FY2025 10-K
```

```text
Counter({'generated': 78, 'exhibit': 6, 'data': 6, 'other': 2, 'report': 1})
```

## The primary document

`filing.primary_document` follows one rule on every route:

1. If exactly one document is flagged as primary by the source, it wins.
2. Otherwise, the `report` role comes first, then format: ZIP package, then
   XHTML, then PDF, then HTML; then source order.

`filing.text()`, `filing.html()`, `filing.markdown()`, `filing.tables()` and
`filing.download()` all read the primary document. On the SEC route,
`primary_document` uses the primary filename EDGAR already supplies, so it
fetches that one original without listing the whole filing archive.

## Selecting one document

```python
filing.select_document(*, document_id=None, document_type=None, filename=None,
                       media_type=None, language=None, description=None)
```

Filters match exact source metadata and combine. With no filter it returns
the primary document. No match raises `UnsupportedCapabilityError`; more than
one match raises `ValueError` instead of guessing.

```python
exhibits = [document for document in filing.documents if document.role == "exhibit"]
[(document.document_type, document.filename) for document in exhibits]
```

```text
[('EX-21.1', 'a10-kexhibit21109272025.htm'), ('EX-23.1', 'a10-kexhibit23109272025.htm'),
 ('EX-31.1', 'a10-kexhibit31109272025.htm'), ('EX-31.2', 'a10-kexhibit31209272025.htm'),
 ('EX-32.1', 'a10-kexhibit32109272025.htm'), ('EX-4.1', 'a10-kexhibit4109272025.htm')]
```

```python
subsidiaries = filing.select_document(document_type="EX-21.1")
subsidiaries.text()[:300]
```

```text
'EX-21.1\n3\na10-kexhibit21109272025.htm\nEX-21.1\nExhibit 21.1\nSubsidiaries of\nApple Inc.*\nJurisdiction\nof Incorporation\nApple Asia Limited\tHong Kong\nApple Asia LLC\tDelaware, U.S.\nApple Canada Inc.\tCanada\nApple Computer Trading (Shanghai) Co., Ltd.\tChina\nApple Distribution International Limited\tIreland\n'
```

### `FilingDocument` fields

| Field | Meaning |
|---|---|
| `document_id` | the source's ID for the document |
| `filing_id` | the filing it belongs to |
| `filename` | the source filename |
| `source_url` | where the original is retrieved from |
| `media_type` | such as `text/html`, `application/pdf`, `application/zip` |
| `document_type` | the source's label, such as `10-K` or `EX-21.1` |
| `description` | the source's description, where given |
| `language` | where the source states it |
| `is_primary` | the source's primary flag |
| `role` | see [Roles](#roles) |
| `provider_metadata` | source fields passed through |
| `provenance` | a [`Provenance`](../concepts/identifiers-dates-provenance.md#provenance) record |

`document.to_dict()` returns one JSON-safe row describing the document,
without its content.

## Downloading one original

```python
document.download()               # the original bytes
document.download("report.zip")   # streams to the path and returns it
filing.download("annual.html")    # the primary document
```

With a path, the bytes go to a temporary file in the destination directory
and replace the target only after a complete, validated save; a failed save
leaves an existing target in place. An empty response is rejected. PDF and ZIP
originals are checked by their byte signature, and a ZIP needs a readable
archive directory, so an HTML error page served with HTTP 200 is not accepted
as the document. `download()` without a path loads that one document into
memory.

Documents stay bound to their source URL from selection onward: changing a
document's URL raises `DownloadError` on content access rather than
attributing bytes to a different source.

`document.sha256()` returns the SHA-256 of the selected original bytes. After a
streamed save it verifies and hashes the local file without downloading again.
Two documents with the same LEI and period are not proven identical until
their hashes match.

## ZIP packages and archive members

Many European and Japanese filings arrive as a ZIP package. `document.members`
lists the files inside as `FilingArchiveMember` objects without unpacking the
package to disk:

```python
from opencorpfilings import Company

report = Company("969500XXRPGD7HCAFA90", market="FR").filings(form="annual").latest()
package = report.primary_document
[(member.entry_path, member.size) for member in package.members][:3]
```

```text
[('Legrand-2025-12-31-1-FR/META-INF/taxonomyPackage.xml', 1082),
 ('Legrand-2025-12-31-1-FR/reports/Legrand-2025-12-31-1-FR.xhtml', 91246552),
 ('Legrand-2025-12-31-1-FR/www.legrandgroup.com/Legrand-2025-12-31_cal.xml', 51696)]
```

```python
member = next(m for m in package.members if m.entry_path.endswith(".xhtml"))
member.filename           # the name inside the package
member.source_location    # package URL plus the member's path chain
member.text()             # readable HTML/XHTML text
member.html()             # the decoded original markup
member.tables()           # literal HTML tables
member.download("report.xhtml")
```

- A nested ZIP, or a gzip-wrapped ZIP, exposes its own `.members`, up to five
  levels, with the full source path.
- Extraction is limited to 100 MB per member by default. Pass
  `member.download(max_bytes=...)` for another limit, or `max_bytes=None` for
  an unrestricted read.
- `member.download(path)` extracts in bounded chunks and replaces the target
  only after extraction and the ZIP CRC check complete.
- Changing a member's or its package's source URL, or the entry path, raises
  `DownloadError` before cached content is returned.

The original package itself remains available through `package.download()`.

## What each route lists

| Route | Documents |
|---|---|
| US SEC | the EDGAR filing index: the report, typed exhibits with their index descriptions, XBRL data and generated files |
| UK Companies House | public PDF, XHTML or ZIP; API document representations with a key |
| JP EDINET | the native ZIP, PDF, attachments, and English and CSV packages when flagged |
| FR Info-Financiere | one original attachment per record (PDF, ZIP or XHTML; `.xbri` is treated as ZIP) |
| ESEF index | indexed XHTML, the source ZIP, and derived xBRL-JSON where indexed |

The market pages have the details.
