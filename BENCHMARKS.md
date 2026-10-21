# Single-filing benchmarks

## Argentina and Peru, 2026-10-21

Version 1.2.0 adds two **experimental** routes: Argentina CNV/AIF and Peru
SMV main-market issuers. A named, source-register-confirmed sample selected
one annual report for ten issuers per market. All 20 original PDFs saved,
retained source identifiers and passed fresh-provider direct lookup. These
are bounded smoke checks, not market-wide or historical-recall qualification.
The local source pools contained 485 CNV CUITs and 202 SMV selector entries;
register membership does not guarantee a filing for every issuer/period.
Neither list is republished in the browser/cross-market directory.

| Market | Issuer | Identifier | PDF pages | First-five-page text | Raw facts / source items |
|---|---|---|---:|---|---:|
| AR | Central Puerto | `33650305499` | 121 | yes | PDF only |
| AR | YPF S.A. | `30546689979` | 140 | yes | PDF only |
| AR | Pampa Energía S.A. | `30526552659` | 144 | yes | PDF only |
| AR | Telecom Argentina S.A. | `30639453738` | 154 | no text layer in checked pages | PDF only |
| AR | Transportadora de Gas del Sur S.A. | `30657862068` | 46 | yes | PDF only |
| AR | Transportadora de Gas del Norte S.A. | `30657863056` | 111 | yes | PDF only |
| AR | Aluar Aluminio Argentino | `30522780606` | 60 | no text layer in checked pages | PDF only |
| AR | TERNIUM ARGENTINA S.A. | `30516888241` | 54 | yes | PDF only |
| AR | Loma Negra  CIASA | `30500530851` | 65 | yes | PDF only |
| AR | Banco Macro SA | `30500010084` | 185 | yes | PDF only |
| PE | ALICORP S.A.A. | `73` | 142 | yes | 1,004 / 1,004 |
| PE | UNION DE CERVECERIAS PERUANAS BACKUS Y JOHNSTON S.A.A. | `47` | 70 | yes | 1,038 / 1,038 |
| PE | FERREYCORP S.A.A. | `93` | 103 | yes | 1,004 / 1,004 |
| PE | VOLCAN COMPAÑIA MINERA S.A.A. | `46703` | 111 | yes | 1,004 / 1,004 |
| PE | COMPAÑIA DE MINAS BUENAVENTURA S.A.A. | `50` | 136 | yes | 1,004 / 1,004 |
| PE | SOUTHERN COPPER CORPORATION | `18050` | 240 | yes | PDF only |
| PE | UNACEM CORP SOCIEDAD ANONIMA ABIERTA - UNACEM CORP S.A.A. | `45` | 102 | yes | 1,004 / 1,004 |
| PE | INRETAIL PERU CORP. | `154527` | 128 | yes | 1,004 / 1,004 |
| PE | CEMENTOS PACASMAYO S.A.A. | `74470` | 76 | yes | 1,038 / 1,038 |
| PE | CREDICORP LTD. | `18049` | 182 | yes | PDF only |

Telecom Argentina and Aluar supplied scanned pages: the first five yielded no
text, while their originals and direct lookups passed. No OCR is claimed.
All eight Peruvian cases with original XBRL matched an independent count of
source elements carrying `contextRef`. Southern Copper and Credicorp supplied
PDFs without XBRL; raw-fact access correctly raises `UnsupportedCapabilityError`.
Southern Copper's generic `Informacion Financiera` upload is its original
home-market 10-K PDF, rather than a locally generated report.

Several SMV instances declare UTF-8 but contain Windows-1252 bytes, including
Spanish issuer names and certificate text. The adapter discloses its decoding
fallback on every parsed fact; saved bytes and original hashes remain intact.
Counts are compared after independently decoding those files as Windows-1252.
This establishes occurrence counts for these originals, not accounting
comparability or full-document text quality.

Notebook 07 ran all nine code cells live: source search, annual PDF saves,
page text, Alicorp's 1,004 annual raw facts, an interim case with XBRL statements
and a separate notes PDF, and direct case lookup. Test-first fixes covered SMV's
required name/ID fields, six-column interim rows, notes-versus-statements roles,
misdeclared XML encoding and generic financial-information uploads.

[Machine-readable evidence](benchmarks/country_expansion_20261021.json) contains
source keys, original hashes, sizes, page counts and fact counts; no originals,
public attachment grants or session state are bundled. The source guides
explain request bounds, dates, ordering, issuer scope, rights and formats.

## Company search pools, 2026-10-19

The 1.1.1 directory build adds 662 active CVM registrations and 336 active
CMF securities issuers: 998 entries, for 16,640 source-route entries overall
in this snapshot. Companies appearing on several filing routes remain separate.
These are regulator registers, not exhaustive lists of companies in either
country; membership does not guarantee an available annual report.

Live `find_company()` searches for Petrobras and Copec's RUT returned the
correct BR/CL routes and selected their annual filings. Local browser search
on desktop and mobile returned the correct copyable `Company(...)` lines
for Petrobras, its CNPJ, Copec and its RUT; AAPL still returned the US route.
Blocking the separate CVM JSON produced an explicit load error, with no
silently incomplete search list. The CVM subset has its own ODbL license,
attribution, transformation notes and download; only company names and
identifiers enter either directory. Both refresh with the existing weekly job.
The 829-test suite includes old-cache migration, active-status selection,
source-fetch integration and retention of previous rows during source outages.

## Brazil and Chile, 2026-10-19

Version 1.1.0 adds two **experimental** national routes. Before publication,
a bounded check selected one annual financial report for each of ten
registry-confirmed issuers per market. All 20 selected PDFs saved, retained
source provenance and passed direct filing-key lookup. The first five PDF
pages supplied readable text and a 2025 reference in every case. No source
reports, metadata databases or signed download tokens are bundled.

| Market | Issuer | Identifier | PDF pages | Raw facts / source elements |
|---|---|---|---:|---:|
| BR | VALE S.A. | `4170` | 156 | PDF only |
| BR | BANCO DO BRASIL S.A. | `1023` | 177 | PDF only |
| BR | BANCO BRADESCO S.A. | `906` | 314 | PDF only |
| BR | ITAÚ UNIBANCO HOLDING S.A. | `19348` | 133 | PDF only |
| BR | WEG SA | `5410` | 66 | PDF only |
| BR | CEMIG DISTRIBUIÇÃO S/A | `20303` | 177 | PDF only |
| BR | SUZANO S.A. | `13986` | 181 | PDF only |
| BR | AMBEV S.A. | `23264` | 147 | PDF only |
| BR | EMBRAER S.A. | `20087` | 28 | PDF only |
| BR | OI S.A. - EM RECUPERAÇÃO JUDICIAL | `11312` | 120 | PDF only |
| CL | CEMENTO POLPAICO S.A. | `91337000` | 115 | 5,665 / 5,665 |
| CL | SOCIEDAD QUIMICA Y MINERA DE CHILE S.A. | `93007000` | 204 | 13,805 / 13,805 |
| CL | ENEL GENERACION CHILE S.A. | `91081000` | 124 | 5,019 / 5,019 |
| CL | EMPRESAS COPEC S.A. | `90690000` | 176 | 10,274 / 10,274 |
| CL | CENCOSUD S.A. | `93834000` | 201 | 9,711 / 9,711 |
| CL | COLBUN S.A. | `96505760` | 131 | 5,378 / 5,378 |
| CL | AGUAS ANDINAS S.A. | `61808000` | 107 | 4,726 / 4,726 |
| CL | EMBOTELLADORA ANDINA S.A. | `91144000` | 96 | 4,984 / 4,984 |
| CL | FALABELLA S.A. | `90749000` | 141 | 18,508 / 18,508 |
| CL | LATAM AIRLINES GROUP S.A. | `89862200` | 149 | 4,526 / 4,526 |

For all ten Chilean reports, parsed classic XBRL occurrence counts equalled
an independent count of elements with `contextRef` in the original instance.
This checks occurrence completeness for those files, not accounting semantics
or cross-issuer comparability. CVM IPE does not supply structured DFP/ITR data.

Additional live checks selected Petrobras's annual PDF and material announcement,
and Copec's June 2026 interim/quarterly PDF after correctly skipping the unavailable
September report. Notebook 06 ran all cells against live sources, including
source search, streamed saves, PDF page text and Copec's 10,274 raw facts.

The identifier preflight also rejected eight unlisted identifiers and found
no annual in the default five-year window for two historical Brazilian issuers.
The confirmed sample uses source-registry identities and reuses ten successful
preflight originals; it is a named smoke check, not an unbiased market sample.
Both routes remain experimental: submission-history recall, every source form,
all balances and historical vintages have not been qualified. Full-document
text quality is outside this check. CMF signed download links may expire.

[Machine-readable evidence](benchmarks/country_expansion_20261019.json) records
filing keys, original SHA-256 hashes, file sizes, page counts and raw-fact counts.
Recheck an individual record with `Company(identifier, market=market).get_filing(key)`;
`benchmarks/provider_workflow.py BR 9512 --form annual` and
`benchmarks/provider_workflow.py CL 90690000 --form annual --facts` run the
full text workflow against the source's latest selection. Source terms and
request bounds are documented in the [Brazil](docs/markets/br.md) and
[Chile](docs/markets/cl.md) guides.


## Source search to filing handoff, 2026-10-08

The same `search_companies()` candidate-to-`Company()` filing workflow passed
offline source fixtures for eighteen market adapters. Separate provider
fixtures passed the Korean Open DART, French OAM, Spanish CNMV and Romanian
ASF paths. Romanian search results are OAM selector IDs; the selected
candidate is lazily resolved to a CUI before listing filings, while
`company.search_result` retains its original provenance. The ESEF central
index does not declare issuer search. These fixtures establish the API
handoff for named source samples, not live availability or population-wide
issuer recall.

A live Romanian OMV Petrom check took a candidate with selector ID `OAM:213`
through `Company(candidate)` to CUI `1590082` and selected its 2025 annual
record with one original link. The path took 9.2 seconds on that run. It did
not download the original; the observation is not a regulator-wide latency
or coverage measure.

Separate live search-result handoffs selected J Sainsbury through keyless UK
Companies House (one linked original), Samsung Electronics through Open DART
(receipt `20260310002820`, two linked originals), and Toyota through EDINET
(filing `S100Y8NY`, four linked originals). The latter used its known
submission day as a date bound. Each kept its provider-scoped candidate ID
through `Company(candidate)` and returned the regulator source URL. These
are three named metadata paths; none downloaded an original in this check.

On Romanian ASF, one search-to-filing request trace recorded two opening-page
GETs: the first for issuer search took 2.5 seconds and the repeated GET during
resolution took 1.8 seconds. A fresh-session exact issuer-ID POST without an
opening GET returned the same selected name and CUI. The selected-candidate
route now uses the candidate's source name to verify the returned reports.
One subsequent live run selected the same OMV Petrom annual in 2.6 seconds
after search, with zero opening GETs during resolution or filing discovery.
The runs are sequential network observations, not a controlled performance
comparison or a general source latency target.

