# Provider and advanced workflow notes

This file holds the per-source detail, limits and dated measurements that moved
here from the README on 2026-10-09.

These details extend the [README quickstart](README.md#quickstart). In examples
below, `filing` is a filing selected through `Company.filings()` unless another
source is shown.

Contents:

- [Issuer lookup and filing selection](#issuer-lookup-and-filing-selection)
- [Documents, text, and facts](#documents-text-and-facts)
- [SEC sections and source navigation](#sec-sections-and-source-navigation)
- [PDF originals](#pdf-originals)
- [Core objects](#core-objects)
- [Full route matrix](#full-route-matrix)
- [Raw facts, text and tables: format conditions](#raw-facts-text-and-tables-format-conditions)
- [Transport, caching and limits](#transport-caching-and-limits)
- Per-source notes: [SEC](#sec), [Companies House](#companies-house),
  [EDINET](#edinet), [Open DART](#open-dart), [France OAM](#france-oam),
  [ESEF index](#esef-index),
  [Other national OAM routes (experimental)](#other-national-oam-routes-experimental)
- [Examples by market](#examples-by-market)
- [Command-line details](#command-line-details)
- [Benchmarks and live checks](#benchmarks-and-live-checks)

## Brazil CVM and Chile CMF

New in 1.1.0; both routes are experimental and require no API key.
[Brazil](docs/markets/br.md) resolves CVM codes/CNPJs, reads bounded IPE
delivery-year metadata and retrieves individual original PDFs. Its ten-second
default pacing observes the data host's crawl delay. This excludes DFP/ITR.
[Chile](docs/markets/cl.md) resolves active securities issuers by RUT, verifies
the public IFRS report selector's issuer/period/balance and retrieves PDF/XBRL
originals. No filing date is inferred from its query clock. Its signed links
may expire; reopen the company and select the report for fresh links.

Both support `search_companies`, streamed saves and direct composite-key
lookup. The cross-market `find_company` index includes active registrations from both
registers, refreshed weekly. Brazil retains CVM code, CNPJ and trade names;
Chile retains RUT/name. Browser search loads a separate ODbL Brazil directory.
The guides document composite IDs, source attribution and request bounds.

## Issuer lookup and filing selection

If you know a company name but not its regulator identifier, search within a
market first:

```python
from opencorpfilings import Company, search_companies

matches = search_companies("Apple", market="US", limit=5,
                           user_agent="Your Name contact@example.com")
company = Company(matches[0], user_agent="Your Name contact@example.com")
```

Passing the returned `Entity` keeps its source-scoped identifier, market,
provider route and search provenance. A string identifier still requires an
explicit `market`. Most candidates can be used for filing discovery directly.
SEC filing discovery fetches the submissions profile once when starting from
a ticker-list search result; the original search record remains on
`company.entity`, and `company.search_result` keeps the selected source
candidate and its provenance.

`search_companies()` currently supports Brazil CVM, Chile CMF, US SEC, UK Companies House, Korean Open DART,
Japanese EDINET, Polish KNF, Swedish Finanscentralen, French Info-Financiere,
Spanish CNMV, the Finnish Nasdaq OAM, the Netherlands AFM financial-reporting
register and Danish OAM. It
returns up to 100 source-listed `Entity` candidates with provider-scoped IDs,
source URLs and search-result provenance. SEC results come from the ticker
listing; UK results come from the public search page or authenticated search
API. The UK public route follows source pagination until it finds the requested
number of unique companies or reaches its 20-page safety bound. It returns
matches found within that bound even when fewer than requested, and retains
the actual search page URL on each result. Finnish search reads the source
issuer selector; Polish KNF
returns distinct issuer names from its first source report page and marks that
scope in each candidate's metadata. Spanish CNMV
searches its official issuer-name register; a unique match can lead directly
to a source detail page, while broader matches return NIF candidates. France
groups the official OAM's
issuer-name records by name and LEI; an exact name can be passed to `Company`,
which rejects names associated with multiple LEIs. Search results do not fetch
a profile for every candidate. A candidate is not a
full company profile: `Company(id, market=...)`
resolves that profile before listing filings. Other providers, including the
ESEF index, raise `UnsupportedCapabilityError` for entity search. An empty list
means no match was found in the queried source result, not that the issuer does
not exist.
For FI, `Company` accepts the exact source-listed name or OAM company ID.
For example, the Finnish OAM lists `Nokia` and `UPM-Kymmene`, without their
familiar company suffixes; `search_companies("Nokia", market="FI")` returns the
ID to pass to `Company`.

Korean-name and exact stock-code search uses DART's
[public company selector](https://dart.fss.or.kr/corp/searchCorp.ax), preserving
its issuer IDs, names, stock codes and source URL. Six-character stock codes
can contain letters. Exact eight-digit corporation-code search uses the
authenticated company profile. Pass any returned `entity_id` to `Company`.
For `Company("005930", market="KR")`, the selector's exact stock-code row is
verified against that profile. Changed selector markup falls back to the
[official Open DART corporation registry](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018).
English-name search first uses the [English DART company selector](https://englishdart.fss.or.kr/corp/searchCorp.ax).
An empty or changed selector result falls back to the registry for English
aliases. A live `Samsung Electronics` query returned four candidates in 1.13
seconds without loading the registry. Its `no-store` 3.62 MB response took
about 250 seconds to download in an earlier live check and is reused only
within the provider object's lifetime.
Japanese issuer search uses the [EDINET code list](https://disclosure2.edinet-fsa.go.jp/WEEK0020.aspx),
which supports Japanese and English names. It loaded in 1.73 seconds in a
named check. DART's selector is HTML rather than a versioned API, so its
behavior may change independently of Open DART's API.
Open DART filing rows are checked against the selected corporation code.
English `Semi-annual Report` and `Semiannual Report` titles are classified as
interim before annual-title matching; the raw source title stays on the
filing. The annual filter does not include those half-year reports.
`Company.get_filing(receipt)` uses a bounded listing scan for Korea because
the official filing-search API has date filters but no exact receipt lookup.

Use `collection.head(3)` or `collection.latest(3)` to inspect a few filing
records, `filing.select_document(media_type="application/zip")` to choose one
representation, and `filing.find_facts(concept_raw="...")` for exact
raw-concept occurrences. These operations never normalize accounting concepts.
For prose, read `document.text()` and use ordinary Python string or regular
expression search in the caller when needed.
For SEC date-filtered listing, the provider avoids older submission files
whose SEC-declared date range cannot contain a matching filing.
Exact SEC ticker lookup uses the SEC's smaller ticker/CIK text map and verifies
the ticker against the submissions profile. A miss, stale mapping, or ordinary
source failure falls back to the exchange JSON, with the fallback profile also
checked. Issuer search still
uses the exchange JSON for names and exchange labels.
Ticker resolution identifies the current SEC registrant. A corporate
reorganization can put older filings under another CIK: for example, current
`XOM` resolves to `0002115436`, while its predecessor's 2026 annual filing is
available with `Company("0000034088", market="US")`. The package does not
silently combine those entities. See the [source-backed example](BENCHMARKS.md).
On the same filing object, extracted text and raw fact parsing run once;
subsequent searches and fact filters reuse those results. `filing.facts`
returns a separate list on each access so list edits cannot alter the cache.
For SEC, `filing.primary_document`, `filing.text()` and `filing.download()`
use the primary filename already supplied by EDGAR submissions. They fetch
that one original without first listing the filing archive. Ask for
`filing.documents` when you need exhibits or all available files; the primary
object then gains the original index's description and type metadata.
`company.get_filing(source_id)` uses a verified direct source-record route when
the provider declares `direct_filing_lookup` (currently SEC accessions, Companies House with a valid REST API key, ESEF index record IDs, French Info-Financiere,
Netherlands AFM financial reporting and Danish OAM). Other
providers use a bounded listing scan (`max_scan=500` by default); pass
`start=`/`end=` to narrow that scan for older records. The date bounds also
apply to a direct result. The scan bound is passed to the provider before
discovery, so a recent ID does not force a full history traversal. A directly
retrieved filing supports the same
document, text and fact methods as a filing selected from a collection. For
an unfiltered collection, `company.filings().get(source_id)` uses the same
verified direct lookup when the provider supports it. A collection with a
form, date, amendment or result-limit filter uses its bounded listing scan so
the returned filing actually belongs to that selected collection. For keyless
Companies House access, this bounded
scan remains the available route; its public website has no individual
transaction metadata page. With an API key, `Company("00185647",
market="UK").get_filing("<transaction_id>")` requests one official filing
history item and validates its company and transaction link.
For SEC, an accession such as
`Company("320193", market="US").get_filing("0000320193-25-000079")` reads the
original EDGAR index page directly. It checks the CIK and source accession,
retains the page's form, filing date, period and primary document, and keeps
the displayed acceptance time raw because the page does not specify its time
zone. The accession prefix need not equal the issuer CIK: Microsoft's
`0001193125-26-323660` resolves under Microsoft CIK `0000789019`.
For SEC exhibits, `filing.select_document(document_type="EX-21.1")` chooses
the original file. `document.description` and
`document.provider_metadata["index_sequence"]` retain the filing index's
description and sequence. The adapter combines those typed rows with the full
archive directory, so generated files remain visible with no invented type.
The shared `select_document()` also accepts exact `document_id`, `language`,
and `description` filters alongside `document_type`, `filename`, and
`media_type`. Filters combine, so a caller can select an EDINET language and
document role or one SEC exhibit by its source ID and description. No filter
returns the primary original; multiple matches raise `ValueError`, while no
match raises `UnsupportedCapabilityError`. Selection reads document metadata
without downloading an original.
For France, use the source's `diffuser:UIN` key, for example
`Company("AB SCIENCE", market="FR").get_filing("432:628645_20260513")`.
The adapter checks the issuer LEI and reads that record directly.
French ZIP packages can contain tagged `.htm` or `.html` originals as well as
`.xhtml`; `filing.facts` exposes raw inline facts from the first tagged
report it can parse while preserving its archive path. It stops extracting ZIP
members once one tagged report yields facts.
For French ZIP members of at least 16 MB, fact parsing uses a temporary file
and leaves the member byte cache empty. A file-backed report may be up to 2 GB
when its compression ratio is plausible (Michelin's FY2025 XHTML exceeds
100 MB and yields 457 facts).
For the separate ESEF index, use its numeric record ID, for example
`Company("5299006UDSEJCTTEJS30", market="AT", source="esef_index").get_filing("24793")`
(Verbund's FY2025 English report, checked 2026-10-09).
The adapter fetches one index record and checks its LEI and country. The index
does not supply a regulator filing date, so `start=`/`end=` cannot filter this
direct result.

## Documents, text, and facts

`document.download()` and `filing.download()` return or save **one selected
document**. Passing a path saves those
original bytes to that path, replacing it only after the save completes.
`FilingCollection.download(directory, ...)` saves a bounded selection of one
company's filings (bounded by `filings(limit=...)`, `start=`/`end=`, or
`all_history=True`) with a resumable manifest; there is no multi-company bulk
download.
`filing.text()` and `filing.facts` are available
only where the selected source format and provider expose them; unsupported
operations raise `UnsupportedCapabilityError`.
Readable HTML/XHTML text omits iXBRL header metadata and explicitly hidden
HTML while retaining visible inline fact text. `download()` and `.html()`
still expose the original source, and `.facts` retains raw structured values.
`filing.html()` returns the selected original HTML/XHTML as a string when its
primary document has that format. On a ZIP, select an HTML/XHTML member and
call `member.html()`; `document.html()` works on a direct HTML/XHTML document.
These methods decode as UTF-8 by default and accept `encoding=` for another
known source encoding. Invalid bytes raise `UnicodeDecodeError`; use
`download()` for the unmodified source bytes.

```python
filing.download("annual-report.html")  # one primary source document
```

SEC, Companies House, the Finnish Nasdaq OAM, Netherlands AFM, Danish OAM,
Spanish CNMV, Swedish Finanscentralen and the ESEF index stream an individual
document to a temporary file in the destination directory, then replace it after a complete
response. This avoids holding that download in memory. A later byte read from
the same document object reuses the saved file after checking its SHA-256 hash.
`document.sha256()` exposes the hash of the selected original bytes. If the
document was saved through the streamed path, it verifies and hashes that local
file without buffering the package again. A fresh streamed original is hashed
through a temporary file that is removed after use; repeat calls reuse that
digest on the same object. Compare this value across national
and ESEF index documents only when both selected originals are the artifacts
you intend to compare; a matching LEI and period alone do not prove identity.
For KONE's FY2023 annual report, the Finnish OAM English ZIP matched ESEF
index record `12309` byte for byte in a live check; the Finnish-language ZIP
from the same publication day did not.
Saving that document again to a different path copies and verifies the local
file in chunks, without another source request or loading it into memory.
For a saved ZIP, listing and reading archive members also uses the verified
local file without loading the whole package into memory. One selected member
still has the documented extraction size limit.
Documents remain tied to their source URL from selection onward. Changing a
document object's URL, even before its first download, raises `DownloadError`
on content access rather than attributing bytes to a different source. Cached
bytes, saved copies, digests and derived content keep the same binding.
Cached filing facts and sections also check the filing URL and any selected
document URLs before they are returned.
SEC and Companies House also check selected PDF and ZIP signatures before
returning their bytes or replacing a saved target, so an HTML error response
with HTTP 200 is not treated as the original document.
All buffered selected PDF and ZIP originals receive a shared byte-signature
check before they enter the document cache or replace a target. ZIP originals
also need a readable archive directory on buffered reads and streamed saves;
this catches truncated archives without extracting every member. A source may
explicitly discover a different format, such as a CNMV PDF-labeled XHTML
report; the document then exposes that observed type and keeps the listed
type in provider metadata. CNMV validates a staged stream before replacing
the caller's target, including ZIP integrity and PDF/XHTML format discovery.
Finanscentralen discovers ZIP, PDF or XHTML from the staged source bytes and
checks a ZIP archive directory before replacing the target. Text and raw-fact
reads from a saved Swedish ZIP inspect its members without loading the original
package into the document byte cache.
The Finnish Nasdaq OAM checks ZIP/PDF signatures and ZIP archive structure;
the ESEF index checks a ZIP signature and its source SHA-256 when supplied.
France Info-Financiere and Poland KNF stream a
selected original to disk while retaining their source URL checks. ZIP saves
check the archive signature and directory before replacing the target; PDF
saves check the PDF signature. Text from their saved ZIPs reads members without
loading the original package into the document byte cache.
EDINET streams a selected source ZIP or PDF to a caller path. ZIP saves verify
every member's CRC before replacing the target; a source error or damaged ZIP
leaves an existing target intact. Providers without a streamed save path buffer
their selected document when their source needs format or response validation. `download()` without a path
returns bytes and therefore loads that one document into memory.
Open DART also streams one selected original or XBRL ZIP to a caller path,
checking every member's CRC and preserving the regulator's XML error status.
Status `800` reports a temporary Open DART maintenance outage.
It raises `SourceUnavailableError`, the same `ProviderError` subclass used
after bounded retries for HTTP 500, 502, 503 or 504. HTTP 429 remains
`RateLimitError`. Callers can catch `SourceUnavailableError` separately from
missing filings, unsupported formats and authentication failures.
After a ZIP has been saved, EDINET and Open DART read text directly from the
verified saved archive. Open DART also reads raw XBRL facts from a saved XBRL
ZIP without loading the whole source package back into memory.
For a saved direct HTML/XHTML original, `document.text()` verifies and reads
the file incrementally without retaining the original byte buffer. A direct
byte-returning `document.download()` still loads those bytes by request.
Sweden's inline-fact reader also uses a verified saved XHTML directly, or
extracts an uncached ZIP report member of at least 16 MB to a temporary file
for parsing. The original ZIP and selected report bytes stay uncached.
Package-only ESEF index records use that file-backed member path for raw
inline facts as well, retaining every report member's source location.
Companies House raw inline facts use a saved original XHTML or the selected
XHTML inside an accounts ZIP. Spanish CNMV annual raw facts likewise use the
selected report XHTML inside the saved ESEF ZIP. Large uncached members are
parsed through temporary files; original source URLs and member paths remain
attached to each fact.
The Finnish Nasdaq OAM adapter follows the
same rule and opens report members only until a tagged report yields facts.
Denmark, Netherlands and Poland also use the file-backed parser for selected
uncached XHTML/HTML members of at least 16 MB. Their provider-specific member
selection and fact provenance remain intact.

For a selected source ZIP, inspect and retrieve one file inside it:

```python
package = filing.primary_document
if package.media_type == "application/zip":
    for member in package.members:
        print(member.entry_path, member.source_location)
    one_file = package.members[0].download()
```

`FilingArchiveMember` keeps the original package URL and the exact inner path.
Listing members reads only that selected package. A saved package is opened
from its verified local file; otherwise the package bytes are reused for
individual member access. A nested ZIP or gzip-wrapped ZIP exposes `.members`
on the archive member, up to five member levels, with the full source path.
Member extraction is limited to 100 MB by default, including when a compressed
entry advertises a smaller size. Pass `member.download(max_bytes=...)` for a
different limit, or `max_bytes=None` explicitly for an unrestricted read.
`member.download(path)` extracts to a temporary file in bounded chunks and
replaces the destination only after extraction and ZIP CRC validation complete.
It does not retain the selected member in memory. A byte-returning
`member.download()` still caches that selected member on its object.
For HTML/XHTML entries, `member.text()` extracts readable text directly.
Members of at least 16 MB are streamed through a temporary file when their
bytes have not already been loaded; the source package and member need not be
retained in memory when the package was saved with `download(path)`.
Selected members stay bound to their original package URL and ZIP entry path.
Changing a member or parent source URL, or the selected entry path, raises
`DownloadError` before cached bytes or derived content can be returned.
The original ZIP remains accessible through `package.download()`.
For an ESEF index record with only a source ZIP, `filing.text()` joins text from
all report XHTML members and `filing.facts` preserves every inline fact
occurrence with its source member path. When the index supplies xBRL-JSON,
`filing.facts` uses that representation and keeps its JSON fact identifier.

## SEC sections and source navigation

SEC original HTML 10-Ks, 10-Qs and 8-Ks expose source-linked sections when their
Item boundaries can be verified against the original:

```python
for section in filing.sections():
    print(section.part, section.item, section.title, section.start_line, section.source_url)
    print(section.text[:200])
    for reference in section.references:
        print(reference.kind, reference.target, reference.source_line)

# For a 10-K:
item_8 = filing.section("Item 8")
print(item_8.text[:200], item_8.references)
# A jointly filed heading remains one section; any listed Item resolves to it.
item_11 = filing.section("11")
print(item_11.item, item_11.items)  # e.g. 10-13, ("10", "11", "12", "13")
for reference in item_8.references:
    source = reference.resolve(filing)  # a verified F-page or one original exhibit
    print(source.source_url)

# For a numbered annual-report page in a source-backed HTML sequence:
page = filing.primary_document.printed_page("38")
print(page.label, page.text, page.start_line, page.source_url)

# When a 10-K has only a terminal cross-reference index:
for reference in filing.section_references("Item 8"):
    target = reference.resolve(filing)
    pages = target if isinstance(target, tuple) else (target,)
    print(reference.kind, reference.source_text,
          [getattr(page, "label", getattr(page, "filename", None)) for page in pages])

# For an 8-K:
event = filing.section("Item 2.02")
print(event.title, event.text)
```

Each `FilingSection` includes the original document source and one-based line
positions in `filing.text()`. The first 10-K path matches contents titles to
body headings. If that fails, a source-only body-heading path requires at
least 15 ordered Items from Item 1 through Item 15 or 16 and checks every
heading against the extracted source line. This path does not follow Item
pointers into exhibits or financial pages after the signature. Source headings
inside table cells can qualify when their text and line positions match;
adjacent rows of a page-reference index do not count as body sections.
An explicit leading Item 8 pointer to a page such as `F-3` or an exhibit such
as `EX-13` is returned as a `FilingSectionReference` with the filed line,
document ID, URL and provenance. `section.text` remains the source's contiguous
Item span. `reference.resolve(filing)` returns an enumerated original exhibit
or a `FilingPrintedPage` when the HTML's page breaks and consecutive F-page
footers verify the printed page. A page result retains its original text-line
span; ambiguous or unmarked layouts raise `UnsupportedCapabilityError`.
Direct `printed_page(label)` accepts an `F-` label or a decimal label when
consecutive `Annual Report` or `Form 10-K` footers with the same title align
with HTML page breaks. The decimal number may precede or follow the title,
or occupy an adjacent footer line. It returns source page text and line positions, not an inferred Item
section. McDonald's 2025 10-K has an index pointing Item 8 to page 38, but
that page begins with material from an earlier topic; `filing.sections()`
still fails closed on its index-only Item labels. `section_references(item)`
returns the explicit page pointer from a sufficiently complete, ordered
terminal index when its target belongs to a verified numbered-page run.
An inline `36-73` range has `kind="page_range"`; its `resolve(filing)` result
is a tuple of verified `FilingPrintedPage` objects. A filed comma list
returns separate references, preserving the full source row and line.
For ordinary 10-K Items it returns their existing references. It does not
assemble Item content or resolve proxy incorporation. On one document object, the
first successful page lookup caches the verified footer run; later page labels
and `reference.resolve(filing)` reuse it without rescanning the HTML.
GE's 2025 original verified a 76-page `Form 10-K` run despite changing footer
order. Its inline index returns Item 8's filed 36-73 range and Item 7A's
separate page 13 and 68-69 range. Cardinal Health's fiscal 2026 original
verified an 89-page run with separate title and number lines; its split-cell
Item index returns verified start-page references through `section_references(item)`.
A 10-K contents list used by the first path
must reach Item 15 or 16; a 10-Q must include both Part I (through Item 4)
and Part II (through Item 6). The 10-Q `part` field distinguishes repeated
Item numbers, and its spans exclude the Part II transition and signature.
Select one with `filing.section("1", part="II")`; omitting `part` for a repeated
Item raises `ValueError`, and a missing Item raises `KeyError`.
The final 10-K Item also stops at an explicit source signature heading.
For an 8-K, the Item number and caption must match the first words of the
[SEC Form 8-K caption](https://www.sec.gov/files/form8-k.pdf). The returned
title is the original filing text. The last Item ends before a visible
`SIGNATURE` or `SIGNATURES` line. A table of contents with its own Item and
signature rows qualifies only when its codes and captions match later body
headings; the returned spans start at those body headings. An 8-K with
ambiguous or absent boundaries raises `UnsupportedCapabilityError`; `8-K/A`
is not claimed.
The matcher accepts a 10-Q contents title on the Item line, a body title on
the next line, and an annual numeric Item/title/page table when each title
matches one body heading. For 10-Ks, a unique body heading may differ from its
contents title by regular singular/plural endings or an added `and`; other
words must remain in order. Each contents title must identify one body
heading. For a 10-K body heading, a short decimal list prefix immediately before `Item` is
accepted only when the filed contents code and title verify that body line.
A bold body heading that explicitly lists consecutive Items is returned once,
with a range label such as `item="10-13"` and `items=("10", "11", "12", "13")`.
`filing.section("11")` returns that same shared section. Its title, text and
line range remain those of the filed group; no individual boundaries are
invented. Nonconsecutive, overlapping, unbolded or table-only group candidates
remain unsupported.
For an unlabelled
10-Q Item, a unique contents link in that Item's row must point to an empty
body anchor. A repeated 10-Q body heading can be disambiguated when the
same-row contents link points to one matching heading paragraph. Contents
matched sections follow contents order; source-only 10-K sections follow body
order. Their line positions can differ
from that order when the source places items elsewhere in the document, and
an anchor-delimited section need not begin with an Item heading. Unsupported
forms, formats and ambiguous filings raise `UnsupportedCapabilityError`.
The SEC provider's `sections` capability applies to qualifying originals,
not every SEC filing. Other providers do not declare it.
An amended 10-K/A, 10-Q/A or 8-K/A may contain only changed Items. Section
navigation currently requires an original; the error points to
`company.filings(form="annual", include_amendments=False).latest()` for an
annual original. This filter is explicit because `latest()` otherwise includes
amendments.

For a qualifying terminal 10-K cross-reference index, `filing.section_references(item)`
returns filed page pointers rather than complete Item sections. Inline ranges
resolve to each verified printed page. Cardinal Health's fiscal 2026 index
places Item, title and start page in separate cells; Items 1, 7, 8, 10 and 15
resolve to pages 25, 3, 50, 83 and 84 with the original page line attached.
The split-cell reader accepts a contiguous run of identical index headings and
does not limit an as-filed title by character count. It still requires an
ordered Item chain and independently verified printed-page targets.
`N/A` rows and proxy incorporation remain visible as source material; no Item
end boundary is inferred from the next listed page.

HTML/XHTML documents expose their literal table tags without assigning
financial meaning or expanding merged cells:

```python
for table in filing.tables():  # when the primary document is HTML/XHTML
    print(table.index, table.caption)
    print([[cell.text for cell in row] for row in table.rows])

# For a ZIP, select the original report member first:
report = next(m for m in package.members if m.entry_path.endswith(".xhtml"))
original_html = report.html()
tables = report.tables()
```

`FilingDocument.tables()` and `FilingArchiveMember.tables()` use the same
`FilingTable`/`FilingTableCell` objects. Each cell keeps its original `td`/`th`
tag and raw `rowspan`/`colspan` attributes; rows are not padded or aligned.
The source URL, full archive path and one-based table index remain attached.
`#table=N` in `source_location` is a library position, not a browser anchor.
Parsing is limited to 100 MB and cached on that document/member object.
Table decoding honors a UTF byte-order mark or declared XML/HTML charset,
then defaults to strict UTF-8. For unlabelled legacy HTML, pass a known
encoding such as `report.tables(encoding="cp949")`; an undecodable source
raises `ParseError` instead of silently replacing original-language text.
An XHTML report built from positioned `div` elements can have no `<table>`
tags, in which case this returns an empty list. PDFs and ZIP containers require
their own supported representation; this method does not infer tables from
visual layout.

For an optional Markdown view of one HTML/XHTML source, install
`opencorpfilings[markdown]` and call `filing.markdown()`,
`document.markdown()` or `report.markdown()` on a selected XHTML archive
member. Visible headings, emphasis and literal tables are retained where the
source markup expresses them. Hidden iXBRL metadata and embedded image data
URIs are omitted; image alt text remains. Original source bytes are available
through `download()`. PDF and ZIP containers do not claim Markdown support;
select an HTML/XHTML representation or archive member first.

## PDF originals

Install the optional PDF parser with `pip install '.[pdf]'` from the
source checkout. A selected PDF with a text layer then exposes original page
numbers and source links:

```python
pdf = filing.select_document(media_type="application/pdf")
for page in pdf.pages:
    print(page.number, page.source_location, page.text[:80])
```

`pdf.text()` joins the extracted page text. Image-only or scanned pages without
a text layer remain empty; this library does not run OCR. PDF extraction is
limited to 50 MB source files, 2,000 pages and 10 MB decoded page content.
The original document remains downloadable when text extraction cannot run.

## Core objects

- `Company` resolves a string identifier **within an explicit market**, or
  accepts an `Entity` from `search_companies()` directly. The latter preserves
  the source route and search result. A candidate whose source ID is not yet
  filing-ready is resolved on first use; `company.search_result` retains its
  original provenance. Tickers are not assumed globally unique.
- `Entity` preserves provider-scoped identity and original identifiers.
- `search_companies()` discovers source-listed candidates where a provider
  supports market-scoped search; the result keeps the original search record.
  The common API enforces `limit` and checks each returned candidate's market,
  provider and source provenance before handing it to `Company`.
- `FilingCollection` applies supported filters and yields newest records in
  its documented `order_basis`. `filings(limit=n)` yields at most `n` records,
  with the bound applied both at the provider and in the common collection.
  Date bounds accept ISO dates, Python `date` objects or the calendar date of a
  Python `datetime`; direct filing lookup uses the same provider-defined source
  date for those bounds.
  Listing and direct lookup verify each filing's issuer, market and provider
  before exposing it; source index and filing URLs can still differ.
  `filings(form=..., start=..., end=...).get(source_id)` uses direct lookup
  when the provider offers it, checking those filters on the returned record.
  `filings(limit=n).get(source_id)` checks membership within the bounded
  listing instead.
- `Filing` exposes raw type/title, conservative convenience category, source
  dates, the report period where the source states it (`period_end`: SEC
  report date, Companies House "made up to" date, EDINET and ESEF period end,
  Open DART report month; France's OAM supplies no period, so it stays `None`),
  original metadata and provenance. The category is one of `ANNUAL`,
  `QUARTERLY`, `INTERIM`, `CURRENT`, `PROSPECTUS`, `OWNERSHIP`, `OTHER`, or
  `None` when the source cannot justify one. Verified SEC 10-K/10-Q/8-K Item spans are
  available through `.sections()` where the original supports them. SEC 10-K
  `.section_references("Item 8")` exposes source-linked page or exhibit pointers;
  a filed page range resolves to an ordered tuple of verified pages. Split-cell
  index rows can expose verified start pages. A pointer does not assert
  complete Item content.
- `FilingDocument` identifies one original representation and retrieves its
  bytes. Its `role` says what it is within the filing: `report` (the filed
  report or its package), `exhibit`, `annex`, `announcement`, `data` (XBRL
  instances, schemas, xBRL-JSON), `generated` (source-system indexes and
  renderings, such as EDGAR's `R*.htm` and full-submission `.txt`) or `other`.
  `primary_document` is the one source-flagged document, otherwise the
  `report` role, then package/XHTML over PDF over HTML. Document enumeration and primary-document lookup verify the selected
  filing ID, provider, market and original URL provenance before binding the
  provider. Its `document_type` and optional `description` retain source labels.
  Text extraction is conditional. PDFs expose `FilingPage` records
  with original page numbers when the optional parser is installed. ZIP packages expose individual
  `FilingArchiveMember` records through `.members`. HTML/XHTML documents and
  selected archive members expose literal `FilingTable` rows and `FilingTableCell`
  source attributes through `.tables()`. Optional `.markdown()` is available
  for selected HTML/XHTML sources. Saved direct originals and large archive
  members use a verified file for Markdown parsing without filling the
  original-byte cache; Markdown still builds an in-memory text tree.
- `FilingFact` holds an original structured fact occurrence, including its raw
  concept, value, unit, context/dimensions and source location when available.
  Facts are checked against the selected filing's provider and market before
  caching; their source URLs retain the actual document or derived source.
  `filing.find_facts()` filters exact raw concept, period start/end, unit,
  context ID and taxonomy, plus specified dimension members. `limit=` bounds
  returned occurrences without changing or normalizing the underlying facts.

`filing.text()` reads available source text, `filing.facts` returns raw tagged
facts when present, and `filing.primary_document.download(path)` saves one
original. Each result keeps the regulator URL and original metadata. Use
`filing.documents` to inspect available originals, then
`filing.select_document(document_id=...)` to choose one exact source ID.
Selection can also filter by `document_type`, `filename`, `media_type`,
`language`, or `description`; an ambiguous match raises instead of guessing.
Document and archive-member lists can be filtered or edited locally without
changing the filing's cached source enumeration.

If you supply a provider object, its declared market must match `market=`.
The caller owns that provider's connection: leaving a `Company` context does
not close it, so the same provider can be reused for another company. A
`Company` that creates its own provider closes it on context exit.

## Full route matrix

Inspect the configured route without credentials or network access:

```python
from opencorpfilings import provider_info, supported_markets

print(supported_markets())
route = provider_info("JP")
print(route.tier, route.identifiers, route.forms, route.date_filters, route.auth)
print(provider_info("IT", source="esef_index").coverage_note)
```

Each route declares a **tier**: `supported` (US, UK, JP, FR: qualified on
fresh issuers), `limited` (the ESEF index: useful history, documented gaps)
or `experimental` (everything else). Its profile names the identifiers it
resolves, the `form=` categories it can select, whether exact native forms
and date filters work, and the credentials it needs. `Company.filings()`
checks a request against that profile before contacting the source, so an
unservable form, a date filter on a dateless source, or a category typo
fails at once with the allowed values. `ocf markets` prints every route's
profile as JSON. An unknown market code raises `UnsupportedMarketError`
(also a `ValueError`) with a hint such as `GB` → `UK`.

`supported_markets()` includes countries served only by the bounded ESEF
index. Declared capabilities describe a provider route; a particular filing
may have fewer formats or no raw facts. The table below records those source
differences in more detail for every route that exists. The eleven national
routes retired on 2026-10-09 have no rows; see
[Retired national routes](#other-national-oam-routes-experimental).

| Market | Lookup | Filing selection | Original formats | Text | Raw facts | Auth |
|---|---|---|---|---|---|---|
| US SEC | ticker or CIK | form/date, newest filing first; direct accession lookup | HTML, typed exhibits with index descriptions, other archive files, original instance XML where filed | HTML/plain text | original XBRL instance or XML iXBRL tags when present | identifying User-Agent |
| UK Companies House | company number or exact name | filing history; annual selects filed accounts | public PDF/XHTML/ZIP; API document representations with a key | XHTML and report XHTML inside ZIP | raw inline tags in XHTML or report ZIP | none for public pages; API key optional |
| KR Open DART | stock or corporation code; official registry name/code search | form/date, receipts and amendments | original disclosure ZIP; periodic XBRL ZIP when available | original XML/HTML | classic XBRL instance when present | API key |
| JP EDINET | securities or EDINET code; official registry Japanese/English name/code search | bounded daily discovery, form/source file date | native ZIP, PDF, attachments, English and CSV when flagged | HTML inside original/English ZIP | classic XBRL or XML iXBRL tags when present | API key |
| FR Info-Financiere OAM | LEI or exact source name; source-name search | source publication order; annual 003000 including secondary source classification on a registration document, half-year 004000, quarterly information 005000/005001/005002; date filters pushed to source; direct diffuser:UIN lookup | original PDF/ZIP/XHTML as linked, including ZIP bytes under `.xbri` | HTML/XHTML, including report inside ZIP; PDF text when extractable | raw inline tags where present | none |
| FI OAM | exact OAM company name or numeric company ID; source-name search | source publication order; annual 270 and interim 78/153; five-year default search window and 20-page safety bound | original ZIP/PDF/XHTML attachments | HTML/XHTML, including report inside ZIP; PDF text when extractable | raw inline tags where present | none |
| ES CNMV OAM | issuer NIF; official issuer-name search | annual and interim registers, publication-date filter, five-year default lookup window | annual financial-report links/ESEF ZIP; interim original PDFs, annexes and XBRL XML | XHTML directly or inside ZIP; PDF pages when text is extractable | raw inline tags from annual XHTML and raw classic XBRL from interim XML | none |
| SE Finanscentralen OAM | company registration number; source-name search via result pages or direct company detail | paginated annual/interim/quarterly report rows; period-label order; no exact date filter | original file links; ZIP/PDF/XHTML detected on download | XHTML inside ZIP or original XHTML | inline tags in XHTML under 100 MB parser bound | none |
| PL KNF OAM | exact source issuer name; first-page source-name search | source receipt-date order; verified RR/SRR/SRR-I annual codes; 20-page default scan bound | original KNF ZIP with nested `.rap` and gzip-wrapped ESEF ZIP | report XHTML inside nested ESEF package | raw inline tags in report XHTML where present | none |
| NL AFM OAM | exact register issuer name; source-name search | annual and half-yearly register categories, filing-date order, bounded issuer metadata | individual original `.xbri`/ZIP/PDF files | report XHTML inside ZIP; PDF text when available | inline tags in XHTML where present | none |
| DK Danish FSA OAM | listed source business ID or exact issuer name; source-name search accepts ASCII Danish spellings | native annual/half-yearly categories, publication order, bounded pages | individual original ZIP/PDF/HTML/TXT links | report XHTML inside ZIP or HTML; PDF text when available | inline tags in XHTML where present | none |
| 21 country-scoped ESEF index routes (limited) | LEI | report-period order, preferred language first; `form="annual"`; direct numeric record lookup; no filing-date filter | indexed XHTML, source ZIP, derived xBRL-JSON where indexed | indexed XHTML or report XHTML inside source ZIP | xBRL-JSON when present; otherwise original inline tags when present | none |
| HK | pending authorized access | pending | pending | pending | pending | route unresolved |

## Raw facts, text and tables: format conditions

An advertised raw-fact capability is conditional on the selected filing's
actual format. Inline facts expose the displayed lexical value and original
`format`/`scale`/`sign` attributes; they do not apply XBRL transformations.
The raw parser rejects duplicate context, unit or inline-continuation IDs
instead of silently assigning a fact to whichever duplicate appeared last.
Raw unit labels preserve XBRL structure: sibling measures join with `*`, and
only an explicit unit numerator/denominator joins with `/`. No unit conversion
or accounting mapping is performed.
Fact values stay the filed strings, such as `9 480,6` in a French report:
they are not converted to numbers.

The classic XBRL reader makes two incremental passes over direct XML children:
it collects source contexts, units and prefixes before emitting raw facts in
document order. It does not retain the full XML element tree.
A named Toyota original package
still yielded 2,182 classic raw facts after this change.

Page-linked PDF text is available with the optional `pdf` extra when the
original document has a text layer. For a long PDF, use
`document.page(1)` to extract one one-based `FilingPage` without extracting
every page. The same document object reuses that page. After a streamed
`download(path)`, PDF page and text extraction reads the SHA-256-verified saved
file without retaining the original PDF bytes in the document object.
HTML access also reads a verified saved original directly. Large uncached
HTML/XHTML ZIP members are extracted to a temporary file for `.html()`, so the
member bytes are not retained after the decoded string is returned.
Literal `.tables()` also parses a verified saved HTML/XHTML original or a large
uncached ZIP member from a file, preserving source table structure and the
100 MB inspection bound without retaining the original bytes.
`document.pages` and `document.text()` extract all pages. Invalid page
numbers raise `ValueError` or `IndexError`.
This does not imply reliable table
structure or OCR. Non-XML inline reports remain outside the current parser
capability.

## Transport, caching and limits

An explicit `api_key=` takes precedence, followed by the
`OPENCORPFILINGS_*` name and then the shorter name. Providers also accept
`user_agent=` where applicable. OpenCorpFilings makes bounded
requests with timeouts, retries, `Retry-After` handling and pacing.
Transient HTTP 500/502/503/504 responses use bounded retries and raise
`SourceUnavailableError` if exhausted; HTTP 429 raises `RateLimitError`.
An empty HTTP 200 body is rejected when downloading one original document;
failed path saves leave the previous target in place.
Successful GET responses up to 2 MB are reused in memory for up to five
minutes, shortened by the source's freshness limit. Concurrent readers share
an atomic in-memory cache lookup; a concurrent miss may still make more than
one source request. To reuse those responses
across separate processes, opt into a local cache:

```python
company = Company("AAPL", market="US", cache_dir="~/.cache/opencorpfilings")
```

`search_companies(..., cache_dir=...)` accepts the same option. Alternatively,
set `OPENCORPFILINGS_CACHE_DIR` for default provider transports. The cache
stores at most 128 response files, uses a checksum for each entry, and keeps
request credentials out of filenames. It honors source `no-store`, `no-cache`,
`max-age`, `Age` and `Expires` instructions. Client-level auth, cookie sessions
and redirects that set a cookie are excluded when the sent request could differ
from the cache key. The cache
does not store client-authenticated or cookie-backed pages, POST forms, or
streamed document saves.
Transport error messages show the source origin and failure type/status without
echoing request paths, query parameters or client exception text that may
contain credentials.
The library reads process environment variables; it does not load `.env` files
automatically. Respect each regulator's usage terms.

## Per-source notes

### SEC

SEC requests need `OPENCORPFILINGS_SEC_USER_AGENT` containing an identifying name
and contact, or `user_agent=` (`--user-agent` on the command line).
SEC original XBRL and inline XHTML documents saved with `download(path)` are
parsed from the verified saved file without filling the document byte cache.
Ticker lookup, accession lookup and exhibits are covered under
[Issuer lookup and filing selection](#issuer-lookup-and-filing-selection);
Item sections under [SEC sections and source navigation](#sec-sections-and-source-navigation).

### Companies House

Companies House uses public filing pages by default; set
`OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY` to use its authenticated REST and Document
APIs instead. The public-page route skips rows without a document link because
those rows do not expose a source transaction ID in the page markup.
Companies House public pages currently send `no-store`, so the local response
cache does not reuse them.

### EDINET

EDINET uses `OPENCORPFILINGS_EDINET_API_KEY` or `EDINET_API_KEY`.
EDINET's API accepts one source day per request. Discovery keeps up to four
daily metadata requests in flight, paces their dispatch with the default
transport's 0.2-second interval, and consumes every day in descending order. It
defaults to a 550-day lookback. Pass `start=` and `end=` to bound it further:
measured live, Toyota's latest annual took 27.5 s and its half-year report,
filed 330 days earlier, 92 s. `period_end` is the report's own period: EDINET's
period fields give the fiscal year, so a half-year report (160/170) ends six
months after the fiscal year starts, and a quarterly report (140/150) has none.
For Japan, those bounds and `latest()` follow EDINET's source file date;
`collection.order_basis` is `"source_file_date"`. The document's submission
date remains `filing.filing_date`, and its source file date is retained as
`filing.provider_metadata["source_file_date"]`. They can differ for a
backdated paper or disk submission, so a narrow file-date window is not a
complete submission-date search.
The daily response can repeat a document ID for a later administrative
correction or disclosure event. Those event rows are excluded from filing
results; the original day's row retains the updated source metadata. A filing
whose current source status prevents access can still have no documents.
EDINET reads original ZIP members through the shared bounded extractor:
classic XBRL instance members retain a 50 MB parse limit, while inline XHTML
members use the inline reader (100 MB in memory, up to 2 GB from a file). Uncached
members of at least 16 MB are parsed from a temporary file, leaving their
uncompressed byte cache empty.

EDINET's daily lists arrive with `Cache-Control: no-cache`,
so the transport never reuses them; the EDINET provider instead keeps the 90
most recently read past JST days in memory, which lets an annual and then an
interim lookup in one session share recent days. A cold lookback still
requests each source day.

### Open DART

Open DART uses `OPENCORPFILINGS_DART_API_KEY` or the existing `OPENDART_API_KEY`
name. Issuer search and receipt lookup are covered under
[Issuer lookup and filing selection](#issuer-lookup-and-filing-selection);
streamed saves and maintenance status `800` under
[Documents, text, and facts](#documents-text-and-facts).

### France OAM

France's OAM accepts `form="annual"`, `form="interim"` and
`form="quarterly"` using [DILA's native codes](https://echanges.dila.gouv.fr/OPENDATA/AMF/0%20Presentation%20et%20documentation%20flux%20AMF/Notices_relatives_au_Flux_AMF_20210120.pdf):
`003000`, `004000`, and `005000`/`005001`/`005002`, respectively. A caller can
also request one exact raw code. Date bounds are applied by the source API
before paging. AB SCIENCE's named 2025 half-year record and MILIBOO's named
2026 first-quarter information record supplied original PDFs. The quarterly
category can contain a revenue update rather than full accounts; the source
title and raw code remain available. Code `002003` is an availability notice,
so it is left unclassified in unfiltered results.

### ESEF index

The [ESMA directory](https://www.esma.europa.eu/publications-and-data/databases-and-registers)
lists 30 national OAM country routes, with two operators for Italy. This library
currently has seven national OAM adapters: FR, FI, ES, SE, PL, NL and DK.
Their national routes are the market defaults. The separate `filings.xbrl.org` index route (tier **limited**) finds
ESEF annual reports by LEI in 21 countries; the country list, the 2026-10-08
removals and the dated freshness table are in the
[README](README.md#the-esef-index-limited). Select the index with
`source="esef_index"` where a national adapter exists; it is the default for
indexed countries without one.

Use it for multi-year iXBRL history, not for a company's latest report. It is
a secondary index that lags the regulators by months and is incomplete.
Filings are ordered by report period (`order_basis="report_period"`), newest
first, with the preferred language first within a period (English by default;
`ESEFProvider(market=..., prefer_language="it")` changes it). Each record is
typed `ESEF`/`ANNUAL` because ESEF tagging is mandated for annual financial
reports; `form="annual"` is accepted and other forms, date filters and
amendment filters are refused. `index_added_at` is when the index received
the record; there is no regulator filing date. Discovery reads at most 20
index pages per issuer (`max_pages=` widens it) and raises if more are needed.

The ESEF central index is a secondary, incomplete index. Its LEI-only lookup
and index-order results do not claim national OAM coverage in any country.

An original ESEF index ZIP is checked against the index's SHA-256 when that
hash is present. One selected source ZIP in each of the 26 markets indexed at
the time of that check (before CZ, CY, RO, LV and PL were dropped on
2026-10-08) passed issuer resolution, filing selection, archive opening and
checksum comparison. The same selected filings each yielded text and raw
facts, totaling 14,047,617 extracted characters and 12,876 facts. These
one-record checks do not establish national OAM coverage, source-text fidelity
or accounting parity.
A selected 51,231,666-byte Belgian index ZIP also passed `download(path)`
with source SHA-256 verification before target replacement and no retained
document-byte buffer.

Norway remains an index-only route in this package. NewsWeb's source terms
reserve non-private downloading and storage to separately authorized users;
an automated national adapter is pending an appropriate access agreement.

### Other national OAM routes (experimental)

The national OAM routes for ES, NL, DK, SE, PL and FI are tier
**experimental**. See the
[country-by-country source matrix](EUROPE_SOURCES.md) for national portals.
The named examples below do not measure national coverage.

**Spain (CNMV).**
The CNMV national route needs a source NIF. `form="annual"` and
`form="interim"` use separate official registers; an unfiltered listing merges
both by publication date. The selected interim detail page supplies exact
period dates and original PDF/XML links on demand. Iberdrola interim report
`2026103709` exposed four original documents, including an XBRL XML instance
with 1,110 raw facts. The named Iberdrola FY2024 annual ZIP was
downloaded; its 70.0 MB XHTML yielded 833 raw inline facts. The two-pass
inline reader keeps source locations; it caps bytes in memory at 100 MB and a
file-backed report at 2 GB (2026-10-08).

**Sweden (Finanscentralen).**
The Swedish report table gives a year/month label, not an exact report-end or
publication date. The national adapter therefore preserves the label in
`provider_metadata`, leaves those dates unset, and orders by the visible label.
Issuer-name search returns source registration numbers from the public result
table, following its next-page control up to a configurable 20-page bound.
Report-table pages are fetched when the requested result count or a selected
period at a page boundary needs them;
the default bound is 20 pages per report type (`max_report_pages` can be raised
to 100). Separate source rows for the same period can carry different languages;
these become documents of one period filing when their language labels do not
conflict, even when the rows span pages. Ambiguous same-language repeats fail explicitly. Correction history
is not classified. Source files do not declare a filename/format in
the table, so `.download()` detects ZIP, PDF or XHTML and updates the document.
The named Swedbank FY2024 ZIP yielded 10 members and readable XHTML. Its
55.5 MB Swedish report yielded 551 raw inline facts. The adapter reads only
the first tagged report needed for a filing's `facts` result.

**Poland (KNF).**
The Polish national route uses an exact OAM issuer name and scans at most 20
search pages by default; increase `max_pages` on `PolandOAMProvider` for an
older report. The KNF record supplies a receipt date, local receipt time,
report year and correction flag. Its report year is not converted into an exact
period end. The named mBank `SRR` annual package contained a nested `.rap` and
gzip-wrapped ESEF ZIP; the original bytes, text and 733 raw inline facts were
retrieved. The source's launch descriptor points to the original ZIP and is
retained in document metadata.

**Finland (Nasdaq OAM).**
Finnish OAM search
defaults to the past five calendar years; pass `start=` for earlier notices.
Finland also accepts `form="interim"` through its native Nasdaq OAM
categories: 78 is a half-year report and 153 includes interim reports and
financial statement releases. The adapter
merges category results by source publication time and reads later pages only
when needed. Each record retains its exact source label and category ID.
The named recent interim record for KONE supplied an original PDF; its file
format alone does not imply structured facts.

The other national routes (NL, DK) are described by their matrix rows above
and the lookup and document notes earlier in this file.

**Retired national routes.** The Iceland, Lithuania, Latvia, Croatia, Romania,
Slovakia, Estonia, Malta, Cyprus, Hungary and Liechtenstein national routes
were retired on 2026-10-09 and their code removed. For HR, EE, HU, IS, LT, MT and SK,
`market=<code>` now uses the ESEF index route by LEI. CY, RO, LV and LI have
no route.

## Examples by market

The same collection workflow on each route. Korea and Japan require source API
keys; see [EDINET](#edinet) and [Open DART](#open-dart).

```python
from opencorpfilings import Company

Company("00185647", market="UK").filings(form="annual").latest()
Company("005930", market="KR").filings(form="annual").latest()
Company("060310", market="KR").filings(form="annual").latest()
Company("7203", market="JP").filings(form="annual").latest()
Company("KONE Oyj", market="FI").filings(form="annual").latest()
Company("969500U43TVR8CCVBJ97", market="FR").filings(form="annual").latest()
Company("A-48010615", market="ES").filings(form="annual").latest()
Company("502017-7753", market="SE").filings(form="annual").latest()
Company("mBank Spółka Akcyjna", market="PL").filings(form="annual").latest()
Company("ASML Holding N.V.", market="NL").filings(form="annual").latest()
Company("DK-61056416", market="DK").filings(form="annual").latest()

# The independent central index is an explicit alternative by LEI.
Company("2138001CNF45JP5XZK38", market="FI", source="esef_index").filings().latest()
Company("959800M75M81U0Y2UX24", market="ES", source="esef_index").filings().latest()
```

Run [the one-filing example](examples/one_filing.py) with `--market US`,
`UK`, `KR`, `JP`, `FI`, `FR`, `ES`, `SE`, `PL`, `NL` or `DK` for an optional live source check. It retrieves
one filing and one selected original document; regular tests use offline
fixtures.

## Command-line details

The optional `ocf` command uses the same API. It searches source-listed
issuers, inspects one company, lists a small set of filings, or saves one
selected original document:

```bash
ocf search KONE --market FI --limit 5
ocf filings 552 --market FI --form annual --limit 1
ocf company 00185647 --market UK
ocf filings 00185647 --market UK --form annual --limit 3
ocf documents 00185647 --market UK --form annual --latest
ocf download 00185647 --market UK --form annual --latest --output annual.zip
ocf filings AAPL --market US --form annual --limit 3 --user-agent "Your Name contact@example.com"
```

The commands emit JSON, retain source URLs, and respect the same market and
source routing as `Company`. Search results include the source-scoped issuer
ID, search provenance and whether the candidate needs further resolution;
`552` in the example is the source-listed KONE ID. `ocf download` selects one document from one
filing; `ocf documents` lists that filing's documents, with the
`filename` and `document_type` values `download` selects by, without
downloading them. `ocf download` refuses to replace an existing file unless `--overwrite` is given;
use `--filing-id` to select an exact source filing instead of `--latest`.
For SEC commands, pass an identifying `--user-agent` for that invocation or
set `OPENCORPFILINGS_SEC_USER_AGENT` in the environment. The option applies only
to the US SEC route.
The per-company download equivalent of
`Company("00502851", market="UK").filings(form="annual", limit=5).download("greggs/")`
is `ocf download 00502851 --market UK --form annual --limit 5
--output-dir greggs/`. There is no multi-company download.

## Benchmarks and live checks

The [single-filing SEC benchmarks](BENCHMARKS.md) compare annual and quarterly
workflows with EdgarTools on named filings, recording timing and text coverage.
It is a live observation, not a speed claim.
The bounded [metadata coverage probe](benchmarks/coverage_probe.py) reports
issuer, latest-filing and document-link outcomes for up to 20 named issuers
without downloading original files.
