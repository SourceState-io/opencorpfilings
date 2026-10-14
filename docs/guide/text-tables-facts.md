---
title: 'Extract filing text, HTML tables and XBRL facts'
description: 'Read annual report text, PDF pages, SEC sections, HTML tables and raw XBRL or iXBRL facts with OpenCorpFilings.'
---

# Text, tables and facts

Content methods read a filing's primary document, or a document or archive
member you select. What is available depends on the original's format; an
operation the format cannot support raises `UnsupportedCapabilityError`.

| You want | Call | Format conditions |
|---|---|---|
| Plain text | `filing.text()`, `document.text()`, `member.text()` | HTML/XHTML; PDF with the `pdf` extra and a text layer; route-specific package readers |
| Original markup | `filing.html()`, `document.html()`, `member.html()` | HTML/XHTML |
| Markdown | `filing.markdown()`, `document.markdown()`, `member.markdown()` | HTML/XHTML, with the `markdown` extra |
| Tables | `filing.tables()`, `document.tables()`, `member.tables()` | HTML/XHTML |
| PDF pages | `document.pages`, `document.page(n)` | PDF, with the `pdf` extra |
| Tagged facts | `filing.facts`, `filing.find_facts(...)`, `filing.facts_to_pandas()` | XBRL or inline XBRL in the original |
| 10-K/10-Q/8-K Items | `filing.sections()`, `filing.section(item)` | SEC originals with verifiable Item boundaries |

Text and facts are transformations of source material. Their provenance
points back to the original document; it does not imply that the regulator
produced the transformed representation.

## Text

```python
text = filing.text()
```

Readable HTML/XHTML text omits iXBRL header metadata and explicitly hidden
HTML while keeping visible inline fact text. On a filing, extracted text is
computed once and reused. For a ZIP package, the route's reader finds the
report inside it; for example, an ESEF index record that has only a source
ZIP joins text from all report XHTML members.

`text()`, `html()`, `markdown()` and `tables()` choose one encoding the same
way: a byte-order mark; else UTF-8 when the bytes are valid UTF-8 (filers
label UTF-8 as Latin-1); else the declared charset, with Latin-1 and ASCII
labels read as windows-1252 as browsers do; else UTF-8. Pass `encoding=` for
unlabelled legacy HTML. Where `html()` or `markdown()` cannot decode the bytes,
they raise `ParseError`; `text()` replaces them. `download()` always returns
the unmodified bytes.

`markdown()` keeps visible headings, emphasis and literal tables where the
markup expresses them, omits hidden iXBRL metadata and embedded image data,
and keeps image alt text. PDF and ZIP containers do not claim Markdown
support; select an HTML/XHTML document or archive member first.

## Tables

`tables()` returns each HTML `<table>` tag in document order as a
`FilingTable`, cell by cell as filed. Merged cells are not expanded, rows are
not padded, and no financial meaning is assigned.

```python
tenk = Company("AAPL", market="US").filings(form="annual").latest()
table = next(table for table in tenk.tables()
             if any("Total net sales" in cell.text for row in table.rows for cell in row))
[[cell.text for cell in row if cell.text] for row in table.rows[:4]]
```

```text
[[], ['2025', 'Change', '2024', 'Change', '2023'],
 ['Americas', '$', '178,353', '7', '%', '$', '167,045', '3', '%', '$', '162,560'],
 ['Europe', '111,032', '10', '%', '101,328', '7', '%', '94,294']]
```

| Object | Fields |
|---|---|
| `FilingTable` | `index` (one-based), `caption`, `rows` (each row a sequence of cells), `source_url`, `source_location`, `provenance` |
| `FilingTableCell` | `text`, `tag` (`td` or `th`), `rowspan`, `colspan` (the raw attribute strings) |

`#table=N` in `source_location` is a library position, not a browser anchor.
Parsing is limited to 100 MB. Decoding follows the rule above; pass
`encoding=` (for example `report.tables(encoding="cp949")`) for unlabelled
legacy HTML. An undecodable source raises `ParseError`. An XHTML report built from positioned `div`
elements can contain no `<table>` tags, in which case the list is empty.
Tables are not inferred from PDF layout.

## PDF pages

With the `pdf` extra, a PDF with a text layer exposes its pages with their
original one-based page numbers:

```python
pdf = filing.select_document(media_type="application/pdf")
for page in pdf.pages:
    print(page.number, page.source_location, page.text[:80])

first = pdf.page(1)       # one page, without extracting the rest
```

`FilingPage` has `number`, `text`, `document_id`, `source_url`, `provenance`
and `source_location` (the document URL with a page anchor). `pdf.text()` joins
all pages. Image-only or scanned pages return empty text; the library does not
run OCR, and empty text is not evidence that a page has no content.
Extraction is limited to 50 MB source files, 2,000 pages and 10 MB of decoded
page content. Invalid page numbers raise `ValueError` or `IndexError`.

## Tagged facts

`filing.facts` holds the raw structured fact occurrences in the original:
XBRL instance facts, or inline XBRL tags in XHTML. Values stay the filed
strings. No number conversion, scaling, unit conversion or concept mapping is
performed.

