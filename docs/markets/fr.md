---
title: 'France AMF annual reports in Python'
description: 'Find French issuer filings through AMF and DILA Info-Financiere by LEI or exact name, with original documents and source dates.'
---

# France (AMF / DILA Info-Financiere)

<span class="ocf-tier ocf-tier--supported">supported</span> · market `FR` · provider `france_oam` · regulator AMF / DILA Info-Financiere OAM

## Source

France's officially appointed mechanism (OAM) for regulated information,
published by DILA for the AMF through the
[Info-Financiere open API](https://www.info-financiere.gouv.fr/pages/api0/).
Each record is one source event: a publication with one original attachment.
An ESEF index row for the same report, if one exists, is a separate record on
the [ESEF index route](esef.md); neither identity nor chronology is inferred
from it.

## Identifiers

| Identifier | Example |
|---|---|
| LEI (20 characters) | `Company("969500XXRPGD7HCAFA90", market="FR")` |
| exact source issuer name | `Company("AB SCIENCE", market="FR")`; a name associated with more than one LEI raises `AmbiguousEntityError` |

`search_companies("Legrand", market="FR")` groups the source's issuer-name
records by name and LEI. The OAM attaches LEIs inconsistently: some issuers'
annual reports carry no LEI (SEB) or a second LEI of the same group (AXA). The
route therefore also matches the share ISINs on the issuer's own LEI-tagged
record; `provider_metadata["matched_by"]` says whether a filing matched by
`lei` or `isin`. A search result carries only the LEI, so it has
`requires_resolution=True`: `Company(result)` resolves it, adding the ISINs,
before listing filings.

## Forms

Every OAM record carries a **primary** category code and a list of
**secondary** codes, from
[DILA's code list](https://echanges.dila.gouv.fr/OPENDATA/AMF/0%20Presentation%20et%20documentation%20flux%20AMF/Notices_relatives_au_Flux_AMF_20210120.pdf).
The route maps three code families to categories:

| Category | Codes |
|---|---|
| `annual` | `003000` (annual financial report) |
| `interim` | `004000` (half-year financial report) |
| `quarterly` | `005000`, `005001`, `005002` (quarterly information) |

A category request selects records whose primary code **or** any secondary
code is in that family. `filing_type_raw` is always the record's primary code;
`filing_type_normalized` is set when the primary and secondary codes point to
exactly one category.

This is why an annual report can carry a code outside the `003000` family. A
universal registration document (*document d'enregistrement universel*) has
primary code `300005` and carries the annual code `003000` in its secondary
list, because it serves as the annual financial report:

```python
from opencorpfilings import Company, search_companies

legrand = Company(search_companies("Legrand", market="FR", limit=1)[0])
report = legrand.filings(form="annual").latest()
report, report.title, report.filing_type_raw
```

```text
(<Filing 370:623156_20260408 300005 ANNUAL filed=2026-04-08 FR/france_oam>,
 "DOCUMENT D'ENREGISTREMENT UNIVERSEL 2025", '300005')
```

The secondary codes stay in `provider_metadata["informationdeposee_inf_stp_inf"]`.

**Native codes.** `form=` accepts the five codes above (`003000`, `004000`,
`005000`, `005001`, `005002`) as exact codes; any other code, such as
`300005`, raises `UnsupportedCapabilityError`. An exact code matches a record
that carries it as primary or secondary code, as the source query does, so
`form="003000"` also returns a registration document whose primary code is
`300005`.

Other notes on categories:

- Code `002003` is an availability notice and is left unclassified.
- The quarterly category can contain a revenue update rather than full
  accounts; the source title and raw code remain on the filing.
- A half-year report filed as an update to the universal registration
  document (BNP Paribas) is not coded `004000`, so `form="interim"` does not
  select it.

## Dates

| Field | Source value |
|---|---|
| `published_at` | the OAM publication time (`uin_dat_amf`) |
| `filing_date` | the date of `published_at`; `start=`/`end=` filter on it, pushed to the source API |
| `period_end` | `None`: the OAM states no report period |

`order_basis` is `published_at`.

## Filing IDs and amendments

`filing_id` is `diffuser:UIN`, the source key the portal defines (diffuser
code plus UIN):

```python
Company("AB SCIENCE", market="FR").get_filing("432:628645_20260513")
```

Direct lookup checks the issuer LEI and reads that record. A record whose
source status is not `NEW` is an amendment; category requests exclude
amendments by default.

## Documents and content

- One original attachment per record, `is_primary=True`,
  `document_type="original_oam_attachment"`, role `report` for annual,
  interim and quarterly records and `other` otherwise.
- PDF, ZIP or XHTML as linked. An `.xbri` file is treated as a ZIP and keeps
  its source filename.
- Text from HTML/XHTML, including the report inside a ZIP, and PDF text where
  extractable.
- Raw inline XBRL facts from the first tagged report in a ZIP (`.xhtml`,
  `.htm` or `.html`). Members of 16 MB or more are parsed from a temporary
  file, up to 2 GB; Michelin's FY2025 XHTML exceeds 100 MB and yields 457
  facts. Values stay the filed strings, such as `9 480,6`.

```python
package = report.primary_document
[(member.entry_path, member.size) for member in package.members][:2]
```

```text
[('Legrand-2025-12-31-1-FR/META-INF/taxonomyPackage.xml', 1082),
 ('Legrand-2025-12-31-1-FR/reports/Legrand-2025-12-31-1-FR.xhtml', 91246552)]
```

## Authentication and limits

No credentials. Requests use bounded pages of up to 100 records. The source
API stops paging at an offset of 10,000; a request that would pass it raises
`UnsupportedCapabilityError`, so narrow it by form or date.

DILA's reuse terms require attribution to DILA, the download URL, the
downloaded filename and the file date. The library keeps these fields on each
filing and document.

## Known gaps

- No report period (`period_end` is `None`).
- Interim selection depends on the source coding a record `004000`.
- A first `filing.text()` on a large report downloads the whole package,
  which can take a minute.

See also the [France terms in Source access](../reference/source-access.md)
and the [France provider notes](https://github.com/sourcestate-io/opencorpfilings/blob/main/PROVIDER_NOTES.md#france-oam).