## SEC Form 10-K numbered-page layouts, 2026-10-08

GE's 2025 10-K accession `0000040545-26-000008` has a source index that
points Item 8 to pages 36-73. Its printed footers alternate `2025 FORM 10-K
77` and `78 2025 FORM 10-K`. The updated page locator verified a 76-page
consecutive run. Pages 36, 38 and 73 matched their exact `filing.text()` line
slices; page 38 covers lines 767-826.
The terminal inline index then returned `section_references("8")` as one
source-linked `page_range` of 36-73; resolving it yielded 38 verified pages.
Item 7 returned pages 7-22 (16 pages), Item 7A returned separate page 13 and
pages 68-69, Item 10 returned page 74 with its filed proxy qualifier in the
source row, and Item 15 returned pages 75-78. The index rows lie at extracted
text lines 2079-2093. These are filed page references, not full Item spans.

Cardinal Health's fiscal 2026 10-K accession `0000721371-26-000038` puts the
report title and page number on separate adjacent footer lines in either
order. The locator verified an 89-page run. Pages 3, 49, 50, 51 and 84 matched
their exact source line slices; page 50 covers lines 1006-1023. Both filings
still lack a verified `filing.sections()` span. Cardinal Health's split-cell
index is not yet parsed by `section_references()`; a resolvable page is not a
complete Item.

## Korea and Japan named annual coverage, 2026-10-08

A metadata-only common-workflow probe since 2025-01-01 resolved Samsung
Electronics (`005930`), SK hynix (`000660`) and NAVER (`035420`) through
Open DART. All three selected a 2026 annual filing and two source-linked ZIP
documents with declared media types; observed issuer-to-document times were
12.452, 3.689 and 2.423 seconds. The first includes issuer-code acquisition.
A subsequent selected-original request for Samsung receipt `20260310002820`
returned the regulator's maintenance status `800`, surfaced as
`SourceUnavailableError`. Metadata success therefore does not establish
original-file availability for this sample.

The same probe resolved Toyota (`7203`), Sony Group (`6758`) and SoftBank Group
(`9984`) through EDINET. All three selected 2026 annual filings with four
source-linked ZIP/PDF document references and no unknown media types. The
observed times were 27.605, 25.673 and 25.317 seconds. These are exact,
date-keyed annual searches; they did not fetch original bytes. Together the
six named paths broaden metadata evidence, but they are neither a population
coverage rate nor a regulator availability guarantee.

The follow-up original-file check bounded Toyota to its known 2026-06-10
submission day. It selected the same `S100Y8NY`, downloaded 2,410,352 ZIP
bytes, enumerated 65 members and confirmed every member retained the
original EDINET source URL; the path took 6.782 seconds. A second issuer,
Sony Group, bounded to 2026-06-18, selected `S100YE2C`, downloaded a
1,099,994-byte ZIP, enumerated 33 members, extracted 348,798 text
characters and returned 2,010 raw facts. Its first fact had a source
location and source URL; the entire path took 7.149 seconds. The bounded
dates bypass the expensive exact-latest scan; these are two named originals,
not a claim about all EDINET report layouts or text fidelity.

A separate selected original for SK hynix receipt `20260317000635` also
returned Open DART maintenance status `800` after issuer and filing selection.
Together with Samsung's `20260310002820` and the earlier 2025 receipt, the
current observations span more than one issuer and receipt. They do not
establish whether the regulator outage is universal or when it will end.

## SEC terminal index page references, 2026-10-08

McDonald's 2025 10-K accession `0000063908-26-000035` has an ordered terminal
cross-reference index, but its Item labels are not full report body headings.
The new `filing.section_references(item)` read its explicit Item 1, 7, 8,
10 and 15 page pointers, including the filed `Page 37, (a)` qualification
for Item 10. Each pointer resolved to the selected original's verified
numbered-page run: pages 3, 7, 38, 37 and 70 begin at extracted text lines
99, 174, 771, 756 and 1693. Item 8's `Page 38` pointer is at text line
1812. `filing.section("8")` still raised `UnsupportedCapabilityError` because
page 38 alone does not establish complete Item 8 content. This is one named
source check, not a claim that all SEC cross-reference layouts are supported.

## Malta annual and interim title coverage, 2026-10-08

