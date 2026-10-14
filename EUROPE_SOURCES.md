# European corporate-reporting sources

> Updated 2026-10-09: national routes for IS, LT, LV, HR, RO, SK, EE, MT, CY, HU
> and LI were retired; CZ, CY, RO, LV and PL left the ESEF index route. Rows
> below keep the earlier findings as history.

ESMA's [Corporate reporting (Transparency Directive) directory](https://www.esma.europa.eu/publications-and-data/databases-and-registers)
points to national Officially Appointed Mechanisms (OAMs). It lists 30
countries and 31 operators (Italy has two). It is a source directory, not a
single filings API. The directory also includes Iceland, Liechtenstein and
Norway.

Two source classes are available through this library:

- **National OAM:** FR Info-Financiere, FI OAM, ES CNMV, SE Finanscentralen,
  PL KNF, NL AFM and DK Finanstilsynet. The routes preserve source report codes
  or titles and original files. Sweden's report tables expose period labels
  without source publication dates; other date fields remain provider-specific.
- **ESEF index:** country-scoped entries from the independent
  [filings.xbrl.org API](https://filings.xbrl.org/docs/api). It uses LEIs and
  report-period ordering. It does not supply native OAM publication time or form.

`Company(identifier, market=...)` selects the national OAM when this library
has one. Use `source="esef_index"` with an LEI to select the separate central
index. For countries without a national adapter, the indexed route remains
the available default where records have been verified.

The 26 `index` entries below had at least one record in a country-filtered API
query on 2026-10-07. This proves neither a national issuer denominator nor
complete ESEF coverage. A `0` means zero indexed records in that query; it
does not mean there are no national filings. The national links come from the
ESMA directory; an unimplemented link is source discovery only.

For the current 21-country index coverage and route tiers, see the
[ESEF guide](docs/markets/esef.md) and [experimental routes](docs/markets/experimental.md).
The catalogue and sample below record the dated source review; an `index`
entry is not a promise that the market remains enabled in the current release.

| Market | National OAM | National adapter | ESEF index route |
|---|---|---|---|
| AT | [OeKB](http://issuerinfo.oekb.at/startpage.html) | annual/half-year ESEF and original-file portal reviewed; [database reuse terms](https://www.oekb.at/en/legal-notice.html) require authorization for third-party service use | index |
| BE | [FSMA STORI](https://www.fsma.be/en/business-link/stori) | annual ZIP/XHTML/PDF and other PDF records reviewed; [noncommercial reproduction terms](https://www.fsma.be/fr/stori-le-mecanisme-officiel-belge-pour-le-stockage-des-informations-reglementees) require a source-access decision | index |
| BG | [FSC](https://eis.fsc.bg/services/520/) | FSC's [UIS help](https://eis.fsc.bg/help/) describes a public register available without login, separate from authenticated filing-submission services. No issuer-to-original-filing path has been verified; the ESMA-linked service page alone is not an adapter route. [FSC access guidance](https://www.fsc.bg/za-potrebitelya/dostap-do-informatsiya/) describes a request process for reuse of public-sector information, without establishing blanket document reuse rights. | 0 |
| HR | [HANFA](https://www.hanfa.hr/areas-of-supervision/capital-market/officially-appointed-mechanism-for-the-central-storage-of-regulated-information/) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| CY | [CSE public OAM](https://publicoam.cse.com.cy/) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| CZ | [CNB](https://www.cnb.cz/en/supervision-financial-market/information-published-issuers/) | official annual/half-year store scope reviewed; linked OAM application refused HTTPS from this environment on 2026-10-07, so issuer search and originals remain unverified; national adapter pending | index |
| DK | [Finanstilsynet OAM](https://www.dfsa.dk/financial-themes/capital-market/company-announcements) | **available via public issuer-filtered announcement search, direct detail IDs and individual originals** | index via `source="esef_index"` |
| EE | [Finantsinspektsioon OAM](https://oam.fi.ee/en/borsiteated) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| FI | [Nasdaq OAM](https://csf.omxgroup.com/cns-web/oam/Search.action?request_locale=fi) | **available via oam.fi for annual category 270 and interim categories 78/153; original attachments checked** | index via `source="esef_index"` |
| FR | [Info-Financiere](https://www.info-financiere.fr/pages/home/) | **available via official API for LEI or exact issuer name, source-listed issuer-name search, direct diffuser:UIN record lookup, annual 003000, half-year 004000 and quarterly-information 005000/005001/005002 source codes; original files checked** | index via `source="esef_index"` |
| DE | [Company Register](https://www.unternehmensregister.de/ureg/) | retrieval security gate | 0 |
| GR | [Euronext Athens financial data](https://athens.euronext.com/en/market-data/financial-data) | Public issuer, report-period and PDF/ESEF selectors with individual PDF links reviewed. [Athens terms](https://athens.euronext.com/en/policy/terms-of-use) restrict commercial use; no national adapter pending an authorized route. Original ESEF package access remains unverified. | index |
| HU | [MNB OAM](https://kozzetetelek.mnb.hu/en/introduction) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| IS | [Nasdaq OAM](https://csf.omxgroup.com/cns-web/oam/Search.action?request_locale=is) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| IE | [Euronext](https://direct.euronext.com/#/oamfiling) | pending | 0 |
| IT | [1Info](http://www.1info.it/PORTALEONEINFO/) and [eMarket Storage](http://www.emarketstorage.com/) | pending; eMarket content rights require consent, 1Info unresolved | index |
| LV | [Bank of Latvia CSRI](https://csri.investinfo.lv/en/) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| LI | [FMA register](https://register.fma-li.li/search) | **National route retired 2026-10-09; no adapter ships.** | 0 |
| LT | [Nasdaq OAM](https://csf.omxgroup.com/cns-web/oam/Search.action?request_locale=lt) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| LU | [LuxSE OAM](https://www.luxse.com/issuer-services-overview/oam/oam-search) | public issuer/country/ISIN search and named source originals reviewed; [LuxSE terms](https://www.luxse.com/terms-of-use) and [document-license route](https://www.luxse.com/market-data-services/market-data-products/document-services) reserve commercial use and redistribution, so national adapter pending an authorized route | index |
| MT | [Malta Stock Exchange OAM](https://www.borzamalta.com.mt/officially-appointed-mechanism) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| NL | [AFM financial reporting](https://www.afm.nl/en/sector/registers/meldingenregisters/financiele-verslaggeving) | **available via exact register issuer name, issuer-filtered XML metadata and individual original files** | index via `source="esef_index"` |
| NO | [NewsWeb](https://newsweb.oslobors.no/) | pending separate access agreement under NewsWeb rights notice | index |
| PL | [KNF](https://www.knf.gov.pl/en/MARKET/OAM) | **available for annual RR/SRR/SRR-I by exact source issuer name; first-page issuer search** | index via `source="esef_index"` |
| PT | [CMVM](https://www.cmvm.pt/PInstitucional/) | pending original-byte endpoint and source-use review; [CMVM Regulation 4/2023](https://diariodarepublica.pt/dr/detalhe/regulamento-cmvm/4-2023-220340961) specifies an annual ESEF ZIP with XHTML and permits an additional PDF, but that filing-format rule does not establish a reusable download route | index |
| RO | [ASF](https://oam.asfromania.ro/oam/loadedPDFReportsForPublic.jsp) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| SK | [NBS CERI 2](https://ceri2.nbs.sk/) / [CERI archive](https://ceri.nbs.sk/) | **National route retired 2026-10-09; no adapter ships.** | index via `source="esef_index"` |
| SI | [Ljubljana OAM](https://www.oam.si/) | public annual-notice and individual-attachment route reviewed; [LJSE access terms](https://seonet.ljse.si/default_en.aspx?doc=GENERAL_CONDITIONS_OF_ACCESS_TO_SEONET_AND_ITS_USE) restrict commercial use/reproduction, so the national adapter needs a source-access decision | index |
| ES | [CNMV](https://www.cnmv.es/portal/home.aspx) | **available for annual and interim reports with source NIF and [official issuer-name search](https://www.cnmv.es/portal/consultas/busquedaporentidad?idPerfil=2&lang=en)** | index via `source="esef_index"` |
| SE | [Finanscentralen](https://finanscentralen.fi.se/search/Search.aspx) | **available for paginated annual/interim/quarterly report tables by company registration number; paginated public issuer-name search** | index via `source="esef_index"` |

On 2026-10-07, one named LEI in each of the 26 index countries completed the
same entity to filing to original ZIP workflow. All 26 ZIPs opened (8 to 13 members)
and their SHA-256 values matched the index; together they were 332,185,412
bytes. The [captured API rows](tests/fixtures/esef_index_country_samples.json)
drive 26 offline routing and document-contract cases. This is one selected
filing per country, not a measure of national coverage. The selected source
records are reproducible below; the index API links retain each original
package URL.

| Market | Sample LEI | Index record | Original ZIP bytes | Members | Text chars | Raw facts |
|---|---|---|---:|---:|---:|---:|
| AT | `529900PD3SI453KAW989` | [25831](https://filings.xbrl.org/api/filings/25831) | 3260150 | 10 | 1017060 | 481 |
| BE | `5493000O0NZ1BCXO8K39` | [25830](https://filings.xbrl.org/api/filings/25830) | 51231666 | 9 | 1148836 | 668 |
| CY | `213800BYCUHXLRDEA130` | [6834](https://filings.xbrl.org/api/filings/6834) | 6817042 | 10 | 211076 | 357 dropped from the index route on 2026-10-08 |
| CZ | `31570010000000004460` | [441](https://filings.xbrl.org/api/filings/441) | 3022746 | 9 | 991925 | 310 dropped from the index route on 2026-10-08 |
| DK | `529900VSWLQF0O3GA946` | [26155](https://filings.xbrl.org/api/filings/26155) | 49434971 | 10 | 275880 | 215 |
| EE | `25490093MDYISEP1Y539` | [19521](https://filings.xbrl.org/api/filings/19521) | 16321814 | 9 | 392361 | 333 |
| ES | `95980020140005491250` | [18863](https://filings.xbrl.org/api/filings/18863) | 54796501 | 9 | 1676173 | 636 |
| FI | `743700WUIPC24LVMLO66` | [26154](https://filings.xbrl.org/api/filings/26154) | 7305278 | 10 | 292820 | 373 |
| FR | `969500M5EQJVDASURW53` | [26089](https://filings.xbrl.org/api/filings/26089) | 4544388 | 9 | 949393 | 423 |
| GR | `213800NW1S2T9JRVU437` | [19587](https://filings.xbrl.org/api/filings/19587) | 2263309 | 10 | 412382 | 355 |
| HR | `3157002G3ENYCZEB1A25` | [19518](https://filings.xbrl.org/api/filings/19518) | 5457222 | 9 | 116483 | 296 |
| HU | `529900VUFNK4NMC6YJ22` | [19564](https://filings.xbrl.org/api/filings/19564) | 8264143 | 8 | 390058 | 433 |
| IS | `635400TICHH43JJTNP54` | [24968](https://filings.xbrl.org/api/filings/24968) | 3197960 | 9 | 268797 | 368 |
| IT | `815600D581F8552C4F54` | [26156](https://filings.xbrl.org/api/filings/26156) | 4155707 | 10 | 311060 | 446 |
| LT | `48510000P2S3LHJPX414` | [24970](https://filings.xbrl.org/api/filings/24970) | 15980493 | 9 | 672631 | 526 |
| LU | `222100DCZBOWV5DZ8372` | [19583](https://filings.xbrl.org/api/filings/19583) | 1371367 | 9 | 346382 | 458 |
| LV | `2138002PKHUJIMVMYB13` | [15588](https://filings.xbrl.org/api/filings/15588) | 4075759 | 9 | 206402 | 325 dropped from the index route on 2026-10-08 |
| MT | `391200ZCN16YSPNKID89` | [19489](https://filings.xbrl.org/api/filings/19489) | 591111 | 8 | 194372 | 319 |
| NL | `213800HKRFK8PNUNV581` | [25930](https://filings.xbrl.org/api/filings/25930) | 6088215 | 8 | 434958 | 498 |
| NO | `549300OZ3GTYOIZ25011` | [19569](https://filings.xbrl.org/api/filings/19569) | 955639 | 9 | 101504 | 357 |
| PL | `2594007GQP5TDYY9OD45` | [16090](https://filings.xbrl.org/api/filings/16090) | 4170293 | 10 | 130351 | 476 dropped from the index route on 2026-10-08 |
| PT | `JU1U6S0DG9YLT7N8ZV32` | [19222](https://filings.xbrl.org/api/filings/19222) | 13196598 | 9 | 2327188 | 727 |
| RO | `2138008L93GYU5GN6179` | [5805](https://filings.xbrl.org/api/filings/5805) | 5766367 | 8 | 332713 | 561 dropped from the index route on 2026-10-08 |
| SE | `549300ZWVSKHHDQPES93` | [19215](https://filings.xbrl.org/api/filings/19215) | 25672692 | 10 | 354607 | 365 |
| SI | `984500DB3D0E9BCE1C41` | [25052](https://filings.xbrl.org/api/filings/25052) | 8515728 | 9 | 270565 | 564 |
| SK | `097900BGMO0000059267` | [25245](https://filings.xbrl.org/api/filings/25245) | 25728253 | 13 | 221640 | 2006 |

On 2026-10-08, the same 26 selected filings returned 14,047,617 extracted
text characters and 12,876 raw facts in total; all fact provenance linked to
the selected index country and source URL. These counts confirm retrieval and
parsing for the selected records, not text fidelity or accounting equivalence
across markets. Czech record `441` for Raiffeisenbank a.s. has only an
original 3.0 MB ZIP link, with no indexed XHTML or xBRL-JSON link. Its
embedded report XHTML yielded
991,925 text characters and 310 raw inline facts with ZIP-member source
locations. No national CNB adapter follows from this index check. FR AB SCIENCE UIN
`582412_20250514` and FI KONE notice `467217` passed original ZIP, text and
raw inline-fact checks through the national adapters. These checks are bounded
examples, not coverage measurements.
The selected Belgian index ZIP for record `25830` also passed a streamed
51,231,666-byte single-document save. The source SHA-256 was checked before
target replacement, and the document object retained no byte buffer.

To use the index for a country with a verified index route:

```python
from opencorpfilings import Company

filing = Company("959800M75M81U0Y2UX24", market="ES").filings().latest()
print(filing.index_added_at, filing.source_url, filing.documents)

known = Company("31570010000000004460", market="CZ").get_filing("441")
print(known.source_url, known.select_document(document_type="source_package"))
```

For a national source:

```python
Company("969500U43TVR8CCVBJ97", market="FR").filings(form="annual").latest()
Company("KONE Oyj", market="FI").filings(form="annual").latest()
Company("A-48010615", market="ES").filings(form="annual").latest()
Company("502017-7753", market="SE").filings(form="annual").latest()
Company("mBank Spółka Akcyjna", market="PL").filings(form="annual").latest()
Company("Íslandsbanki hf.", market="IS").filings(form="annual").latest()
Company("Apranga", market="LT").filings(form="annual").latest()
Company("1590082", market="RO").filings(form="annual").latest()
Company("2138002PKHUJIMVMYB13", market="LV").filings(form="annual").latest()
Company("VALAMAR RIVIERA d.d.", market="HR").filings(form="annual").latest()
```

The FI national adapter requires an exact OAM company name or numeric OAM
company ID. Its default search covers the last five calendar years; pass
`start=` to reach older notices. The FR national adapter accepts a LEI and
recognizes annual `003000`, half-year `004000`, and quarterly-information
`005000`/`005001`/`005002` from the [official DILA code list](https://echanges.dila.gouv.fr/OPENDATA/AMF/0%20Presentation%20et%20documentation%20flux%20AMF/Notices_relatives_au_Flux_AMF_20210120.pdf).
The named AB SCIENCE half-year record `432:599590_20251010` and MILIBOO
quarterly-information record `ACT:081396_20260917` supplied original PDFs.
The latter is a first-quarter revenue update, not a full quarterly accounts
package. Code `002003` announces availability of a half-year report and is
not mapped as the report itself. The API filters report codes and UTC source
publication dates before paging, while original codes and labels remain.
Native report periods,
correction relationships and language variants remain source-specific.
`search_companies()` reads the public issuer selectors for FI, IS, LT and HR;
the returned numeric source IDs resolve through `Company`. A live source
check found KONE `552`, Íslandsbanki `2742`, Apranga `80` and Valamar Riviera
`30577`. FI/IS/LT search accepts names typed without diacritics while keeping
source spelling in returned entities. These are source-listed candidates,
not a complete national issuer census.
France's official API groups filing records by issuer name and LEI for bounded
candidate search. `Company("AB SCIENCE", market="FR")` resolves an exact
case-insensitive source name, or callers can use the returned LEI directly.
Names associated with multiple LEIs require an explicit LEI. Live checks
resolved AB SCIENCE, L'OREAL and SOCIETE GENERALE; the latter search also
returned separate SCF and SFH entities, with the exact name ranked first.
Candidates retain the grouped source query URL and raw source row.
The ES national route needs a CNMV issuer NIF. Iberdrola's FY2024 annual
record can be reached from the official issuer-name search result `A-48010615`.
The search page offers five Iberdrola-named candidates in a live check; one
selected candidate resolved through the annual-report route. Search results
are source-listed issuer candidates, not a claim that each has a recent annual
report. The named FY2024 annual ZIP was retrieved and its members enumerated.
Its 70.0 MB XHTML yields 833
raw inline facts, matching the original source tag count. The inline parser
has a 100 MB input bound.
The [CNMV interim register](https://www.cnmv.es/portal/consultas/busqueda?id=6)
is separate from annual IFA. Its issuer page shows native report labels,
publication dates and source detail IDs. Iberdrola interim record `2026103709`
has source dates 1 January–30 June 2026 and four original links: Spanish and
English PDFs, an annex PDF and classic XBRL XML. Its original XML yielded
1,110 raw fact occurrences. The list does not expose exact period boundaries;
those are filled only after the selected detail page is inspected.
The SE national route accepts an exact company registration number. The
Swedbank FY2024 source ZIP (file ID `57991`) yielded 10 members and XHTML
text. The Swedish file ID `57992` yielded 551 raw inline facts from 55.5 MB
XHTML, matching the original source tag count. The public tables
do not expose a filing date or exact period end, so the adapter retains the
year/month label and orders by it. Only the first visible table page is read;
older results and report history require additional source paging.
The PL national route accepts an exact KNF source issuer name. Its `RR`, `SRR`
and `SRR-I` annual mapping is backed by KNF's report codes. A named mBank
FY2025 `SRR` record yielded the original ZIP, nested `.rap` and gzip-wrapped
ESEF ZIP, report text and 733 raw inline facts. The source report year is kept
as raw metadata; it is not an exact period end. The filing date is the KNF
receipt date, and its local receipt time is retained without guessing a time
zone. Discovery scans at most 20 search pages by default. Source issuer names
are used as provider-scoped identities because a stable issuer ID is not
exposed in this route.
The FI national route selects interim financial reports through the source's
issuer-scoped category menu for the requested date window. In a live example,
KONE used category 78 (half-year) and 153 (interim reports and financial
statement releases); its selected 2026 report was notice `473736`, and the
original PDF was checked. The filters retain source labels and IDs. A PDF-only
notice does not imply raw facts. Nasdaq's
[general legal terms](https://www.nasdaq.com/legal) have a broad
automated-content and third-party-use restriction, so the FI route stays
experimental pending an OAM-specific access determination.
The IS, LT and RO national routes were retired on 2026-10-09.
The NO national route is not distributed. NewsWeb's rights notice restricts
downloading and storage beyond private use without a separate agreement.
The bounded source review reached a named announcement and attachment, but
the library exposes Norway only through the independent ESEF index while
the national access route is unresolved.
The [Czech National Bank's official store description](https://www.cnb.cz/en/supervision-financial-market/information-published-issuers/)
lists annual and half-yearly reports, but its linked OAM application did not
accept a direct HTTPS connection during this review. Indexed original file
links do not establish a working issuer search. [CNB site terms](https://www.cnb.cz/en/privacy-statement-and-disclaimer/disclaimer-copyright/)
allow use of CNB Internet information with source attribution and exceptions
for authored material; issuer-file rights remain distinct. Recheck the live
application before implementing a national route.
The Italian eMarket route is likewise pending: its
[disclaimer](https://www.emarketstorage.it/it/disclaimer) restricts content use
to personal/non-commercial purposes and calls for explicit consent for
reproduction. The index route does not establish rights to eMarket material.
OeKB describes an Austrian public OAM with LEI/ISIN, language and date search,
annual and half-year ESEF, and original downloads; its site legal notice bars
unauthorized third-party database use. Belgian STORI describes PDF records and
annual ZIP/XHTML/PDF files, but permits reproduced content only for
noncommercial use with attribution. Neither national adapter is distributed
while those terms are unresolved for the intended library use.
Slovenia's public OAM exposes source-classified annual notices and individual
attachments, but LJSE's linked SEOnet access conditions restrict commercial
use/reproduction. Their applicability to an automated OAM adapter and issuer
attachments needs a source-access decision before a national route is included.
