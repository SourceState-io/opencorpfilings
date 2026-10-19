---
title: 'Filing identifiers, dates and source provenance'
description: 'Understand original filing IDs, native form codes, report periods, publication times, index dates and document provenance.'
---

# Identifiers, dates and provenance

OpenCorpFilings keeps what each regulator says and does not reinterpret it.
IDs are the source's, dates are kept apart, and every object carries a pointer
back to the record it came from.

## Identifiers

| Field | Meaning | Examples |
|---|---|---|
| `filing.filing_id` | native record ID or a documented composite of source fields (for BR/CL) | SEC accession `0000320193-25-000079`; EDINET document ID `S100Y8NY`; France `diffuser:UIN` `370:623156_20260408`; ESEF index record `24793` |
| `filing.entity_id` | the source's own issuer ID | CIK, Companies House number, EDINET code, LEI |
| `document.document_id` | the source's or route's ID for one document | |
| `filing.jurisdiction` | the market code | `US`, `UK`, `JP`, `FR`, `IT` |
| `filing.provider`, `filing.regulator` | the route and the regulator behind it | `sec` / US Securities and Exchange Commission |
| `filing.source_url` | the filing's record or index page at the source | |

The same company can have different IDs on different routes (a CIK on the
SEC route, an LEI on the ESEF index) and can be reachable through more than
one market. The library does not merge them.

## Form type

| Field | Meaning |
|---|---|
| `filing_type_raw` | the source's own form or category code, unchanged: `10-K`, `AA`, `120`, `300005`, `ESEF` |
| `filing_type_normalized` | a conservative convenience category: `ANNUAL`, `QUARTERLY`, `INTERIM`, `CURRENT`, `PROSPECTUS`, `OWNERSHIP`, `OTHER` (the values of `FILING_CATEGORIES`), or `None` when the source cannot justify one |
| `title` | the source's title or description |

The category only says which `form=` request selects a filing. It does not
claim that two filings in the same category have the same contents or
accounting meaning. Each [market page](../markets/index.md) lists the codes
behind each category.

## Dates

A date the source does not state is `None`, never a guess.

| Field | Meaning | Where it comes from |
|---|---|---|
| `filing_date` | when the regulator received or published the filing | SEC filing date; Companies House filing history date; EDINET submission date; France publication date; `None` on the ESEF index and Sweden |
| `published_at` | the source's timestamp, where it gives one | SEC acceptance time; EDINET submission time (JST); France, Finland and Denmark publication time |
| `period_start`, `period_end` | the reporting period the filing covers, where the source states it | SEC report date; Companies House "made up to" date; EDINET period; ESEF index period end; Open DART report month; `None` for France |
| `index_added_at` | when a secondary index received the record | ESEF index only; never substituted for a filing date |

`start=`/`end=` filter on the route's source date for a filing, usually
`filing_date`; Japan uses EDINET's source file date
(`provider_metadata["source_file_date"]`). Each collection's
`order_basis` names the ordering it uses; see
[Selecting filings](../guide/selecting-filings.md#order).

## Amendments and language

| Field | Meaning |
|---|---|
| `amendment` | `True` when the source flags the filing as an amendment or correction, `False` when it flags an original, `None` when it does not say |
| `language` | the filing's or document's language where the route knows it, such as `en`, `ja` or `it`; France's source labels are mapped to ISO 639-1 codes (`Français` → `fr`) and an unknown label is kept as given |

Category requests exclude amendments by default on routes that flag them;
see [Amendments](../guide/selecting-filings.md#amendments).

## Provenance

Every `Entity`, `Filing`, `FilingDocument`, `FilingFact`, `FilingPage`,
`FilingTable`, `FilingSection` and archive member has a `provenance`
attribute holding a `Provenance` record (on an `Entity` it can be `None`):

| Field | Meaning |
|---|---|
| `provider` | the route, such as `sec` or `france_oam` |
| `regulator` | the regulator or source name |
| `jurisdiction` | the market code |
| `source_url` | the exact source record or document the object came from |
| `source_id` | the source's ID for that record |
| `retrieved_at` | when the library read it (UTC), where recorded |
| `raw` | the source record, unchanged |

Derived objects keep pointers to their original: a `FilingPage` has the
document URL with a page anchor (`page.source_location`), a fact or table
inside a ZIP keeps the package URL and the member's path chain, and a
`FilingSection` keeps its document and one-based line span in
`filing.text()`. Text and facts are transformations of source material; their
provenance does not imply that the regulator produced the transformed
representation.

The library also checks bindings: a listed filing must belong to the
selected issuer, market and provider, and a document whose URL is changed
after selection raises `DownloadError` rather than attributing bytes to
another source.

## Source fields passed through

| Attribute | Contents |
|---|---|
| `filing.provider_metadata` | the source's own fields for the filing, plus a few route keys such as `source_file_date` (JP) or `matched_by` (FR) |
| `filing.raw` | the same mapping: the source's own record, unchanged |
| `document.provider_metadata`, `entity.provider_metadata`, `fact.provider_metadata` | source fields for that object; for inline facts, the original `format`, `scale` and `sign` attributes |
| `provenance.raw` | the source record behind the object |

These contents are whatever the source returned, so they differ by route and
can change when a source changes. They are outside the
[stability promise](../stability.md); the named fields above are inside it.

## JSON and DataFrames

| Call | Returns |
|---|---|
| `filing.metadata` | a dict of the filing fields, dates as `date`/`datetime` objects |
| `filing.to_dict()` | the same fields JSON-safe, plus `provenance_source_url` and `provenance_source_id` |
| `document.to_dict()` | one JSON-safe row describing a document, without its content |
| `fact.to_dict()` | one JSON-safe row; `value` stays the filed string |
| `collection.to_pandas(n)` | the first `n` filings as a DataFrame (`pandas` extra) |
| `filing.facts_to_pandas()` | one row per fact occurrence (`pandas` extra) |
