# Changelog

## Unreleased

- Dependency maintenance: monthly checks group minor and patch updates per
  ecosystem, while major upgrades remain separate PRs. Contributor guidance
  covers release-note review, CI, package installation and live Pages checks.
- CI and documentation deployment use checkout/setup-python v7 and the Pages
  upload/deployment actions v5.

- Refined README navigation, quickstart and workflow examples; compact market
  and content tables link to the full guides. Release and compatibility badges
  identify the supported release; CI is linked directly from the header.

- Shorter README with a SEC quickstart, cross-market examples and explicit
  coverage tiers. Branding includes only the GitHub logos and social preview,
  with the documentation assets kept separately.
- Documentation page titles and descriptions, canonical URLs, sitemap and
  social sharing metadata prepared for GitHub Pages.
- Repository code ownership identifies the SourceState organization maintainers team.

## 1.0.2 — 2026-10-11 (private release)

- `filings[0]` and `filings[:5]` work: a collection takes positions and
  slices, listing only as far as asked.
- Docs site: a "Find a company" page searches the US, Japanese, French and
  ESEF-index company lists in the browser and gives the `Company(...)` line to
  copy. `scripts/build_find_index.py` builds its list, and a Pages workflow,
  inactive while the repository is private, rebuilds it weekly.

## 1.0.1 — 2026-10-11 (private release)

Fixes from a review of the whole library. Each fix has a test that fails on 1.0.0.

US (SEC EDGAR)
- `form="ownership"` includes Schedules 13D and 13G filed under their names
  since December 2024, `SCHEDULE 13D` and `SCHEDULE 13G`.
- For Forms 3, 4 and 5 and other XML forms, the primary document is the filed
  XML. It was SEC's rendered view, with the filed original listed as "other".
- `get_filing()` accepts a combined filing looked up under any of its
  co-registrants, not only the first one listed.
- `facts()` on a filing whose submissions record says it has no XBRL fails at
  once instead of downloading every document first.

Japan and Korea
- Securities codes with letters (`130A`, issued since 2024) open with
  `Company()` and come back from `find_company()`.
- Text uses the library's HTML reader, so it no longer includes hidden
  inline-XBRL facts, and lines are kept.
- A repeated EDINET scan reuses the newest daily lists. The cache evicted those
  first, so a second scan of more than 90 days re-read every day.

UK, France and the national European routes
- Companies House: `filings(start=...)` stops at the first filing older than
  `start` instead of reading the company's whole history. With an API key,
  `form="annual"` asks the source for accounts only. An all-digit company
  number shorter than eight digits, such as `"185647"`, is zero-padded instead
  of being searched as a name.