A bounded three-issuer metadata probe since 2025-01-01 initially selected Bank
of Valletta's `BOV568` annual but returned `no_filing` for HSBC Bank Malta and
Malta Properties Company. The [exchange's HSBC issuer page](https://www.borzamalta.com.mt/reports/HSB)
lists `HSBC474` as "Annual Financial Statements 2025"; its [Malta Properties
page](https://www.borzamalta.com.mt/reports/MPC) lists `MPC135` as "Approval of
Financial Statements for year ended 31 December 2025". Both have linked
originals. The adapter's conservative title mapping now recognizes those two
annual descriptions. A repeat selected all three annuals, each with three
source-linked XHTML/ZIP/PDF originals and no unknown media type.
One selected XHTML original was then fetched for each newly selected annual:
`HSBC474` returned 32,379,457 bytes and `MPC135` returned 3,579,182 bytes,
both with XML/HTML starts. The ZIP and PDF links were not fetched.
The selected XHTML text paths returned 945,909 and 169,589 characters,
respectively. Raw fact extraction returned 420 and 308 facts with source
locations. An independent byte-level opening-tag count found exactly 420 and
308 `nonFraction`/`nonNumeric` inline tags in those originals. This checks
tag coverage on two named files; it does not validate transformed values,
concept meaning or all source formats.

The same probe for interim reports initially missed HSBC's ["Interim Financial
Results" announcement](https://www.borzamalta.com.mt/officially-appointed-mechanism?search=HSBC480).
After admitting that explicit title form, both HSBC `HSBC480` and Malta
Properties `MPC142` returned interim records with one source-linked PDF each.
These checks establish five named metadata paths and two annual XHTML
text/fact paths, not issuer-wide filing recall. The original source titles
remain in `filing_type_raw`; preview announcements are still excluded.

## France secondary annual category, 2026-10-08

A four-LEI, annual-since-2025 metadata check initially found AB Science and
Sanofi but missed LVMH and TotalEnergies. The latter two records use source
primary code `300005` for a universal registration document and carry annual
code `003000` in the source's secondary category array. The provider now
queries both fields and validates the exact secondary code before setting
`filing_type_normalized="ANNUAL"`; `filing_type_raw` remains `300005`.
The same four-LEI check then returned four filing/document paths. This is a
named-source sample, not a measure of all French issuers. The [AMF describes](https://www.amf-france.org/fr/actualites-publications/actualites/formats-et-modalites-de-depot-des-rapports-financiers-annuels-et-des-documents-denregistrement)
how a universal registration document can serve as an annual financial report;
the source's secondary code identifies the particular records here.

LVMH's selected `156:622038_20260331` original has an `.xbri` suffix and a
ZIP signature. The 4,279,174-byte original exposed 11 members, 1,700,080
readable text characters and 697 raw inline facts in one live run. The
provider treats `.xbri` as a ZIP while preserving its source filename and
primary category.

## Bounded metadata coverage probe, 2026-10-08

`benchmarks/coverage_probe.py` measures issuer lookup, latest filing selection
and original-document link enumeration for at most 20 named issuers in one
market. It prints one JSON record per issuer plus a summary, distinguishing
`ok`, `no_filing`, `incomplete` and source/program errors with the failed stage.
Each selected entity and filing keeps its source URL in the record.
The probe also lists distinct declared document media types and counts links
without a media type. An `ok` row establishes metadata and linked originals;
it does not establish that text or facts can be extracted from those originals.
Cyprus reports `document_listing_requires_originals` after filing selection:
its OAM sends all base64 attachment bytes with the document list, so a
metadata-only probe cannot count them without fetching the originals.
It does not download document bytes or test text/facts. Run the separate
one-filing workflow below for selected original-content checks.

```bash
python benchmarks/coverage_probe.py US AAPL MSFT NVDA GE XOM --start 2025-01-01
python benchmarks/coverage_probe.py UK 00185647 00000006 --start 2024-01-01
```

In a live, uncached 2026-10-08 run, the US sample returned four `ok` paths,
each with 93–182 source document entries and source URLs, and one `no_filing`:
the current SEC ticker list mapped XOM to CIK `0002115436`, which had no
annual filing in the requested window. The five issuer durations were
0.58–0.95 seconds each. The UK sample returned one `ok` Companies House
path (`00185647`, one original-document link, 2.09 seconds) and one
`no_filing` path (`00000006`, 4.96 seconds). These are intentionally selected
issuers, not a statistical coverage estimate; source network time and
unverified population denominators preclude a reliability percentage.

A separate four-issuer media check selected LVMH (FR), Nokia (FI), Inditex
(ES) and J Sainsbury (UK). All four metadata paths were `ok`. Their nine
document links declared ZIP and/or PDF media types, with zero unknown media
types. This confirms only the selected links' metadata; the probe did not
download those originals or verify their actual byte signatures.

Six more selected national routes returned `ok` metadata paths: OMV Petrom
(RO), DelfinGroup (LV), ASML (NL), Carlsberg (DK), Pro Partners Holding (SK)
and VanEck ETP (LI). All sixteen linked documents declared ZIP, PDF or XLSX;
none had an unknown media type. Liechtenstein's source does not supply a filing
date, which remains `null` despite the successful linked-document check.

Another Danish sample found Novo Nordisk, Carlsberg and Vestas by source name;
all three selected current annual filings with three to five source-linked
documents. Novo's 24,152,301-byte original ZIP yielded 553,339 text characters
and 515 raw facts, all with locations linking to that original. Vestas's
36,887,173-byte ZIP yielded 738,461 text characters and 594 raw facts. The
Novo and Vestas complete runs took 21.71 and 33.94 seconds, of which original
downloads took 16.11 and 27.00 seconds. These named checks do not measure
population coverage or establish a transfer-speed target.

The Danish issuer selector lists both `DONG Energy A/S` and `Ørsted A/S` under
business ID `DK-36213728`. The previous exact-name equality check rejected
Ørsted's current annual result. The ID now resolves to the name on the newest
source announcement, while each filing retains its own issuer label and
details are checked against the same business ID and its official aliases.
An ASCII `Maersk` search now finds the source's `MÆRSK` spelling; `Orsted`
finds `Ørsted`. Live metadata checks selected Maersk announcement `300003436`
with three originals and Ørsted announcement `300003541` with ten. This is
source-listed alias handling, not a global entity-resolution claim.

Separately, one Romanian run took 11.104 seconds. A repeat separated 6.081 seconds of
issuer resolution from 4.674 seconds of filing discovery; document enumeration
was negligible. A fresh portal session then showed that exact CUI filter POSTs
work without an opening GET for both annual and all-report searches. Removing
that GET from the exact-CUI path retained the same selected OMV Petrom record,
document type and source URL in a 7.780-second live run. These are sequential
network observations, not a controlled latency guarantee. An independent
two-page source check found the POST's first-page order and page 2 matched the
explicit descending sort; the adapter still requests source sorting for stable
pagination. Issuer-selector ID lookup still opens the page to verify the
selected source identity.

A live Cyprus `1637` run selected OAM record `223454` in 1.728 seconds and
returned `document_listing_requires_originals` without enumerating its
attachments. The probe exited unsuccessfully by design because the metadata
only workflow cannot verify linked documents for this source.

Eight further named annual routes returned linked-document metadata: Swedbank
(SE), mBank (PL), Islandsbanki (IS), Apranga (LT), Valamar Riviera (HR),
LHV Group (EE), Bank of Valletta (MT) and 4iG (HU). Seven declared their
document media types at listing. Sweden's selected `fid=61644` supplied a
source file link but no source filename or MIME type, so its one listed
document correctly reported `unknown`. The package detects its ZIP format
from the original bytes: a separate live one-filing run downloaded 7,725,663
bytes, exposed ten archive members and returned 1,336,369 text characters.
The Swedish listing took 23.163 seconds; a repeat attributed 22.960 seconds
to the exact issuer form and 0.003 seconds to filing selection from the
already retrieved issuer page. These selected observations do not measure
countrywide coverage or establish a latency target.
One request-level trace of the same exact lookup measured 20.419 seconds for
the 15,274-byte public search-page GET and 0.812 seconds for the 216,058-byte
form POST. The GET supplies the ASP.NET form state needed for the exact search;
this trace does not justify skipping it. Adapter review also found that the
Swedish download paths checked source URL shape but did not compare the URL's
file ID with the selected document ID. Buffered and streamed paths now reject
a mismatch before requesting bytes, and source URLs with repeated `fid`
parameters fail validation.

A separate three-issuer Danish annual metadata check selected Novo Nordisk
`DK-24256790`, Vestas `DK-10403782` and Pandora `DK-28505116` since
2025-01-01. All three returned a current annual filing and three or four
original links. Vestas's source listed one `.htm` original that the adapter
initially labelled with unknown media type; the format map now recognizes it
as HTML. The selected Vestas announcement `300003430` then returned its
12,424-byte original `.htm`, 4,534 characters of readable text, and matching
document/provenance URLs. This is a named-issuer check, not countrywide
coverage or a claim about every linked file.

A five-issuer Netherlands AFM annual metadata check since 2025-01-01 returned
linked ZIP originals for ASML, ING Groep, Koninklijke Philips and Heineken.
Prosus N.V. resolved to the source issuer and returned half-yearly notices,
but no annual record in that date window; its newest annual record in the
AFM response was filed 2024-06-24 for FY2024. The separate ESEF index route
for Prosus LEI `635400Z5LQ5F9OLVT688` also returned no period after
2024-03-31 in this check. [Prosus publishes FY2025 and FY2026 annual
reports](https://www.prosus.com/investors/financial-information/annual-reports)
on its issuer site. These observations establish a gap in the two queried
routes for this issuer, not why the records are absent or countrywide coverage.

The same provenance audit found that Slovakia's two CERI generations accepted
an original URL for another valid source file under a selected document ID.
Buffered and streamed paths now compare the URL with the generation-prefixed
document ID before contacting the source. Offline cases cover both CERI 2
numeric IDs and historical filename IDs. A post-change live call selected
Pro Partners Holding's `ceri2:71`, downloaded its 2,467,779-byte `.xbri`
original, exposed ten archive members and returned 393,548 text characters.

The XOM result is a developer-experience issue to investigate: current ticker
resolution can point to a successor entity without the older issuer's annual
history. The probe preserves that source identity instead of silently joining
legal entities. A future solution needs an explicit, source-backed predecessor
relationship and user-visible selection.

A separate UK sample used the nine exact Companies House numbers in the
[dated UKSEF pilot selection](../../docs/plans/2026-10-02-uk-xbrl-financial-statement-pilots.md).
With annual filings since 2025-01-01, keyless public-page access returned nine
`ok` metadata paths with one original-document link each. The nine sequential
issuer checks took 14.54 seconds in total (1.24–2.32 seconds individually).
This selected cohort was already known to have source reports and therefore
does not measure UK issuer-population coverage, original-byte availability or
text/fact correctness. The one-filing checks below cover selected originals.

On 2026-10-08, a second five-issuer keyless UK sample used source-confirmed
company numbers for Tesco, Barclays, Unilever, Rolls-Royce Holdings and BP.
All five resolved their latest annual accounts with one original PDF link and
filing/document source URLs. Sequential metadata paths took 8.28 seconds
(1.18–2.43 seconds each). No original bytes were fetched. During issuer
selection, exact-name search for Rolls-Royce found its company on the first
page but previously raised at the 20-page bound because fewer than three
unique matches appeared. The bounded search now returns candidates it found;
this does not establish completeness of Companies House search results.

Four source-listed Finland OAM issuer IDs (Nokia `690`, UPM-Kymmene `1099`,
Wärtsilä `1147`, KONE `552`) each returned an annual filing and two to four
source document links since 2025-01-01. The four sequential metadata paths
took 7.00 seconds. No original bytes were fetched in this probe.

Spain's CNMV name-search form has two valid results: a multi-issuer NIF
selector, and a direct entity detail page for a unique match. Before the
detail-page parser was added, `search_companies("Inditex", market="ES")`
raised `ParseError`; it now returns NIF `A-15075062` with the direct CNMV
entity URL. A subsequent four-NIF annual metadata sample (Santander,
Inditex, Telefónica and Iberdrola) returned four filing/document paths since
2025-01-01 in 11.14 seconds. These named issuer checks do not measure Spanish
issuer coverage or original-content success.

A subsequent 20-ticker US metadata pass, using annual filings since
2025-01-01, returned 19 `ok` and XOM `no_filing` in 16.45 seconds total.
Individual issuer paths took 0.56–1.06 seconds. This measures only named
metadata paths; no original bytes, text, facts or population denominator were
checked. Direct CIK `0000034088` selected the old Exxon Mobil Corporation's
2026-02-18 annual filing `0000034088-26-000045`, with 164 document entries,
in a separate 1.01-second run. The [successor registrant's July 2026 8-K](https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm)
identifies the redomiciliation and the old corporation as predecessor. This
proves that particular historical relationship, not a general discovery rule
for arbitrary ticker changes. Users can pass the historical CIK explicitly.

## SEC 8-K Item navigation, 2026-10-08

[EdgarTools exposes 8-K Items by decimal code](https://github.com/dgunning/edgartools/blob/main/docs/eightk-filings.md).
The standalone SEC path now uses the same `filing.section("2.02")` selection
shape as its 10-K/10-Q Item navigation. It accepts only headings whose
caption matches the first words of the [SEC Form 8-K](https://www.sec.gov/files/form8-k.pdf),
keeps the original title, and stops the last source span at a signature line.
The table-of-contents route requires its codes and captions to match later
body headings before selecting them.

One latest unamended original each from AAPL, MSFT, NVDA, JPM, TSLA, AMZN,
META, BAC, JNJ, WMT, XOM and KO returned source-linked Item spans. Amazon's
`0001104659-26-107526` has Item 8.01/9.01 both in a page-number contents
list and in the body; returned body lines are 131–155 and 156–181.
ExxonMobil's `0001193125-26-402986` omits punctuation after the Item code;
its split captions resolved at body lines 57–62 and 63–93.

A subsequent twenty-ticker held-out check selected one latest unamended 8-K
each from GOOGL, UNH, PG, MA, HD, COST, IBM, ORCL, CRM, CAT, BA, GE, GS,
C, V, DIS, NFLX, AMD, INTC and PFE. All twenty returned one to three
source-linked Items. This is a named-issuer convenience sample, not a
population coverage estimate or a claim about older forms.

An isolated EdgarTools 5.61.1 exact-accession check returned the same Item
codes for Apple's `0000320193-26-000018`. Its Item 2.02 and this library's
Item 2.02 had identical ordered word tokens (110 each). Item 9.01 had 40
tokens in each, with the first 10 and last 27 matching; three internal
table-text tokens differed in order. On Amazon's `0001104659-26-107526`,
EdgarTools 5.61.1 returned page-number contents text for Item 8.01 and
contents/exhibit-index text for Item 9.01. This library returned the later
body spans after verifying that their code and caption sequence matched the
contents. These two comparisons do not establish general span parity.

## Common-workflow stage timing, 2026-10-08

`benchmarks/provider_workflow.py` times one public issuer -> latest filing ->
document enumeration -> one original download -> readable text workflow. It
prints stage durations, source IDs, byte/text counts and a provenance check.
It labels a successful but blank extraction `text_status="empty"`; for PDFs
it also reports total pages and pages with an extracted text layer;
`--facts` adds raw-fact timing when needed. It does not enable disk caching or
download multiple filings. Run one source per process, for example:

```bash
python benchmarks/provider_workflow.py UK 00185647 --start 2026-01-01
python benchmarks/provider_workflow.py FR 969500U43TVR8CCVBJ97 --start 2025-05-14 --end 2025-05-14
```

On a library/source error it prints one JSON record with `status="error"`,
`failed_stage`, the public error type, elapsed seconds and any IDs already
resolved, then exits with status 1. It does not print raw provider messages,
which may contain request details. Unexpected programming errors still raise.
On 2026-10-08, a new Samsung annual query resolved entity `00126380` and
filing `20260814003699`, then reported `SourceUnavailableError` at `download`
after 13.445 seconds when Open DART returned maintenance status `800`.
The source title on that receipt is `Semi-annual Report (2026.06)`: this
historical result exposed an English-title category bug and is not evidence
of correct annual selection. After fixing the category order, a live Samsung
annual query selected `20260310002820` (`Annual Report (2025.12)`, code
`11011`), while an interim query selected `20260814003699` (code `11012`).
The corrected annual filing's original-document request still returned Open
DART maintenance status `800` in a subsequent live check. The library raised
`SourceUnavailableError` at the save stage and left no destination file; text
and facts from that receipt could not be verified in this run.
A separate keyless UK run completed with the same successful JSON shape:
4,336,135 original bytes, 930,092 text characters and 5.438 total seconds.
These are separate live observations, not a throughput comparison.

Two held-out keyless UK annual originals illustrate why an original-document
link is not evidence of readable text. Tesco's 14,316,485-byte PDF had 236
pages and Unilever's 27,976,052-byte PDF had 283 pages. Both downloaded with
provenance, but `pypdf` extracted text on zero pages in each. Tesco's first page
contains an image; the PDF producer identifies TIFF-to-PDF conversion. The
benchmark now reports `empty` and zero text-bearing pages rather than
`available`. These named observations do not establish a UK PDF population
rate or imply OCR support.

Named live observations below use keyless UK/FR, an identifying SEC identity,
and an EDINET API key. JP is bounded to the known submission date; it is not
the costly unbounded `latest()` discovery case. Durations are seconds, from
separate sequential processes, and include network effects.

| Market | Entity | Latest | Documents | Download | Text | Total |
|---|---:|---:|---:|---:|---:|---:|
| US AAPL | 0.741 | <0.001 | 0.184 | 0.317 | 0.118 | 1.360 |
| UK J Sainsbury | 0.968 | 1.872 | <0.001 | 1.366 | 1.930 | 6.136 |
| JP Toyota, one day | 2.033 | 1.088 | <0.001 | 4.596 | 0.590 | 8.308 |
| FR AB SCIENCE | 0.951 | 0.192 | <0.001 | 1.105 | 0.502 | 2.751 |

The UK workflow stages summed to about 5.8 and 6.1 seconds in two fresh runs
here, compared with
17.26 seconds in the earlier cross-market smoke. That difference does not
support treating UK parsing as a 17-second library bottleneck. On Pfizer's
5.2 MB SEC 10-K, the source-line offset map took 0.623 seconds for 19 Item
headings and 0.582 seconds with no headings. Most of that cost is the required
HTML parse; changing its line-count calculation would save little in this
sample. The full Pfizer section call took 3.00 seconds after filing lookup.
Same-date `--facts` repeats returned 1,131 raw occurrences for US AAPL,
762 for UK J Sainsbury, 2,182 for JP Toyota and 356 for FR AB SCIENCE;
all four still returned nonempty original bytes and text. A third Samsung
Open DART original request again returned source maintenance status `800`;
the public error now has type `SourceUnavailableError`.

## Cross-market live smoke, 2026-10-08

The package's named one-filing examples were run sequentially through the same
`Company` -> latest annual filing -> primary original bytes -> readable text
workflow. Every successful record retained filing and document source URLs.
Elapsed time includes source calls, original transfer and text extraction;
these individual observations are not latency comparisons or service targets.

| Market | Filing ID | Original bytes | Text characters | Seconds |
|---|---|---:|---:|---:|
| US | `0000320193-25-000079` | 1,520,317 | 208,385 | 4.38 |
| UK | `MzUzNDA4NzU2M2FkaXF6a2N4` | 4,336,135 | 930,092 | 17.26 |
| KR | Open DART status `800` | - | - | 1.98 |
| JP | `S100Y8NY` | 2,410,352 | 260,742 | 7.61 |
| FI | `467217` | 10,501,689 | 564,598 | 15.80 |
| FR | `432:582412_20250514` | 4,022,063 | 833,870 | 3.18 |
| ES | `2026031462` | 10,103,299 | 1,349,904 | 20.45 |
| SE | `502017-7753:annual:2025` | 7,725,663 | 1,336,369 | 32.36 |
| PL | `87CC574FDDF43ADAC1258DAA00614B3B` | 11,253,257 | 667,315 | 11.45 |
| IS | `467593` | 13,080,200 | 492,447 | 20.24 |
| LT | `471439` | 6,823,545 | 482,102 | 4.84 |
| RO | ``A`2025`SNP`RFA_SNP_26_03_20260319_181038.zip`` | 268,060 | 501,056 | 11.96 |
| LV | `24724` | 1,171,493 | 179,764 | 4.60 |
| HR | `2026_02_26-1207941` | 17,207,649 | 961,611 | 30.23 |
| NL | `A2510-03564` | 20,292,909 | 1,358,659 | 8.50 |
| DK | `300003388` | 14,496,220 | 774,476 | 7.12 |
| SK | `ceri2:71` | 2,467,779 | 393,548 | 9.51 |
| EE | `18276` | 2,668,104 | 664,240 | 3.65 |
| MT | `BOV568` | 20,326,753 | 783,701 | 6.98 |
| CY | `223454` | 210,159 | 11,268 | 2.54 |
| HU | `K193725/2024` | 14,856,084 | 517,778 | 13.62 |

Twenty of 21 named paths returned an original and nonempty text. Open DART
returned its documented maintenance status `800` when the Korean original was
requested; the lookup and listing proceeded before that response. The run did
not measure raw facts, alternate formats, older history, issuer-population
coverage, or source-use rights. Korea's successful original path was checked
in an earlier named live run, and its current streaming path has offline
source-response tests; current live availability remains unverified.

A repeat of the official English Open DART original-document endpoint for
Samsung receipt `20250618000208` on 2026-10-08 again returned XML status `800`
(`The service is suspended for maintenance.`). This is a source availability
failure, so it does not establish that original downloads currently work live.
The [official Korean original-file endpoint](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003)
returned the same XML status `800` for that receipt and API key in a direct
follow-up check. Substituting the Korean endpoint for the English route would
not restore original downloads in this observed condition.

A later bounded metadata-only check used the public `Company` workflow for
AAPL (US), J Sainsbury (UK), Samsung (KR), Toyota (JP), AB Science (FR) and
KONE (FI). All six resolved an issuer, selected an annual filing, enumerated
one or more document references and retained filing/document source URLs.
The respective elapsed times were 1.13, 2.06, 3.69, 31.16, 1.19 and 3.52
seconds. The Toyota duration is consistent with the date-keyed EDINET scan
below. This check did not download the referenced originals; the Korean
maintenance result above remains the current original-file observation.

## EDINET daily discovery, 2026-10-08

The official [EDINET API specification](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140206.pdf)
lists filings for one date per request. With a cold
transport and the same Toyota `7203` annual query bounded to 2026-04-01 through
2026-10-08, serial discovery returned document `S100Y8NY` after 121 daily
requests in 39.13 seconds. Four-day ordered prefetch returned the same record
after 124 requests in 32.27 seconds. A rolling four-request window returned
it after 125 requests in 30.64 seconds. The rolling implementation now
submits the next date only after the current date has been consumed, so a
`latest()` result can leave at most three already-started older dates. The
transport retains one 0.2-second dispatch gate across the requests. These are sequential live
observations, not a controlled latency comparison or guarantee; the last
submission-order adjustment was not separately timed.

The date API cannot filter by issuer or form. An exact latest annual filing
therefore requires checking each newer source day; date hints could silently
miss a filing. A caller with a known date range can use `start=` and `end=` to
reduce the scan.

A later full Toyota `Company("7203", market="JP").filings(form="annual").latest()`
plus raw-fact read returned the same `S100Y8NY` and 2,182 facts in about 38
seconds. The official issuer registry includes Toyota's fiscal close, but
that date is not a safe substitute for checking newer daily lists: a later
annual amendment or delayed report would otherwise be missed. The official
API specification also says historical daily files are refreshed each day.
The cold exact-latest path therefore remains source-call bound; users with a
known interval can narrow it explicitly.
The official January 2026 API specification still defines a date-keyed
document-list request, with no issuer or form parameter. A live type-2 daily
response on 2026-10-08 was 282,405 bytes and returned both
`Cache-Control: no-cache` and `Pragma: no-cache`, without an ETag or
Last-Modified validator. The transport therefore does not reuse that
authenticated response. Caching it across calls without revalidation could
make `latest()` stale; the existing exact workflow keeps its daily scan.

The benchmark uses the same developer task in both libraries: resolve an issuer
by ticker, select its latest annual or quarterly SEC filing, and read the
primary text.
It follows the [EdgarTools filing workflow](https://github.com/dgunning/edgartools/blob/main/edgar/docs/Filing.md).
It does not measure batch acquisition or normalized financial statements.

Run each implementation in a fresh process with an identifying SEC identity:

```bash
python benchmarks/sec_annual.py opencorpfilings
python benchmarks/sec_annual.py edgartools
python benchmarks/sec_annual.py opencorpfilings --ticker MSFT --form quarterly
python benchmarks/sec_annual.py edgartools --ticker MSFT --form quarterly
```

Set `OPENCORPFILINGS_SEC_USER_AGENT`, `EDGAR_IDENTITY`, or both `SEC_ACC_NAME`
and `SEC_ACC_EMAIL`. EdgarTools is an optional benchmark dependency. Use
`--edgartools-path <isolated-install-dir>` when comparing an isolated version.
`--text-output <path>` saves the extracted text for content comparison.

## Named observation, 2026-10-08

Apple accession `0000320193-25-000079`, OpenCorpFilings `0.2.0.dev0`
and EdgarTools `5.61.1`, both run with the same identity and a fresh Python
process:

| Library | Lookup | Select | Text | Total | Text characters | Word tokens |
|---|---:|---:|---:|---:|---:|---:|
| OpenCorpFilings | 0.664 s | <0.001 s | 0.243 s | 0.908 s | 208,385 | 27,453 |
| EdgarTools | 0.025 s | 0.263 s | 0.663 s | 0.952 s | 268,224 | 27,406 |

The source text has different whitespace and table layout. Using the simple
`[A-Za-z][A-Za-z0-9]+` tokenization in the benchmark, an ordered-token
comparison gave 0.9967 similarity. That comparison does not prove either
extractor is complete; selected source pages and tables still need source
inspection when fidelity matters. These are two sequential live runs with
different cache states and network conditions, so the timings are observations,
not a relative performance claim or service-level target.

A pinned EdgarTools `5.56.0` installation selected this accession
but its `filing.text()` failed because its homepage object had zero documents
and an archive URL without the accession directory. The isolated `5.61.1`
release used the complete archive URL, found ten homepage documents and
returned text. Compare against a current release before interpreting a
benchmark failure as a library difference.

## Additional named observations, 2026-10-08

The same script selected the same accession in each pair below. Word tokens
use `[A-Za-z][A-Za-z0-9]+`; similarity compares their order with Python's
`SequenceMatcher(autojunk=False)`. These are individual sequential live runs,
not controlled latency comparisons.

| Issuer | Form | Accession | OpenCorpFilings words | EdgarTools words | Ordered-token similarity | OpenCorpFilings total | EdgarTools total |
|---|---|---|---:|---:|---:|---:|---:|
| MSFT | annual | `0001193125-26-323660` | 43,503 | 43,503 | 0.997862 | 1.484 s | 4.402 s |
| NVDA | annual | `0001045810-26-000021` | 47,607 | 47,371 | 0.996715 | 0.946 s | 1.471 s |
| AAPL | quarterly | `0000320193-26-000020` | 10,657 | 10,657 | 0.995027 | 0.824 s | 1.041 s |
| MSFT | quarterly | `0001193125-26-191507` | 27,352 | 27,352 | 0.996088 | 1.316 s | 3.482 s |

The largest ordered-token differences observed in these text files were near
table headers and repeated column labels. Nvidia's word counts differ by 236;
the similarity score alone cannot establish which text rendering is more
faithful to the source. Character counts differ substantially because the
libraries format whitespace and tables differently. Inspect the original
filing when exact table reading matters.

### Nvidia source inspection

The original SEC HTML for Nvidia accession `0001045810-26-000021` contains one
table-of-contents heading and 80 repeated fragment links labeled “Table of
Contents.” The earlier OpenCorpFilings text included all 81 labels; EdgarTools
included two. The readable-text extractor now omits those fragment backlinks
while preserving the heading, other fragment-link labels and the original
HTML. In a new live public-API read, OpenCorpFilings returned 47,367 English word
tokens and one heading label. Against the saved EdgarTools 5.61.1 text, ordered
similarity rose from 0.996715 to 0.999134, and the word-count difference fell
from 236 to four tokens. The saved comparison is from the same accession;
it does not settle every remaining table-layout difference.

### Section-navigation boundary

[EdgarTools exposes filing sections](https://github.com/dgunning/edgartools/blob/main/edgar/docs/Filing.md).
A live inspection of Apple's original 2025 10-K HTML (accession
`0000320193-25-000079`, 1,520,317 bytes) found zero `<h1>`–`<h6>` tags.
A generic HTML-heading splitter would therefore miss this benchmark filing's
sections. Its contents links point to empty anchors, while Microsoft's 2026
10-K has no matching Item fragment links. OpenCorpFilings now uses the original
Item contents titles to verify each body heading in extracted text, then
returns source-linked `FilingSection` spans. Saved Apple 2025, Microsoft 2026,
Nvidia 2026 and Alphabet 2026 originals each yielded 23 ordered Items (1
through 16, including lettered Items). The matcher tolerates source punctuation,
spacing and apostrophe differences while requiring one matching body heading
per contents entry and a contents list reaching Item 15 or 16. This deliberately
strict path applies only to qualifying SEC HTML 10-Ks; it raises an explicit
unsupported-capability error when a boundary is missing or ambiguous. It does
not establish coverage for all SEC 10-K markup or other form types.

In a named Apple 2025 comparison against isolated EdgarTools 5.61.1,
`filing.obj().sections` and OpenCorpFilings `filing.sections()` both returned 23
semantic Item spans. For all 23, `[A-Za-z][A-Za-z0-9]+` word-token counts and
the first and last 12 word tokens matched. This checks section boundaries in
one original, not byte-identical rendering or broader 10-K coverage.
EdgarTools' lower-level `filing.sections()` returns search passages rather than
the `TenK.sections` Item map used in this comparison.

### Quarterly Part/Item navigation

Saved Apple, Microsoft and Nvidia 2026 original 10-Q HTML files have separate
Part I and Part II contents. The source-verified matcher returned 11, 9 and 9
ordered Item spans respectively, including repeated Item numbers with their
Part identity. The Part II heading is excluded from Part I Item 4, and the
signature is excluded from Part II Item 6. For Apple's accession
`0000320193-26-000020`, EdgarTools 5.61.1 `TenQ.sections` returned the same
11 Part/Item keys. Ten sections matched word-token count and their first and
last 12 word tokens; Item 6 matched word-token count and end tokens, while its
table layout made the first 12 differ. These are named checks, not population
coverage or a claim of byte-identical text rendering.

JPMorgan Chase accession `0001628280-26-054343` places Part I Item 2 before
Item 1 in the body and does not repeat either Item heading there. Its contents
links instead point to unique empty body anchors. OpenCorpFilings verifies each
link within its Item row, the unique target and its position in extracted
text, then returns 11 sections in contents order. Against EdgarTools 5.61.1
`TenQ.sections`, ten of the 11 spans matched word-token counts and first/last
12-token samples; Item 1 differed by one word token while its boundary samples
matched. The parser rejects missing, duplicated or non-block anchor targets.
This is one named layout, not a population-wide coverage estimate.

### Additional source layouts

A targeted live check of six SEC tickers and both annual and quarterly forms
found that Walmart's 2026 10-K places the Item 1C and Item 5 titles on the
line after their Item numbers. The original contents list supplies the exact
titles, so the section matcher now accepts that adjacent-line form only when
the Item and title match one contents entry. Walmart accession
`0000104169-26-000055` and Amazon accession `0001018724-26-000004`
returned 23 annual Item spans. Walmart's 2026 10-Q accession
`0000104169-26-000154` puts Item number and title on one contents line;
the Part-aware matcher returned nine spans after accepting that source form.
On the same Walmart 10-K accession, all 23 Item keys and first/last 12
word tokens matched EdgarTools 5.61.1. Twenty-two Item word counts matched;
Item 7 differed by one. Item 16 initially included signature pages, which
the source's exact `SIGNATURES` marker now excludes; its four word tokens
and both boundary samples match EdgarTools. On the same Walmart 10-Q,
all nine Part/Item keys matched; six word counts and opening samples matched,
and all nine ending samples matched. The other three openings differ in table
layout. EdgarTools also has one non-Item cover section in each report.

The same sample exposed deliberate limits: Berkshire Hathaway's 2026 10-K
incorporates Items 10-14 by reference, so no matching body headings exist.
Tesla's latest annual result was a 10-K/A, for which section navigation is
not declared. The SEC's current exchange map
lists `XOM` under ExxonMobil Holdings Corp (CIK `0002115436`), while its older
`ticker.txt` lists CIK `0000034088`; the resolved current profile has no annual
filing yet. Those cases were not counted as successful section extraction.

### Numeric contents table

Johnson & Johnson accession `0000200406-26-000016` has 23 Item/title/page
rows in one source table. Its visible text separates bare Item codes from
titles, while some table-cell markup splits words internally. The fallback
requires one ordered table reaching Item 15 or 16 and one body heading whose
letters and digits match each source title. It returns 23 verified Item spans.
On the same accession, 22 of 23 Item spans matched EdgarTools 5.61.1 in word
count and first/last 12 word tokens. EdgarTools' Item 15 includes the separate
Item 16 heading and its 28 word tokens; OpenCorpFilings ends Item 15 at that
explicit body heading and returns Item 16 separately. Both implementations
return 28 word tokens for Item 16. This is one source layout, not population
coverage.

For this saved 3,701,696-byte original, three local parses with
BeautifulSoup's `html.parser` found 238 tables either way. Restricting the
numeric-contents fallback to table tags reduced median traced peak memory
from 42.86 MiB to 29.02 MiB; median parse time was 3.335 s versus 3.345 s.
This measures the fallback parser alone, not end-to-end filing extraction.

### Minor contents/body title differences

An eight-ticker live sample of latest unamended 10-Ks and 10-Qs found three
ordinary 10-Ks unsupported solely because their contents and body titles
differed by a singular/plural ending or an added conjunction: UnitedHealth
`0000731766-26-000062`, AMD `0000002488-26-000018` and Boeing
`0001628280-26-004357`. The constrained same-Item matcher now returns 23
source-verified spans for each. On the same UnitedHealth and Boeing accessions,
EdgarTools 5.61.1 also returned 23 Item keys. Text token counts and boundary
samples differed in several sections, especially near tables and short
headings; this does not establish exact text-span parity. EdgarTools' latest
AMD 10-K result selected a different accession in this comparison, so its
two Item keys were not used as a same-filing quality comparison. Berkshire
Hathaway's annual filing still fails closed because incorporated Items lack
body headings. In this sample the other seven 10-Qs returned 9-11 Part/Item
spans. These are named live observations,
not a population coverage estimate.

### Repeated quarterly page headings

Berkshire Hathaway's 10-Q accession `0001193125-26-341032` repeats its Part I
Item 2 heading 18 times in extracted text. The source contents row links to
one matching paragraph ID at the actual Item start. The adapter verifies the
same-row link, unique target ID, paragraph type, source byte position and
matching Item/title at the derived text line. It now returns all 11 Part/Item
spans in 1.94 s for the named live section call. EdgarTools 5.61.1 returned
the same 11 keys on the same accession. Items 2 and 3 had equal word-token
counts and matching first/last 12 tokens in both libraries. This validates
the selected headings, not every section or filing layout.

### Fresh twelve-issuer annual section sample

A sequential live check of the latest unamended 10-K for KO, PEP, DIS, V, MA,
COST, HD, PG, CAT, IBM, ORCL and CRM returned verified sections for eight
filings before a parser change. Mastercard, Costco, Procter & Gamble and IBM
raised `UnsupportedCapabilityError`; all twelve resolved a source accession.
This is a named convenience sample, not a population coverage estimate.

Costco accession `0000909832-26-000093` has a complete 23-Item contents list,
but its body headings use an em dash (`Item 1—Business`). Items 7 and 7A also
append parenthetical units to the contents title. The constrained matcher now
uses the same Item number and exact/minor contents title before that trailing
parenthetical note. A new live call returned all 23 ordered Items in 1.14 s,
from Item 1 through Item 16, with the signature outside the final span. Nine
of the twelve named 10-Ks now return sections. Mastercard's repeated body
headings, Procter & Gamble's mixed Part/Item contents rows and IBM's same-line
contents remain to be resolved against their original source markup.

### Earlier segmenter comparison

An earlier, broader SEC 10-K segmenter was compared on its source-only path, which found
22, 21, 23 and 22 nonempty Item sections on
the same live Costco, Mastercard, Procter & Gamble and IBM originals,
respectively. The differences include reserved or absent Items, so these
counts are not a required 23-Item shape. OpenCorpFilings currently returns
23 for Costco and raises `UnsupportedCapabilityError` for the other three.

That segmenter's own evaluation also relies on a facts store, XBRL-based
validation and exhibit handling, so it does not measure the source-only path
or OpenCorpFilings. Before extending the standalone SEC matcher again, copy or rebuild useful
source-only mechanics inside this package and compare them against the same
accession fixtures and a
held-out sample. Keep the package independent of that project's storage,
validation dataset and accounting/research layers.

### Standalone source-body follow-up

The source-body heading detector is now copied into the standalone package as
`sec_body.py`; the package imports no code from its origin. Its fallback runs only when
the existing 10-K contents matcher fails, requires at least 15 ordered Items
from Item 1 through Item 15 or 16, and checks each candidate against the
original extracted-text line. It preserves the document's source URL,
provenance and line spans. It does not resolve Item pointers into exhibits or
inherit the origin's facts-store and XBRL validation.

A fresh sequential live rerun of the same twelve latest unamended 10-Ks
returned sections for all twelve. The three formerly failing sources returned
21 Items for Mastercard `0001141391-26-000013` (2.86 s for the section call),
23 for Procter & Gamble `0000080424-26-000103` (1.58 s), and 22 for IBM
`0000051143-26-000010` (0.67 s). Every section text matched its reported
slice of `filing.text()` in that run. These timings include source retrieval;
the sample remains too small to establish population coverage. IBM's Item 7
and Item 8 bodies are short pointers, so the returned spans do not include the
referenced annual-report content.

### Additional named SEC annual sample

A second sequential live check selected the latest unamended 10-K for AAPL,
MSFT, NVDA, GOOGL, AMZN, META, TSLA, JPM, WMT, JNJ, UNH, BAC, XOM, CVX,
GE, BA, F, GM, GS and PFE. After the table-heading change, 18 of these 20
issuer paths returned sections whose text exactly matched their declared
`filing.text()` line slices. This is a selected convenience sample, not a
random or population-wide coverage estimate.

### Separate twenty-issuer SEC annual section sample, 2026-10-08

A sequential, uncached latest-unamended-10-K check used ABT, ABBV, ADBE,
AMGN, BKNG, CSCO, DHR, INTC, LOW, MCD, MRK, NKE, NFLX, QCOM, RTX,
SBUX, TMO, TXN, UPS and VZ. Nineteen returned 21-23 source-linked Item
spans, each exactly equal to its declared slice of `filing.text()` lines.
Those complete issuer-to-section calls took 1.03-4.20 seconds each in this
sequential run. MCD accession
[`0000063908-26-000035`](https://www.sec.gov/Archives/edgar/data/63908/000006390826000035/mcd-20251231.htm)
raised `UnsupportedCapabilityError` after resolving the filing and original.
This named sample does not establish population coverage or a latency
distribution.

The McDonald's original has 23 explicit Item candidates, but every one is in
the terminal Form 10-K cross-reference index, around extracted-text lines
1788-1832 of 1870. Its report body does not print matching Item headings.
The index points Item 1 to printed page 3, Item 1A to page 27, Item 5 to
page 26, Item 7 to page 7 and Item 8 to page 38: Item order is not printed
page order. Returning the index rows as contiguous Item body spans would be
wrong. The installed EdgarTools 5.56.0 selected the same accession and
returned 15 named sections including Signatures via its TOC method; its
section records reported `validated=False`. Its Item 1, 7 and 8 text begins
with plausible body content, but this check did not establish exact source
span or full-Item parity between the libraries. Supporting this layout in
OpenCorpFilings needs verified printed-page boundaries and a multiple-span
section contract; the current single-span section API fails closed.

The HTML original contains 72 page-break markers. Seventy consecutive
segments end with source footers numbered 3 through 72, including Item 8's
referenced page 38 and the financial-statement pages through 67. This is a
viable source-backed page-navigation input for this accession. Some Item
targets share a printed page, and some are incorporated from a proxy, so the
footer run alone does not establish exact or complete Item content.

The public `filing.primary_document.printed_page(label)` now accepts a decimal
printed-page label in the same SEC HTML original. It requires one uniquely
longest run of at least three consecutive page numbers at consecutive HTML
breaks, all with the same `Annual Report` footer prefix. A live call on this
MCD original returned page 3 at text lines 99-116, page 38 at 771-798 and
page 67 at 1638-1653; each page text equalled that exact `filing.text()` line
slice. The first page call took 0.337 seconds after filing selection and text
retrieval, including the footer scan. The same document object then served
pages 38 and 67 from the verified-run cache in about 11 and 2 microseconds;
a repeated page-38 call took about 1 microsecond. These sequential timings
show the local cache effect, not a source-network speed claim. Page 38 begins
with an insider-trading-policy
paragraph before its financial-statement material, so it cannot be relabelled
as a complete Item 8 section without a narrower source boundary.

Pfizer accession `0000078003-26-000026` uses body headings inside table cells.
The source block reads `ITEM 1. BUSINESS` while the extracted text separates
cells with a tab. Matching normalized whitespace against source-positioned
lines now returns 19 ordered Items; a named call took 3.48 s including source
retrieval, down from 12.76 s when each heading reparsed its HTML prefix. GE
accession `0000040545-26-000008` has only a compact end-of-report Item/page
reference table in the candidate set. That source remains unsupported rather
than exposing its index rows as filing sections.

The XOM ticker resolved from the current SEC ticker list to CIK `0002115436`
(`ExxonMobil Holdings Corp`), which had no annual filing in this check. The
older CIK `0000034088` (`EXXON MOBIL CORP`) remained directly resolvable and
its latest annual filing was `0000034088-26-000045`. The library preserves the
source's current ticker mapping; it does not silently merge the two entities.

Four older named 10-Ks exposed a different content limitation. KSS
`0000885639-15-000007`, CAR `0000723612-25-000005`, CHTR
`0001091667-25-000034` and CCL `0000815097-16-000030` returned Item 8 spans
of 127, 163, 241 and 299 characters respectively. The first three point to
financial pages elsewhere in the same report; CCL points to Exhibit 13.
Thus a source-verified Item boundary does not imply that the returned span
contains the full referenced financial section. Exhibit/page assembly and a
representation for noncontiguous section spans remain open.

### Filed Item 8 pointer access

The four historical originals above now expose one source-linked leading
Item 8 reference each: KSS `F-3`, CAR `F-1`, CHTR `F-1` and CCL `EX-13`.
The reference's line is inside its returned Item 8 text span. On the CCL
filing, `filing.select_document(document_type="EX-13")` selected the original
`a2015ex-13.htm` document and its EDGAR URL. These references identify where
the filing itself points; they do not validate or assemble the target's full
financial content.

## Cross-provider named workflow, 2026-10-08

A separate Toyota `S100Y8NY` table check read a 1,613,467-byte annual iXBRL
member from its original ZIP. The member carried a UTF-8 BOM; default
`.tables()` returned 97 source-linked tables, 2,510 cells and 17,792 Japanese
characters without a replacement character. This falsified the initial
assumption that this EDINET report needed a Japanese legacy codec. The table
API now also honors declared charsets and accepts an explicit encoding for
unlabelled legacy HTML; the Toyota path remains on the default UTF-8 route.

One sequential live pass used `Company` to select one annual filing, enumerate
documents, download the selected original, extract text and retrieve raw facts
where supported. The selected originals returned nonempty text and facts on
all six routes. Timings include source network latency and different source
formats, so they are observations rather than comparative service targets.

| Market | Filing ID | Original bytes | Text characters | Raw facts | Total |
|---|---|---:|---:|---:|---:|
| US | `0000320193-25-000079` | 1,520,317 | 208,385 | 1,131 | 2.83 s |
| UK | `MzUzNDA4NzU2M2FkaXF6a2N4` | 4,336,135 | 930,092 | 762 | 5.86 s |
| KR | `20250618000208` | 336,232 | 147,875 | 1,033 | 29.82 s |
| JP | `S100Y8NY` | 2,410,352 | 260,742 | 2,182 | 8.07 s |
| FI | `467217` | 10,501,689 | 564,598 | 498 | 5.10 s |
| FR | `432:582412_20250514` | 4,022,063 | 833,870 | 356 | 3.63 s |

On 2026-10-08, a separate saved-file check read Apple's
`0000320193-25-000079` 1,416,841-byte classic XBRL instance from disk and
returned 1,131 source-linked facts without filling its document byte cache.
Toyota `S100Y8NY` returned 2,182 source-linked facts from a saved
2,410,352-byte EDINET ZIP without buffering the package. For that check only,
the 16 MB archive-member file-path threshold was set to one byte; all three
XBRL member byte caches stayed empty. This verifies the file path against
live original content, not the memory peak or default path of small members.

A separate 8,710,277-byte synthetic classic XBRL instance with 130,000 raw
occurrences exposed the full-tree parser's memory cost. Using Python
`tracemalloc` on the same interpreter, peak allocated memory fell from
170,700,641 to 128,687,695 bytes after parsing direct children incrementally.
The runs took 18.84 and 19.90 seconds respectively; neither establishes a
speed improvement. The returned fact list itself accounts for much of the
remaining memory. This synthetic check is not a regulator-file coverage test.
After the change, the saved Apple and Toyota originals again returned 1,131
and 2,182 source-linked facts. Toyota's member threshold was set to one byte
for the file-path check, and its XBRL member caches remained empty.

Korea's selected original download consumed 21.81 s of that run, and raw-fact
retrieval, including a separate package and parsing, consumed 6.54 s. This points to
source request time as the likely dominant cost; it does not justify changing
the shared parser without a controlled repeat measurement.

Spanish CNMV annual record `2025031726` separately saved a 28,162,648-byte
original ZIP through `download(path)` in 22.72 s, retained no package byte
buffer, and exposed nine ZIP members. Its source URL remains on the document.

Swedish Finanscentralen annual record `502017-7753:annual:2025`, source file
`61644`, saved a 7,725,663-byte ZIP through `download(path)` in a live check.
The document retained no package byte buffer and exposed ten ZIP members.
This confirms memory behavior; source network time remains the dominant cost.

A later Swedish name-search probe exposed two valid source layouts. `Volvo`
returned a multi-company result table, while `Ericsson` and `Atlas Copco`
opened a unique company detail directly. The latter layout previously raised
`ParseError`; both names now resolve to source registration numbers, with the
detail-page LEI preserved. An end-to-end Ericsson run selected annual record
`556016-0680:annual:2025`, downloaded the 3,328,258-byte original file `61807`,
and extracted 1,156,300 text characters with provenance. The 28.35-second
run spent 22.89 seconds resolving the issuer through the source form. These
named checks do not establish Swedish issuer-population coverage.

The shared Nasdaq OAM adapter streamed one current annual ZIP in each of its
three markets: KONE (FI notice `467217`, attachment `337782`, 10,501,689 bytes,
10 members), an Icelandic bank (IS notice `467593`, attachment `338161`, 13,080,200
bytes, nine members), and Apranga (LT notice `471439`, attachment `342920`,
6,823,545 bytes, nine members). All three saved with no original package byte
buffer. These checks establish selected-file behavior, not market coverage.

### Finnish OAM metadata coverage probe, 2026-10-08

A bounded five-issuer probe resolved source IDs `552` (KONE Oyj), `690`
(Nokia), `674` (Neste Oyj), `1099` (UPM-Kymmene) and `4754` (Nordea Bank
Oyj). All five returned a latest annual notice with a source URL and three or
four original document links of known ZIP/PDF type; observed issuer-to-document
metadata time was 1.69–2.44 seconds each. No original bytes were downloaded.
An earlier probe using familiar names failed issuer lookup for “Nokia Oyj”,
“UPM-Kymmene Oyj” and “Nordea Bank Abp”; the source selector instead lists
the names above. `search_companies()` returned the correct IDs. This is a
named workflow check, not a Finnish issuer-population coverage estimate or a
guarantee of download/content availability.
Two selected originals were then read separately: Nokia notice `468712`
returned 931,235 extracted text characters and 868 raw facts in 7.63 seconds;
UPM-Kymmene notice `468520` returned 835,157 characters and 556 raw facts in
7.31 seconds. These are named original ZIP paths, not a text-fidelity audit or
an accounting normalization claim.

### French OAM metadata and original-format probe, 2026-10-08

A bounded five-issuer probe used official LEIs for LVMH, L'Air Liquide,
TotalEnergies SE, Sanofi and Schneider Electric SE. Each returned an annual
source record and one ZIP original link with provenance; observed
issuer-to-document metadata time was 0.80–1.17 seconds per issuer. This is a
named issuer sample, not a national coverage rate. LVMH's selected original
returned 1,700,080 text characters and 697 raw facts.

Sanofi notice `240:614709_20260217` initially yielded 1,227,561 text
characters but reported facts unavailable. Its ZIP contains a 20,044,943-byte
`sny-20251231.htm` with inline XBRL tags. The shared raw parser recovered
6,264 facts when given that member directly; the France adapter had considered
only `.xhtml` members. After admitting tagged `.htm`/`.html` members, the public
`filing.facts` path returned all 6,264 raw occurrences with the ZIP entry path
and original source URL. Candidate ZIP members are extracted on demand and
stop at the first tagged report. Untagged HTML remains without a raw-fact claim.

The selected LVMH, Sanofi, TotalEnergies and Schneider annual packages each
had one HTML report candidate; this sample did not justify aggregating across
multiple tagged members. TotalEnergies' 55.1 MB XHTML returned 782 raw facts.
In two separate end-to-end runs with `tracemalloc`, the byte-backed path peaked
at 189.5 MB of traced Python allocations and the file-backed path at 59.9 MB;
the latter did not retain the member bytes. Source/network and tracing overhead
make their 8.67/16.18-second fact-read times unsuitable as parser speed claims.
On one locally saved copy, repeated byte parses took 2.8–3.2 seconds and
file-backed parses 3.46–3.59 seconds, with identical facts. Sanofi's 20 MB
`.htm` also returned all 6,264 facts from the file-backed path with no retained
member-byte cache.

### Large Spanish XHTML text, 2026-10-08

Two named CNMV FY2025 annual originals passed the common workflow. Inditex
record `2026036808` selected a 39,701,810-byte ESEF ZIP, returned 1,617,465
text characters and 650 raw facts. Santander record `2026029493` selected a
29,430,116-byte ZIP, returned 3,775,688 text characters and 1,952 raw facts.
The download stages took 51.40 and 35.58 seconds respectively; these are
source/network observations, not a transfer-speed target. A repeat known-date
Open DART receipt `20250618000208` still returned the regulator's maintenance
status `800` at original download after entity and filing selection.

Santander's largest XHTML archive member is 84,685,289 bytes. With that same
locally saved member already loaded, the previous whole-string HTML decode
produced 3,775,688 text characters with SHA-256
`29dc13ac5b891e07f135ecc0fe51615e50d633185d7a7225da245f82befe8751`
and peaked at 254.1 MB of traced allocations during text extraction. Feeding
the HTML parser through incremental 1 MB decoder chunks produced the same
length and hash at a 50.4 MB traced peak. The member byte buffer itself was
outside both traces. Timed traced runs were 55.82 and 55.01 seconds; this
supports a memory improvement, not a speed claim. The temporary source ZIP
used for the comparison was removed after verification.

The follow-up file-backed member path saved the same Santander original ZIP,
then called public `filing.text()`. It produced the same 3,775,688 characters
and SHA-256 at a 50.4 MB traced peak, with neither the 29.4 MB package nor the
84.7 MB member retained as a byte cache. The traced text stage took 73.2
seconds in that separate run; network, disk and tracing effects preclude a
speed comparison. Its temporary original was removed after verification.

After the other HTML/XHTML ZIP adapters adopted the shared member path, a live
Swedish FY2025 annual filing (`502017-7753:annual:2025`) saved its 7,725,663-byte
original ZIP and selected a 37,698,387-byte report member. Public
`filing.text()` returned 1,336,369 characters with SHA-256
`53c6d29e5981919b4122d8c54fe5cea37e26b7119dcd2d531cd2f4e450fd558e`.
Neither the package nor member bytes remained cached on their objects. The
temporary original was removed. This is one source-path check, not a population
or speed claim.

A live SEC direct-original check saved Apple's annual accession
`0000320193-25-000079` as 1,520,317 bytes of HTML. Public `document.text()`
returned 208,385 characters (SHA-256
`b32072bbb1a1e5bff360624f3451d8d1eeec14177690ae8bb9c85beb261d6870`)
with no retained original-byte cache. Its temporary original was removed.
This confirms the saved-file path for one filing, not a population claim.

Swedbank's live FY2025 annual record `502017-7753:annual:2025` saved its
7,725,663-byte ZIP, then parsed 561 raw inline facts from a 37,698,387-byte
XHTML member in 6.46 seconds on this run. Neither package nor selected member
bytes remained cached. The temporary original was removed. This is one named
source-path and timing observation, not a general parser-speed claim.

The package-only Czech ESEF index record `441` saved a 3,022,746-byte original
ZIP. Its 22,980,856-byte report XHTML returned 310 raw inline facts in 2.38
seconds on this run. Neither package nor member bytes remained cached. The
temporary original was removed. This checks one package-only route and is not
a general speed or coverage claim.

Keyless Companies House annual accounts receipt
`MzUzNDA4NzU2M2FkaXF6a2N4` saved a 4,336,135-byte original ZIP. Its
19,453,404-byte report XHTML returned 762 raw inline facts in 2.44 seconds
on this run, with neither package nor member bytes retained in the object
caches. The first fact retained its original Companies House URL and ZIP path.
The temporary original was removed; this is one named source-path check.

Inditex CNMV FY2025 annual record `2026036808` saved its 39,701,810-byte
original ESEF ZIP. Its 67,268,985-byte report XHTML returned 650 raw inline
facts in 5.21 seconds on this run, with both package and member byte caches
empty. The temporary original was removed. This checks one large CNMV source
path; the timing is not a general parser-speed target.

Three live Nasdaq OAM annual originals passed the shared FI/IS/LT fact path.
KONE FI filing `467217` saved a 10,501,689-byte ZIP; its 18,415,341-byte
report returned 498 raw facts in 1.83 seconds with package and member byte
caches empty. Iceland filing `467593` saved 13,080,200 bytes and returned 414
facts from a 32,576,544-byte member, again with both caches empty. Lithuania
filing `471439` saved 6,823,545 bytes and returned 323 facts; its 14,822,500-byte
member stayed in the ordinary byte cache because it is below the 16 MB
file-backed threshold. Each temporary original was removed. These named
checks do not establish national coverage or comparative parser speed.

The Polish KNF mBank annual record `87CC574FDDF43ADAC1258DAA00614B3B`
saved an 11,253,257-byte original ZIP. Its nested 22,164,781-byte report
returned 733 raw inline facts in 3.09 seconds on this run; the outer original
and selected report byte caches remained empty. Other nested reports were
listed but not parsed after the first tagged report returned facts. The nested
archive payload may still reside in its parent member object. Malta BOV568's
direct 60,760,642-byte XHTML original returned 813 raw facts in 1.47 seconds
with its document byte cache empty. Both temporary originals were removed.
These are named source-path observations, not population or speed claims.

Cardinal Health fiscal 2026 SEC 10-K accession `0000721371-26-000038` has a
terminal split-cell cross-reference index and 89 verified printed pages.
`section_references()` now resolves Items 1, 7, 8, 10 and 15 to original
start pages 25, 3, 50, 83 and 84, retaining the filed page-line positions.
`sections()` still fails closed: the index does not establish complete Item
boundaries. This is a named source-layout check, not SEC-wide coverage.

A separate held-out, named sample queried the latest annual filing for AMD,
INTC, META, TSLA, UBER, PYPL, NKE, HD, PEP, KO, DIS, ORCL, CRM, CSCO, BAC,
WFC, V and TXN. Sixteen latest results were original 10-Ks and returned 21–24
ordered sections. AMD and TSLA selected 10-K/A amendments; those correctly
raise `UnsupportedCapabilityError` for section parsing. Repeating those two
queries with `include_amendments=False` selected original 10-Ks and returned
23 sections each. This tests route behavior on named issuers, not SEC-wide
section completeness. The split-cell index fixture separately covers three
contiguous identical headings and a title longer than 180 characters, so the
reader's validity rule follows the filed layout rather than the one live issuer.

### File-backed literal table access, 2026-10-08

A selected live SEC annual original, Apple accession
`0000320193-25-000079`, saved 1,520,317 original HTML bytes. Calling the
public `document.tables()` on that saved file returned 62 source-linked
literal tables while `document._cached_bytes` remained empty. This checks one
saved-original path and source URL linkage; it is not a parser speed or SEC
table-coverage claim. Offline equivalence checks compare the same table
objects from bytes and a file across a UTF-8 chunk boundary and a declared
legacy charset.

### Independent twenty-issuer 10-K section check

The latest unamended annual original was selected for ABT, ABBV, ACN, ADP,
AMGN, AXP, BLK, CMCSA, COP, CVS, DE, DHR, FDX, GILD, HON, LMT, LOW, MRK,
NOC and UPS. Before the next parser change, 18 returned ordered sections with
text exactly matching every reported source-line slice; ADP and AXP raised
`UnsupportedCapabilityError`. This is a named convenience sample, not a
population coverage estimate.

ADP accession `0000008670-26-000030` prints its final body heading as
`1.Item 15. Exhibits, Financial Statement Schedules`. Its explicit contents
provides the same Item code and title. The contents-backed list-prefix rule
now returns 22 sections through Item 15, all matching the original text-line
slices. On the same accession, isolated EdgarTools 5.61.1 also returned 22
Item keys. Twenty Item word counts matched, and 21 of 22 matched both the
first and last twelve word tokens. Item 7 differed by four words with matching
boundaries; Item 15 had a different end boundary. These observations do not
establish full content equivalence.

AXP accession `0000004962-26-000080` has one body heading jointly naming
Items 10, 11, 12 and 13. Isolated EdgarTools 5.61.1 returned 24 keys, but
its four Item 10–13 entries each yielded the same 554-word group text. The
standalone API then rejected distinct Item spans for that original; nineteen
of the twenty named filings returned source-matching sections after the ADP
layout fix.

The shared-span follow-up returns one AXP section labeled `10-13` with
`items=("10", "11", "12", "13")`. Looking up any of those four codes returns
that same section. Its live source-line range is 3749–3763; every returned
AXP section exactly matches its slice of `filing.text()`. The shared section
has 557 word tokens versus EdgarTools' 554 because the source span retains
the filed page footer and table-of-contents line before Item 14. All twenty
named originals now return source-matching sections, but AXP's count is one
shared group rather than four independent Item spans. This is one verified
layout, not a population coverage claim.

## Route qualification, declared 2026-10-08

This section fixes the acceptance rule and the sample **before** the run, so a
route's tier is judged against a rule written without seeing its results.

**One-filing acceptance workflow.** For each sampled issuer and form,
`benchmarks/qualify.py` runs `benchmarks/provider_workflow.py --facts` in its
own process: resolve the issuer, select the latest filing of the form, list its
documents, download the primary original, then read text and raw facts. Each
row gets one deterministic label:

| Label | Meaning |
|---|---|
| `pass` | entity, filing and document source URLs present; original bytes returned; nonempty text when the original is HTML, XHTML or a ZIP package |
| `text_gap` | workflow completed, but a text-bearing original returned no text |
| `no_filing` | no filing of that form in the window (`FilingNotFoundError`) |
| `source_unavailable` | source outage or rate limit, rerun once before judging |
| `fail_<stage>` | any other error, at the named stage (`entity`, `latest`, `documents`, `download`, `text`, `facts`, `program`, `timeout`) |

A PDF original with no extractable text is not a gap: OCR is out of scope.
Raw-fact counts are recorded for review but are not part of the label; zero
facts from an ESEF annual package is investigated as a possible defect.

**Tiers (annual form).**

- **Supported:** every sampled issuer passes, after one rerun of rows that were
  only `source_unavailable`. A `no_filing` counts against the route unless the
  source itself confirms the issuer filed nothing of that form in the window.
- **Limited:** some issuers pass, or every issuer passes but the source lacks
  part of the common contract (for example no filing date).
- **Pending:** no sampled issuer passes, or the route is unresolved (HK).

The interim form is reported separately with the same labels; a route's
interim selection is "supported" only on the same 5/5 rule.

**Sample.** `benchmarks/qualification_sample.json` records the issuers and the
selection rule: per route two large caps, two mid/small caps and one bank or
insurer, none named in an earlier live check of that route, identifiers taken
from the route's own entity search. Liechtenstein's source lists two issuers,
so both run. The ESEF index is one adapter, sampled as one issuer in each of
five countries without a national route (IT, NO, AT, PT, LU). 194 workflow
runs in total. Results follow below once the run completes.

### First run results, 2026-10-08

Raw rows: `run1.jsonl`, kept outside the repository.
Passes out of sampled issuers, before the review below:

| Route | Annual | Interim | Main cause of non-pass |
|---|---|---|---|
| US | 5/5 | 5/5 | - |
| UK | 5/5 | - | - |
| JP | 5/5 | 5/5 | - |
| FR | 5/5 | 4/5 | BNP's half-year reports since 2023 are filed under another source category |
| KR | 0/5 | 0/5 | Open DART status `800` (source maintenance) throughout |
| SE | 0/5 | 0/5 | harness error: passed a date filter the route rejects |
| ESEF index | 0/5 | - | harness error: passed `form` the route rejects |
| other national routes | 1/5-5/5 | 1/5-5/5 | see the review findings in the integration plan |

**The pass label overstated success.** A later code review found `pass` rows
that returned the wrong content: PL `text()` decoded gzip bytes (54%
non-printable), DK interims returned an ~8k-character cover notice, MT
returned a 2024 interim as the latest, and `latest()` on SEC can return a
Part III 10-K/A. The rule above checked only that text was non-empty. The
next run must also check text readability, document role and size, and the
report period against the source's newest record; the US annual result does
not establish amendment handling. These rows therefore do not support any
route's tier yet.

## Route qualification v2, declared 2026-10-09

Declared before the run, after the correctness fixes of 2026-10-08/09. The v1
`pass` label overstated success, so v2 adds content checks. A completed
workflow is now labelled, in this order:

| Label | Meaning |
|---|---|
| `amendment_selected` | a category request returned a source-flagged amendment |
| `wrong_document` | the primary document's `role` is set and is not `report` |
| `text_gap` | a text-bearing original returned no text |
| `unreadable_text` | under 90% of extracted characters are printable or whitespace (U+FFFD counts as unreadable) |
| `text_small` | a text-bearing original yielded under 20,000 characters |
| `stale` | report period older than 548 days (annual), 304 (interim) or 213 (quarterly) on the run date |
| `pass` | none of the above, plus the v1 conditions |

An unknown role or period is not a failure by itself (France states no
period). PDFs are exempt from `text_small`.

**Tier rule (unchanged).** `supported` needs every sampled annual row to
pass, after one rerun of `source_unavailable` rows; a `no_filing` or `stale`
row needs source evidence that the issuer has filed nothing newer. The interim
form is judged on the same rule separately.

**Sample.** `benchmarks/qualification_sample_v2.json`: for US, UK, JP, FR and
KR the five v1 issuers plus five fresh ones (same selection rule); for the
ESEF index the five v1 LEIs plus, for each of the 21 index countries, the
issuer whose record the index added most recently. 116 workflow runs.

### v2 results, 2026-10-09

Raw rows, kept outside the repository: `run2.jsonl` (116 rows) and
`run2b.jsonl` (KR and FR rerun after the fixes below).

| Route | Annual | Interim | Tier decision |
|---|---|---|---|
| US SEC | 10/10 | 10/10 | supported |
| UK Companies House | 10/10 | n/a | supported |
| JP EDINET | 10/10 | 2 pass, 7 `stale`, 1 `text_small`, all reviewed as correct | supported |
| FR OAM | 10/10 after fixes (7/10 before) | 9/10 | supported; interim selection limited |
| KR Open DART | 0/10, `source_unavailable` | 0/10, `source_unavailable` | not qualified; stays experimental |
| ESEF index | 12 pass, 14 `stale` | n/a | limited |

What the run found and what changed:

- **France, issuer identity.** SEB's universal registration documents carry no
  LEI and AXA's carry a second AXA LEI; both carry the share ISIN. LEI-only
  lookup returned no annual report for either. The route now also matches the
  ISINs on the issuer's own LEI-tagged record; both found their 2025 URD.
- **France, large reports.** Michelin's FY2025 report XHTML exceeds 100 MB;
  facts now stream from disk (457 facts, 11.3 s).
- **France interim.** BNP Paribas publishes its half-year report as an update
  to its universal registration document, which the source does not code as a
  half-year report (`004000`). `form="interim"` cannot select it; this is
  recorded as a limit of the source classification.
- **Korea.** Listing worked, but `document.xml` returned status `800`
  ("suspended for maintenance") on both the English and Korean endpoints in
  both runs, two days after the same status in v1. Korea cannot be qualified.

Two pre-registered thresholds were wrong, found by reviewing the flagged rows
against the source:

- **Interim staleness (304 days)** is too tight for half-year reporting. A
  half-year ending 30 September is filed in November; a year later the next is
  not yet due, so the newest report period can legitimately be about 410 days
  old. All seven JP `stale` interim rows have period end 2025-09-30, the newest
  half-year any of these March-year-end issuers has filed.
- **`text_small` (20,000 characters)** assumes English density. Nintendo's
  half-year report text is 18,932 Japanese characters across 11 source files
  and includes the interim balance sheet, income statement and business
  sections.

The ESEF `stale` rows are FY2024 reports from countries where the index holds
no FY2025 records yet; this is the lag the route's freshness table discloses.

## Route qualification v3 (second wave), declared 2026-10-09

Declared before the run. Routes: ES, NL, DK, SE, PL and FI national OAMs,
after they moved onto the shared package reader (`packages.py`) and the
review fixes (Finland name drift, Denmark cover notices, large nested
packages). Labels as v2, with one threshold changed before this run because
v2 showed it was wrong: interim staleness is 425 days (a half-year report can
be ~365 + 60 days old), not 304. Sample: `benchmarks/qualification_sample_v3.json`,
each route's five v1 issuers plus five fresh ones; forms per route profile;
Sweden without a date filter. A route stays `experimental` unless every annual
row passes; promotion requires a release review.

### v3 results, 2026-10-09

Raw rows, kept outside the repository: `run3.jsonl` (110 rows) and
`run3b.jsonl` (SE, PL and DK rerun after the fixes below).

| Route | Annual | Interim | Notes |
|---|---|---|---|
| ES CNMV | 10/10 | 10/10 | |
| NL AFM | 10/10 | 10/10 | |
| FI Nasdaq OAM | 10/10 | 10/10 | Nasdaq access-terms review pending |
| SE Finanscentralen | 10/10 | 10/10 after fix (9/10) | |
| PL KNF | 10/10 after fix (7/10) | n/a | |
| DK Danish FSA | 10/10 | 8/10 | both misses are source-side, below |

Fixed during v3:

- **Poland.** KNF gzips every attachment and some issuers file the ESEF
  report as a bare XHTML (LPP), which the locator skipped; gzip-compressed
  markup is now read, and ESEF-named files rank ahead of a larger management
  report. CD Projekt's latest annual had been a flagged correction; Poland
  now returns original reports by default, keeping rows whose flag is
  unrecognized. Standalone (`RR`) reports carry no XBRL tags, so they have
  text but no facts; when a package has no ESEF-named file, text comes from
  its largest document, often the management report.
- **Sweden.** Sandvik's half-year table lists 2024 twice with the same
  languages; the adapter rejected the whole listing. A repeated row is now its
  own record (`:2` suffix, `repeated_period` in metadata), in source order.

Source-side, not changed:

- Matas filed its H1 2025/26 report under the annual category, so
  `form="interim"` finds none (also seen in v1).
- Danske Bank's H1 2026 notice holds only English and Danish HTML
  announcements (8,708 characters); the report itself is published elsewhere.

All six routes stay `experimental` pending a release review.

## Primary statements from filed tables, experiment 2026-10-09

Question: can the income statement, balance sheet and cash-flow statement be
picked from an iXBRL report's own HTML tables by the concepts tagged inside
them? Rule declared before the run (`benchmarks/statements_probe.py`):
cash-flow concepts make a cash-flow table; otherwise total assets (or total
liabilities and equity) make a balance sheet; otherwise revenue or profit make
an income statement; tables with under eight tagged values are ignored; the
most-tagged table of each kind is picked. Each pick's first rows were read and
judged by hand. Raw rows are kept outside the repository.

**Result: 24 of 57 picks right; all three right in 2 of 19 filings** (Apple,
Danone). Balance sheets split into an assets table and an equity-and-
liabilities table were counted right when either half was picked.

| Cause | Filings | Deterministic fix? |
|---|---|---|
| Report has no HTML tables (positioned page blocks) | Enel, Galp, PwC DK, Nightingale FI, Legrand (5 of 19) | no; tables cannot work |
| Statement of changes in equity taken as the income statement (it contains profit) | Linde, Crocs, Sainsbury, Verbund, Equinor, ArcelorMittal, Toyota | yes: require revenue or exclude equity roll-forwards |
| A segment table outscored the income statement | Deere, PNC | yes: prefer facts without dimensions |
| EDINET's five-year summary table picked first | Toyota, Hitachi, Kewpie, MUFG | yes: EDINET's fixed statement section |

Decision recommended: do not build statements from tables. A quarter of the
ESEF/French reports have no tables to read. Better routes for a later
release: SEC's own rendered statement pages listed in `FilingSummary.xml` for
US filings, and the package's presentation linkbase plus facts for ESEF and
EDINET (independent of layout, but it needs standard taxonomy labels).
