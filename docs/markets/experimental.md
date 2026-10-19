---
title: 'Experimental filing routes: Brazil, Chile, Europe and Open DART'
description: 'Review experimental CVM, CMF, European and South Korean filing routes, with source coverage and limitations.'
---

# Experimental routes

<span class="ocf-tier ocf-tier--experimental">experimental</span> · BR, CL, KR, ES, NL, DK, SE, PL, FI

These routes have narrower release guarantees than supported routes. Brazil
and Chile are new in 1.1.0, with live original-document checks recorded in
[BENCHMARKS.md](https://github.com/SourceState-io/opencorpfilings/blob/main/BENCHMARKS.md#brazil-and-chile-2026-10-19). Opening a `Company` on one emits an
`ExperimentalRouteWarning` once per route and process:

```text
ExperimentalRouteWarning: ES/spain_cnmv is an experimental route: it has not been qualified for this release, so results may be incomplete. Supported routes: US, UK, JP, FR.
```

They are outside the [stability promise](../stability.md): a minor release
may change, promote or remove them. The six European routes passed a
second-wave qualification run on 2026-10-09 and stay experimental until the
maintainers complete the release review; Korea could not be qualified because Open DART's
document endpoint reported maintenance throughout
([BENCHMARKS.md](https://github.com/sourcestate-io/opencorpfilings/blob/main/BENCHMARKS.md#route-qualification-v3-second-wave-declared-2026-10-09)).

The named examples below are single checks, not measures of national
coverage. Where the ESEF index covers the same country (DK, ES, FI, NL, SE),
`source="esef_index"` is the [limited alternative](esef.md).

```python
from opencorpfilings import Company

Company("005930", market="KR").filings(form="annual").latest()
Company("A-48010615", market="ES").filings(form="annual").latest()
Company("ASML Holding N.V.", market="NL").filings(form="annual").latest()
Company("DK-61056416", market="DK").filings(form="annual").latest()
Company("502017-7753", market="SE").filings(form="annual").latest()
Company("mBank Spółka Akcyjna", market="PL").filings(form="annual").latest()
Company("KONE Oyj", market="FI").filings(form="annual").latest()
```

## Brazil and Chile

The new [Brazil CVM](br.md) and [Chile CMF](cl.md) guides cover identifiers,
forms, original documents, request bounds and source attribution. Both are
keyless. Brazil exposes IPE PDFs; Chile exposes IFRS PDFs and classic XBRL.

## Korea (Open DART)

| Field | Value |
|---|---|
| Provider | `open_dart` · Financial Supervisory Service Open DART |
| Identifiers | six-character stock code (can contain letters), eight-digit corporation code |
| Categories | annual, interim, quarterly, other; amendments flagged (`include_amendments`) |
| Order | `filing_date` |
| Auth | API key: `api_key=`, `OPENCORPFILINGS_DART_API_KEY` or `OPENDART_API_KEY`, from [Open DART](https://engopendart.fss.or.kr/) |

- Search: Korean names and exact stock codes use DART's
  [public company selector](https://dart.fss.or.kr/corp/searchCorp.ax);
  English names use the English selector; both fall back to the
  [official corporation registry](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018).
  The selector is HTML, not a versioned API.
- Category requests ask the source for that report type. Only the periodic
  report title itself is classified; English `Semi-annual Report` titles are
  interim, not annual.
- Documents: the original disclosure ZIP (`report`) and, for periodic
  reports, the XBRL ZIP (`data`) when available. Raw facts from the classic
  XBRL instance.
- `get_filing(receipt)` uses a bounded listing scan: the official API has
  date filters but no exact receipt lookup.
- Maintenance status `800` raises `SourceUnavailableError`.
- Korea is not in the `find_company` index.

## Spain (CNMV)

| Field | Value |
|---|---|
| Provider | `spain_cnmv` · CNMV annual financial report register |
| Identifiers | issuer NIF, such as `A-48010615` |
| Categories | annual, interim |
| Order | `filing_date` (publication date) |
| Auth | none |

- `form="annual"` and `form="interim"` use separate official registers; an
  unfiltered listing merges both by publication date, with a five-year default
  lookup window.
- `search_companies(..., market="ES")` searches the official issuer-name
  register.
- Annual: financial-report links and the ESEF ZIP, with raw inline facts from
  the report XHTML. Interim: original PDFs, annexes and XBRL XML, with raw
  classic XBRL facts. Iberdrola interim report `2026103709` exposed four
  original documents, including an XBRL instance with 1,110 raw facts.

## Netherlands (AFM)

| Field | Value |
|---|---|
| Provider | `netherlands_oam` · Netherlands Authority for the Financial Markets / AFM |
| Identifiers | exact register issuer name, such as `ASML Holding N.V.` |
| Categories | annual, interim (the register's annual and half-yearly categories) |
| Order | `filing_date` |
| Auth | none |

- `published_at` is the register export's filing time, read as Amsterdam time
  (the source states no offset); `filing_date` is its date. A record read by
  direct lookup has the detail page's filing date and no `published_at`.
- Reads the AFM financial-reporting register with bounded issuer metadata
  (`max_records=500` by default).
- Documents: individual original `.xbri`, ZIP or PDF files; text from the
  report XHTML inside a ZIP, PDF text where available; raw inline facts.
- Direct record lookup is supported.

## Denmark (Danish FSA)

| Field | Value |
|---|---|
| Provider | `denmark_oam` · Danish Financial Supervisory Authority / OAM |
| Identifiers | source business ID, such as `DK-61056416`, or exact issuer name |
| Categories | annual, interim (native annual and half-yearly categories) |
| Order | `published_at` |
| Auth | none |

- `published_at` is the announcement's publication time, read as Copenhagen
  time (the source states no offset).
- Name search accepts ASCII spellings of Danish names. Bounded source pages
  (`max_pages=20`).
- Documents: individual original ZIP, PDF, HTML or TXT links. An HTML cover
  notice beside a PDF or ZIP is an `announcement`, so the report is primary.
- Some issuers file only an HTML announcement and publish the report
  elsewhere (Danske Bank's H1 2026); then the announcement is the only
  document. Matas filed its H1 2025/26 report under the annual category, so
  `form="interim"` does not find it.

## Sweden (Finanscentralen)

| Field | Value |
|---|---|
| Provider | `sweden_oam` · Finansinspektionen / Finanscentralen |
| Identifiers | company registration number, such as `502017-7753` |
| Categories | annual, interim, quarterly |
| Order | `report_period_label` |
| Auth | none |

- The source gives a year/month label only: no filing date and no
  `period_end`. The label is kept in `provider_metadata`, and date filters
  raise `UnsupportedCapabilityError`.
- Search and report tables are paged with bounds (`max_search_pages=20`,
  `max_report_pages=20`, raisable to 100).
- Same-period rows in different languages become documents of one filing. A
  period listed twice with the same language becomes a separate record with a
  `:2` suffix and `repeated_period` in metadata.
- The table declares no file format, so `download()` detects ZIP, PDF or XHTML
  and updates the document. Correction history is not classified.

## Poland (KNF)

| Field | Value |
|---|---|
| Provider | `poland_oam` · Polish Financial Supervision Authority / KNF OAM |
| Identifiers | exact source issuer name, such as `mBank Spółka Akcyjna` |
| Categories | annual: `RR` (standalone), `SRR` and `SRR-I` (consolidated) |
| Order | `source_search_order` (KNF receipt date) |
| Auth | none |

- Scans at most 20 search pages by default (`max_pages=`). Search returns
  distinct issuer names from the first source report page.
- The record supplies a receipt date, local receipt time, report year and
  correction flag. The report year is not converted to a period end.
  Category requests return original reports by default.
- A KNF package holds several documents, including a nested `.rap` and
  gzip-wrapped ESEF ZIP. `text()` reads the ESEF-named report when there is
  one, otherwise the largest document (often the management report).
  Standalone `RR` reports carry no XBRL tags.

## Finland (Nasdaq OAM)

| Field | Value |
|---|---|
| Provider | `finland_oam` · Finland OAM / Nasdaq Helsinki |
| Identifiers | exact OAM company name (`Nokia`, `UPM-Kymmene`, `KONE Oyj`) or numeric source company ID (`552` for KONE) |
| Categories | annual (category 270), interim (78 half-year report; 153 interim reports and financial statement releases) |
| Order | `published_at` |
| Auth | none |

- Search defaults to the past five calendar years; pass `start=` for earlier
  notices. A 20-page safety bound applies (`max_pages=`).
- Documents: original ZIP, PDF or XHTML attachments.
- Coverage note: Nasdaq's general terms restrict automated capture; the
  access-terms review is required before public distribution.

```bash
ocf search KONE --market FI --limit 5
ocf filings 552 --market FI --form annual --limit 1
```

## Source terms

Each source's access route and reuse terms are in
[Source access and rights](../reference/source-access.md); the
[European source matrix](https://github.com/sourcestate-io/opencorpfilings/blob/main/EUROPE_SOURCES.md)
covers national portals country by country.