- France: a company opened from a search result is resolved first, so filings
  found only by share ISIN (SEB's annual reports carry no LEI) are listed.
- Finland, the Netherlands, Denmark and France read file extensions from one
  table: `.xbri` is an ESEF package on every route.
- Sweden downloads XHTML that starts with a byte-order mark or uses upper-case
  tags.
- Denmark and the Netherlands give a time-zone-aware `published_at`, so
  filings from several markets sort together. This adds `tzdata` as a
  dependency on Windows, which has no time-zone database.

Text, HTML and downloads
- `text()`, `html()`, `markdown()` and `tables()` choose an encoding the same
  way: a byte-order mark, else UTF-8 if the bytes are valid UTF-8, else the
  declared charset, else UTF-8. `text()` used to ignore a declared charset, which
  also broke 10-K sections on such filings. The `encoding` default is now
  `None`. A document `html()` or `markdown()` cannot decode raises `ParseError`
  instead of `UnicodeDecodeError`.
- An archive member's `html()` works for gzip-wrapped and very large members,
  as `text()` already did.
- `FilingCollection.download()` reports this run's `filings`, not the
  manifest's total, and gives two documents whose names differ only in case
  separate files, as Windows and macOS need.
- `find_company()`: a rebuild while a source is down keeps the previous
  index's rows for that list instead of dropping them.
- Request pacing is shared per source host, so two `Company` objects on one
  source no longer double its request rate.

Faster
- A saved package is hashed once while its members are read, not once per
  member access.
- Printed-page and 10-Q contents-anchor lookups map positions in one pass;
  they were quadratic, taking 10-27 s on a 10 MB filing.

Removed: duplicated code (the transport's five retry loops,
the European adapters' download and save code, the Japanese and Korean text
parsers, XBRL context parsing) and unused code (`ROUTE_TIERS`, an unused
`sec_printed_pages.printed_page`, leftovers of retired routes); with the fixes
added, the package source is 44 lines shorter. The sdist now
includes `tests/conftest.py`, which blocks network access in tests, and the
benchmark samples.

## 1.0.0 — 2026-10-10 (private release)

Highlights since 0.1.0: a focused release scope (US, UK, JP and FR supported;
the ESEF index limited; Korea and six European national routes experimental,
with a warning when opened); original reports rather than amendments by
default; document roles and one primary-document rule; `find_company()`;
per-company bounded downloads with a manifest; readable printing,
`to_dict()` and optional pandas export; a stated compatibility promise
(README, Stability). Eleven small-market national routes were retired.

- **Renamed to OpenCorpFilings** (was SourceState Filings). The package and
  distribution are `opencorpfilings`, the command is `ocf` (was `ssf`), the
  base error is `OpenCorpFilingsError`, environment variables use the
  `OPENCORPFILINGS_` prefix (was `SOURCESTATE_`; `OPENCORPFILINGS_CACHE_DIR`
  replaces `SOURCESTATE_FILINGS_CACHE_DIR`), the User-Agent is
  `OpenCorpFilings/<version>` and the default cache is
  `~/.cache/opencorpfilings`. No aliases remain for the old names. Entries
  below use the new names.
- A new README, a brand kit (`brand/`: logo, wordmark and icon as outlined SVG
  and PNG, favicons, social preview, usage notes), a documentation site
  (`mkdocs.yml`, `docs/`), `SECURITY.md`, issue and pull-request templates.
  `tests/test_readme_examples.py` fails when the README names an import,
  method, command or environment variable the code lacks;
  `scripts/check_readme.py` runs the README's examples against live sources.
- France: an exact native code now matches a record that carries it as a
  secondary code, as the source query already did. `form="003000"` had raised
  `ProviderError` on Legrand's annual report, filed as a registration document
  (primary code `300005`, secondary `003000`).
- `find_company`: an index built without `OPENCORPFILINGS_SEC_USER_AGENT`
  has no US companies. It was kept for a week even after the variable was
  set, and only the call that built it warned. It is now rebuilt as soon as
  the variable is set, and every search warns while a list is missing. An
  index missing a list that failed to download is retried after an hour.
- The test suite blocks network connections and ignores the caller's
  `OPENCORPFILINGS_*`, `EDINET_API_KEY` and `OPENDART_API_KEY` settings; with
  real keys set, 55 tests had failed.
- Opening a `Company` on an experimental route emits one
  `ExperimentalRouteWarning` per route and process.
- `search_companies("Apple", market="US")` ranks the company the query names
  (Apple Inc.) ahead of longer names that start with it (Apple Hospitality
  REIT). An SEC accession that belongs to another company raises
  `FilingNotFoundError` instead of `ParseError`.
- A missing optional extra raises `UnsupportedCapabilityError` for pandas as
  it already did for Markdown and PDF text (pandas raised `ImportError`).

- `find_company()` and `ocf find` search every first-release market for a
  name, ticker, securities code, ISIN or LEI and return the market and the
  identifier to pass to `Company`. The index (about 14.6k listed issuers on
  2026-10-09) is built locally from official lists and cached for a week; the
  UK is searched live at Companies House.
- `download(..., file_types=(".pdf",))` and `ocf download --file-type pdf`
  keep documents with chosen extensions across all of a filing's documents.
- Five example notebooks in `examples/notebooks/` with stored outputs from
  live sources; `scripts/run_notebooks.py` refreshes them without Jupyter.
- Sweden keeps a period that the source lists twice with the same language
  (Sandvik's 2024 half-year report) as a separate record with a `:2` suffix
  and `repeated_period` in metadata, instead of failing the whole listing.
- The ES, NL, DK, SE, PL and FI routes read packages through the shared
  `packages.package_text`/`package_facts`, replacing six drifted copies: nested
  `.xbri`/ZIP/`.asice` and gzip-wrapped reports are found, and a nested
  package of 16 MB or more spills to a temporary file instead of failing at
  100 MB (Sligro's 182 MB `.xbri`). Finland no longer rejects a notice whose
  row shows a drifted company name. Denmark marks an HTML cover notice beside
  a PDF/ZIP as `announcement`, so the report becomes the primary document.
  Each route declares a profile. Poland's category requests now return
  original reports by default (CD Projekt's latest annual had been a
  correction); a row whose correction flag is unrecognized is kept, as France
  does. KNF's gzip-compressed bare ESEF XHTML reports are read, and ESEF-named
  files rank ahead of larger management reports (LPP, PKO BP).
- **Removed:** the national routes for Iceland, Lithuania, Latvia, Croatia,
  Romania, Slovakia, Estonia, Malta, Cyprus, Hungary and Liechtenstein. IS, LT,
  HR, SK, EE, MT and HU fall back to the ESEF index route; RO, LV, CY and LI
  are no longer supported markets.
- `API.md` is generated from the public objects by `scripts/api_reference.py`;
  a test fails when it drifts, and every public method and property now has
  a docstring (25 had none). The package ships `py.typed`, declares
  "Development Status :: 3 - Alpha" and project URLs, and CI adds a base
  install job on Windows and Ubuntu without extras.
- `FilingCollection.download(directory)` and `ocf download --output-dir` save
  one company's bounded selection with a resumable `manifest.json` (source
  URLs, SHA-256, sizes, per-filing errors). An unbounded history needs
  `all_history=True` / `--all-history`; there is no multi-company download.
- France OAM finds an issuer's records through its share ISIN as well as its
  LEI: SEB's annual reports carry no LEI and AXA's carry a second AXA LEI, so
  LEI-only lookup returned no annual report for either. ISIN-matched records
  say so in `provider_metadata["matched_by"]`. French language labels become
  ISO codes (`Français` -> `fr`); facts from a report over 100 MB stream from
  disk (Michelin FY2025: 457 facts).
- Real source responses for one issuer per supported route are recorded under
  `tests/fixtures/recorded/` and replayed offline (`benchmarks/record_fixtures.py`).
- Open DART category requests ask the source for that report type
  (`pblntf_detail_ty`): Samsung's latest annual took 7.0 s instead of 63 s,
  its half-year report 0.7 s. Open DART and EDINET use a fixed UTC+9 offset,
  so the JP route no longer needs a time-zone database (it failed to import
  on Windows without `tzdata`).
- EDINET keeps the 90 most recent past days in memory, because the API's
  `no-cache` headers had disabled the transport reuse the README described.
  `period_end` is now the report's period: a half-year report ends six months
  into the fiscal year (EDINET's own fields give the whole fiscal year), and
  a quarterly report has none.
- SEC requests share one pacer per process across `Company` objects, keeping
  the 10 requests/second fair-access limit with threads. Pre-2009 `10-K405`,
  `10-KSB`, `10-KSB40`, `10-KT405` and `10-QSB` filings now count as annual
  and quarterly.
- **ESEF index route, now tier `limited`:** filings are ordered by report
  period, not by when the index added them (Enel's FY2021 had sorted ahead of
  FY2022); each record carries its language from the report filename, with
  English first within a period; records are typed `ESEF`/`ANNUAL` and
  `form="annual"` is accepted. Package downloads are no longer kept in the
  response cache. CZ, CY, RO, LV and PL are dropped because the index stopped
  receiving them. `benchmarks/esef_index_freshness.py` regenerates the
  README's coverage table (FY2025 at 45% of FY2024 on 2026-10-08).
- Each route declares a profile (tier, identifiers, forms, native forms, date
  filters, auth, coverage note) exposed by `provider_info()` and `ocf markets`.
  `Company.filings()` refuses an unservable request before any source call:
  UK `form="interim"` now fails in under a second instead of a 51 s scan.
  Unknown markets raise `UnsupportedMarketError`, a `ValueError` subclass.
- `FilingDocument.role` classifies each document (`report`, `exhibit`, `annex`,
  `announcement`, `data`, `generated`, `other`). Apple's FY2025 10-K lists 93
  files: 1 report, 6 exhibits, 6 XBRL data, 78 EDGAR-generated, 2 other.
  `primary_document` now follows one shared rule: a single source-flagged
  document, otherwise the report role, then format.
- Companies House filings carry `period_end` from the accounts "made up to"
  date, and printed filings show their report period.
- **Behavior change:** a category form such as `annual` now returns original
  reports by default where the source flags amendments (SEC, UK, JP, KR, FR).
  TSLA's latest annual is again its 10-K, not the later Part III 10-K/A.
  Pass `include_amendments=True` for the previous behavior. An exact SEC form
  is exact: `form="10-K"` no longer matches `10-K/A`.
- Open DART classifies only the periodic report title itself; a
  deadline-extension notice is no longer an annual or half-year report.
- Reports nested inside packages (`.xbri`, nested ZIP, gzip-wrapped, `.asice`)
  are found by content for FR, UK and ESEF; a compressed or binary member is
  never decoded as text. Reports above 100 MB parse from a temporary file up
  to 2 GB when their compression ratio is plausible (Repsol FY2024: 2.46M
  text characters).
- Public objects print as one line (`<Filing ... 10-K ANNUAL filed=... US/sec>`)
  instead of dumping raw source records, and render a small escaped,
  source-linked table in Jupyter. Printing a `Company` or `FilingCollection`
  never contacts the source.
- `Filing.to_dict()`, `FilingDocument.to_dict()` and `FilingFact.to_dict()`
  return JSON-safe rows. A new optional `pandas` extra adds
  `Filing.facts_to_pandas()` and a bounded `FilingCollection.to_pandas(n)`.
  Fact values stay filed strings.
- `ocf documents` lists one filing's original documents without downloading
  them, using the same filing selection as `ocf download`.
- Removed the prerelease `Filing.search_text()` and
  `FilingDocument.search_text()` convenience methods and `TextMatch` export.
  Callers can search returned text or page-linked PDF text themselves; the
  library keeps source acquisition and provenance as its core contract.
- SEC original HTML 8-Ks now expose source-linked Item spans through
  `filing.sections()` and decimal-code selection such as
  `filing.section("2.02")`. Captions are checked against the SEC form; a
  source signature bounds the last span. A repeated contents list is used
  only when it matches the later body headings.
- The one-filing benchmark now reports the failed public API stage, public
  error type, elapsed time and already resolved IDs as one JSON record with
  a nonzero exit when a source fails. Successful timing output is unchanged.
- The distribution check now compares every package Python module in the
  source tree with both the wheel and source archive, so an otherwise
  importable build cannot silently omit a provider or parser module.
- Temporary HTTP 502/503/504 failures and Open DART maintenance status `800`
  now raise the common `SourceUnavailableError` after bounded retries. HTTP
  429 still raises `RateLimitError`.
- A one-filing benchmark now reports entity, selection, document, download,
  text and optional raw-fact stage timings across market routes.
- SEC `F-` references now resolve to a source-linked `FilingPrintedPage` when
  HTML page breaks verify a consecutive run of printed page footers. Index
  labels and ambiguous runs fail closed. `EX-` references resolve to their
  enumerated original document, without merging either target into Item text.
- `filing.section("Item 8")` selects one source-verified Item without scanning
  the list in caller code. For repeated 10-Q Item numbers, `part="I"` or
  `part="II"` selects the source Part explicitly.
- SEC Item 8 sections now expose explicit leading `F-` page and `EX-`
  document pointers as source-linked `FilingSectionReference` records.
  Section text remains its exact original line span; referenced content is
  not silently merged into it.
- SEC 10-K body-heading sections now accept source table-cell headings whose
  extracted text uses tab separators. A compact page-reference table remains
  unsupported. Source heading positions are mapped to text lines in one HTML
  parse rather than reparsing a growing source prefix for every Item.
- SEC 10-K section navigation now has a source-body fallback that reads
  Item headings from the original HTML. It checks ordered Item headings against original extracted-text lines. The named Mastercard, Procter & Gamble and IBM filings now return
  source-linked sections; attached-report pointers are not followed.
- SEC 10-K section navigation now accepts a unique body heading written as
  `Item 1—Business` and a trailing parenthetical note after the contents
  title. Costco's named 2026 filing returns all 23 source-verified Items.
- Buffered source GETs now reject HTTP 206 partial bodies and unfollowed
  redirects, including on size-limited reads, so incomplete metadata cannot
  enter the parser or response cache.
- Explicit authorization headers, cookie headers and known API-key query
  parameters now bypass the optional local response cache. Public keyless GETs
  retain their cache behavior.
- Markets with an implemented national OAM now select that source by default.
  `source="esef_index"` explicitly selects the separate LEI-based central
  index. Existing explicit `source="oam"` calls still work. This changes the
  default for ES, SE, PL, NL and DK.
- Open DART and EDINET now accept the existing `OPENDART_API_KEY` and
  `EDINET_API_KEY` environment names when their `OPENCORPFILINGS_*` names are
  unset. Explicit keys and namespaced keys retain precedence.
- Selected ZIP originals now require a readable archive directory before
  buffered caching or an atomic streamed save. A truncated source with a valid
  ZIP header no longer appears to be a usable filing package.
- Readable HTML text now omits repeated same-document “Table of Contents”
  navigation links while retaining the heading, other links and original HTML.
- The reproducible SEC benchmark now accepts annual or quarterly reports and
  named tickers. Four additional filings were compared with EdgarTools 5.61.1;
  all pairs selected the same accession, with table-layout differences in text.
- Direct filing lookup now binds its returned filing to the selected provider,
  so third-party adapters support the same document and text workflow as
  collection results.
- Buffered selected PDF/ZIP documents now pass a shared source-byte signature
  check before caching or saving. Providers can still reclassify a source's
  mislabeled XHTML when verified by the returned bytes.
- Optional HTML/XHTML `.markdown()` now works on a filing's primary document,
  one selected document, or one ZIP member. It omits hidden iXBRL metadata
  and embedded image data while retaining original source bytes.
- SEC and Companies House selected PDF/ZIP downloads now verify source-byte
  signatures on buffered reads and streamed saves. A 200 HTML error page no
  longer replaces an existing target or masquerades as an original binary.
- Readable HTML/XHTML text now omits nonvisible document-head and iXBRL-header
  metadata, including alternate inline-XBRL namespace prefixes, and explicit
  hidden containers. Original bytes and raw facts remain unchanged.
- Keyless Companies House issuer search now follows bounded source pagination
  for `limit` values beyond the first page, deduplicates company numbers and
  preserves each candidate's originating search URL.
- Re-saving a previously streamed document to another path now verifies and
  copies its local file in chunks. It does not re-download or buffer a large
  original, and an invalid saved file is refetched.
- SEC primary-document access now uses EDGAR's named file directly. Reading
  one filing's text or saving its primary source skips the archive listings;
  later document enumeration still fills the same object with index metadata.
- The ESEF index now verifies original ZIP bytes against the source SHA-256
  when supplied. One named filing in each of 26 index countries passed the
  common issuer-to-original-ZIP path and checksum check. Captured source rows
  exercise each country offline; this is not national OAM coverage.
- The same 26 selected index filings also returned nonempty text and raw
  facts through one API (14,047,617 extracted characters, 12,876 facts).
  This is source-format evidence for named records, not population coverage
  or cross-country accounting normalization.
- ESEF `download(path)` now streams one selected original to an atomic local
  save. Original ZIPs must pass the source SHA-256 and ZIP signature before
  replacement. A 51,231,666-byte Belgian source ZIP saved live without a
  retained document-byte buffer.
- `Company.get_filing(id)` now uses the ESEF index's direct numeric record
  route, validating the selected LEI and country without scanning listings.
  Named Czech record `441` returned document metadata in a live check.
- ESEF records with only a source ZIP now read the embedded report XHTML for
  text and raw inline facts. A Czech original-only case yielded 310 facts with
  ZIP-member source locations.
- SEC documents now retain the original accession index's raw type,
  description and sequence where listed. `select_document(document_type="EX-21.1")`
  selects an exhibit while the full JSON archive directory still exposes
  auxiliary files. Direct accession lookup reuses the index it already read;
  a named Apple filing exposed 93 archive files and a source-linked EX-21.1.
- Added `search_companies()` for Open DART and EDINET using their official
  corporation/code registries. Results carry regulator IDs, names, available
  stock codes and registry provenance without profile requests. Both adapters
  reuse parsed registry rows within one provider instance. Live Samsung and
  Toyota searches passed; Open DART's 3.62 MB registry response declared
  `no-store` and took about 250 seconds to deliver in this environment.
- Added `FilingDocument.page(number)` for source-linked, one-based PDF page
  access without extracting the full report. A named 735-page OTP Bank PDF
  returned page 1 in 9.28 seconds including its 16.0 MB download; the full
  page cache stayed empty. Repeated selection on one object reuses the page.
- Direct MNB record lookup retains the detail page's document links, so
  opening `filing.documents` does not request that same detail page again.
- Added `.html()` on a filing's primary HTML/XHTML, a selected direct
  document, or an HTML/XHTML archive member. Decoding is explicit and original
  bytes remain available through `.download()`.
- Added source-linked `.tables()` for original HTML/XHTML documents and
  selected ZIP members. It preserves table order, rows, cells, captions and
  literal span attributes, with a 100 MB parse bound and per-object reuse.
  Positioned XHTML and PDF layout are not reconstructed into tables.
- French Info-Financiere issuer-name search returns LEI-backed candidates;
  a unique exact source name resolves through `Company`. Native `diffuser:UIN`
  filing IDs now use one official record query instead of a bounded issuer
  listing scan, with source-key and LEI checks.
- `head(n)` and `latest()` now send their effective bound to the provider,
  allowing source adapters to avoid scanning older pages for one result.
- Added an opt-in Danish OAM adapter for listed source business IDs or exact
  issuer names. Its public announcement search and detail route expose native
  annual/half-yearly categories, publication and registration times, issuer
  identity, direct IDs and individual originals. A named Carlsberg FY2025 ZIP
  yielded XHTML text and 647 raw inline facts. Source-country routing stays
  separate from the issuer ID's country prefix.
- Expanded the common offline company-to-filing-to-original-document-to-text
  acceptance test to all thirteen national OAM adapters plus the four original
  country providers and FR/FI index routes (19 source cases).
- Added an opt-in Netherlands AFM financial-reporting adapter. Exact issuer
  search and annual/half-yearly metadata lead to original filing detail and
  individual `.xbri`/ZIP/PDF links. ASML's FY2025 original 20.3 MB `.xbri`
  ZIP yielded report text and 734 raw inline facts in a named live check.
  Known AFM IDs use a direct detail route. AFM report year remains raw rather
  than an invented exact period end.
- Cached extracted text and raw fact occurrences on each document/filing
  object. Repeated source-linked text searches and exact raw-fact filters no
  longer reparse large reports; returned fact lists are separate copies.
- FI/IS/LT Nasdaq OAM discovery now has a configurable 20-page default safety
  bound. A full result page at the bound raises a clear capability error.
- Saving a document whose bytes were already read now uses a temporary file
  and atomic replacement, preserving an existing destination on write failure.
- Streamed one-document saving for SEC and Companies House, retaining provider
  headers, retries, atomic replacement and hash-checked reuse of saved bytes.
  Other provider downloads keep their source-specific response checks.
- Added an opt-in, bounded local GET response cache with five-minute freshness,
  content checksums, credential-partitioned keys and `no-store` respect.
- Added optional page-linked PDF text for original PDF documents, with source
  page provenance and a text search page pointer. Scanned pages remain empty.
  A live KONE remuneration PDF yielded text on all eight pages; a scanned UK
  accounts PDF yielded no text on 212 pages.
- CNMV financial-report links can resolve to XHTML despite the adapter's PDF
  hint. On download the observed format is exposed while the original hint is
  retained; a named Iberdrola XHTML report yielded readable source text.
- Added official France and Finland OAM annual discovery and individual
  original attachments. FR/FI default to their national source; the central
  index remains available with `source="esef_index"`.
- Added country-scoped central ESEF index routing for 26 observed country
  codes, with a separate 30-country ESMA OAM source matrix.
- Added `head(n)` / `latest(n)`, bounded source-ID listing lookup, document
  selection, extracted-text search with source links, and exact raw-fact filtering.
- Added market-scoped `search_companies()` for SEC ticker-list and Companies
  House public/API source results, returning source-linked issuer candidates
  without fetching a profile for every match.
- Replaced the inline XBRL tree parse with a bounded two-pass reader for
  reports up to 100 MB. Named 70.0 MB Iberdrola and 55.5 MB Swedbank XHTML
  reports now yield raw facts with original source locations. Sweden stops
  reading ZIP members after the first tagged report.
- EDINET now reads original package members through the shared bounded ZIP
  extractor, retaining the 50 MB classic XBRL limit while allowing inline
  XHTML up to 100 MB. A named Toyota filing still yielded 2,182 classic facts.
- Added ES CNMV annual-report access by issuer NIF with original PDF and ESEF
  ZIP links. A named annual ZIP, text and raw-fact path were checked live.
- Added opt-in SE Finanscentralen report tables by exact company registration
  number, grouped source-file language links and on-download format detection.
  A named Swedbank FY2024 ZIP, members, text and raw facts were checked live.
  Listing pagination and exact filing dates remain open.
- Added opt-in PL KNF OAM annual discovery by exact issuer name, native RR/SRR
  codes, receipt date, report year, correction flag and original ZIP. A named
  mBank source report yielded XHTML text and 733 raw inline facts.
- Added bounded inspection of nested ZIP and gzip-wrapped ZIP members while
  retaining original bytes and the full inner source path.
- Limited individual ZIP member extraction to 100 MB by default, with an
  explicit per-call override; original source ZIP download remains available.
- Added offline national-source fixtures and bounded live document/text/fact
  checks for FR, FI, PL, IS and LT. National OAM coverage beyond these routes
  and ES/SE remains open.
- Kept NO national NewsWeb access pending a separate agreement after review of
  its published rights notice; Norway's independent ESEF index route remains.

## 0.1.0 — 2026-10-07 (private source release)

- Added standalone package metadata and source-preserving public domain objects.
- Added a synchronous provider contract and one-document download path.
- Added on-demand inner-file enumeration and individual download for a selected
  original ZIP, with package URL and entry-path provenance.
- Added bounded HTTP retries, pacing and in-memory response reuse.
- Added direct SEC, Companies House, Open DART, EDINET and bounded FR/FI ESEF
  adapters with original source metadata and one-document access.
- Added keyless Companies House public-page access for individual filings,
  including report ZIP text and raw inline facts; an API key selects the
  authenticated REST/Document route.
- Added lightweight HTML/XHTML text, raw xBRL-JSON, classic XBRL instance and
  XML iXBRL tag facts where source documents support them. Inline display
  values retain transformation attributes without numeric conversion.
- Added offline cross-provider workflow checks and a Python 3.11–3.13 CI
  workflow for the standalone repository.
- One-filing live checks passed for US, UK, KR, JP, FR and FI, with raw-fact
  checks where available. The optional authenticated UK API route has offline
  tests; a local-key live smoke returned HTTP 401.