```python
accounts = Company("00185647", market="UK").filings(form="annual").latest()
fact = next(f for f in accounts.facts if f.concept_raw == "ifrs-full:Revenue")
fact.value, {key: fact.provider_metadata["attributes"].get(key) for key in ("format", "scale", "decimals")}
```

```text
('33,6 4 7', {'format': 'ixt5:num-dot-decimal', 'scale': '6', 'decimals': '-6'})
```

This J Sainsbury filing's inline XBRL was generated from a PDF, so its text
has spaces inside numbers. The format and scale travel with each inline fact,
so you can apply them yourself: `scale="6"` means millions.

### `FilingFact` fields

| Field | Meaning |
|---|---|
| `concept_raw` | the concept as tagged, such as `ifrs-full:Revenue` |
| `value` | the filed string, never a converted number |
| `unit` | the raw unit; sibling measures join with `*`, an explicit numerator/denominator with `/` |
| `period_start`, `period_end` | the context period |
| `context_id` | the source context ID |
| `dimensions` | dimension to member mapping |
| `taxonomy` | the concept's taxonomy |
| `source_location` | where the fact sits, including archive member paths |
| `provider_metadata` | source attributes, for inline facts including `format`, `scale` and `sign` |
| `provenance` | a [`Provenance`](../concepts/identifiers-dates-provenance.md#provenance) record |

### Filtering facts

```python
filing.find_facts(*, concept_raw=None, period_start=None, period_end=None, unit=None,
                  context_id=None, taxonomy=None, dimensions=None, limit=None)
```

Filters are exact matches on raw fields; `dimensions` matches the specified
dimension members. `limit=` bounds the result.

```python
filing.find_facts(concept_raw="ifrs-full:Revenue", limit=5)
```

`filing.facts_to_pandas()` (with the `pandas` extra) returns one row per
occurrence, and `fact.to_dict()` one JSON-safe row:

```python
report = Company("969500XXRPGD7HCAFA90", market="FR").filings(form="annual").latest()
frame = report.facts_to_pandas()
frame[frame["concept_raw"] == "ifrs-full:Revenue"][["value", "unit", "period_end"]].head()
```

```text
     value         unit  period_end
0  9 480,6  iso4217:EUR  2025-12-31
1  8 648,9  iso4217:EUR  2024-12-31
```

Facts are parsed once per filing object; `filing.facts` returns a new list on
each access, so editing it does not alter the cache. The parser rejects
duplicate context, unit or continuation IDs rather than silently assigning a
fact to whichever duplicate appeared last. Non-XML inline reports are outside
the parser's capability.

## SEC Item sections

On the SEC route, original HTML 10-K, 10-Q and 8-K filings expose
source-linked Item sections when their boundaries can be verified against the
original:

```python
item_7 = filing.section("Item 7")
print(item_7.title)
print(item_7.text[:400])
```

```text
Management’s Discussion and Analysis of Financial Condition and Results of Operations
Item 7. Management’s Discussion and Analysis of Financial Condition and Results of Operations
The following discussion should be read in conjunction with the consolidated financial statements and accompanying notes included in Part II, Item 8 of this Form 10-K. This Item generally discusses 2025 and 2024 items and year-to-year comparisons between 2025 and 2024. Discussions of 2023 items and year-t
```

- `filing.sections()` lists every verified section; `filing.section(item)`
  selects one (`"Item 8"` and `"8"` both work).
- 10-Q Item numbers repeat across Parts: `filing.section("1", part="II")`.
  Omitting `part` for a repeated Item raises `ValueError`; a missing Item
  raises `KeyError`.
- A heading that jointly covers several Items is one section with a range
  label (`item="10-13"`, `items=("10", "11", "12", "13")`); any listed Item
  selects it.
- For 8-Ks, Item numbers and captions must match the SEC Form 8-K captions,
  such as `filing.section("Item 2.02")`.
- Ambiguous or unverifiable layouts, other forms and amended filings
  (`10-K/A`, `10-Q/A`, `8-K/A`) raise `UnsupportedCapabilityError`. Use
  `company.filings(form="annual", include_amendments=False).latest()` to
  select an original.

`FilingSection` has `item`, `title`, `text`, `document_id`, `source_url`,
`start_line`, `end_line` (one-based positions in `filing.text()`),
`provenance`, `part`, `references` and `items`.

### Page and exhibit pointers

Some 10-Ks point an Item to printed pages or an exhibit instead of containing
it. Those pointers are returned as `FilingSectionReference` objects (`kind`,
`target`, `source_text`, `document_id`, `source_url`, `source_line`,
`provenance`), never merged into section text:

```python
for reference in filing.section_references("Item 8"):
    target = reference.resolve(filing)   # a FilingDocument, a FilingPrintedPage, or a tuple of pages
    print(reference.kind, reference.source_text)

page = filing.primary_document.printed_page("38")   # one page verified by its printed footer
print(page.label, page.start_line, page.end_line)
```

A page result is returned only when HTML page breaks and consecutive printed
footers verify it; ambiguous layouts raise `UnsupportedCapabilityError`. The
[provider notes](https://github.com/sourcestate-io/opencorpfilings/blob/main/PROVIDER_NOTES.md#sec-sections-and-source-navigation)
describe the matching rules in full.
