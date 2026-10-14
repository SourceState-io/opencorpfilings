"""On-demand EDGAR submissions and individual filing documents."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from bs4 import BeautifulSoup

from ..errors import AmbiguousEntityError, AuthenticationError, DownloadError, EntityNotFoundError, FilingNotFoundError, ParseError, ProviderError, RateLimitError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, FilingFact, FilingSection, Identifier, Provenance
from ..provider import FilingProvider
from ..raw_xbrl import parse_ixbrl_xhtml, parse_xbrl_instance
from ..sec_sections import sec_10k_sections, sec_10q_sections, sec_8k_sections
from ..transport import HttpTransport


_DATA = "https://data.sec.gov"
_WWW = "https://www.sec.gov"
# 10-K405, 10-KSB, 10-KSB40 and 10-KT405 were annual forms before 2009; 10-QSB quarterly.
_ANNUAL = {"10-K", "20-F", "40-F", "10-KT", "10-K405", "10-KSB", "10-KSB40", "10-KT405"}
_QUARTERLY = {"10-Q", "10-QT", "10-QSB"}
_CURRENT = {"8-K", "6-K"}
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}\Z")
_DOCUMENT_SIGNATURES = {"application/pdf": (b"%PDF-", "PDF"),
                        "application/zip": (b"PK\x03\x04", "ZIP")}


def _form_category(raw: str) -> str:
    base = raw.removesuffix("/A")
    if base in _ANNUAL:
        return "ANNUAL"
    if base in _QUARTERLY:
        return "QUARTERLY"
    if base in _CURRENT:
        return "CURRENT"
    if base.startswith(("S-1", "F-1", "424B")):
        return "PROSPECTUS"
    # Schedules 13D and 13G are filed as "SCHEDULE 13D"/"SCHEDULE 13G" since December 2024.
    if base in {"3", "4", "5", "SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G"}:
        return "OWNERSHIP"
    return "OTHER"


def _form_matches(raw: str, requested: str | None) -> bool:
    if requested is None:
        return True
    category = _form_category(raw)
    if requested in {"annual", "quarterly", "current", "prospectus", "ownership", "other"}:
        return category.lower() == requested
    if requested == "interim":
        return category == "QUARTERLY"
    return raw.casefold() == requested.casefold()


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _rows(columns: dict[str, list[Any]]) -> Iterator[dict[str, Any]]:
    for index in range(len(columns.get("accessionNumber", []))):
        yield {key: values[index] if index < len(values) else None for key, values in columns.items()}


_GENERATED = re.compile(
    r"(?:R\d+\.htm|FilingSummary\.xml|MetaLinks\.json|Financial_Report\.xlsx|report\.css|Show\.js"
    r"|\d{10}-\d{2}-\d{6}(?:-index(?:-headers)?\.html?|\.txt|-xbrl\.zip))",
    re.IGNORECASE,
)
_XBRL_DATA = re.compile(r"(?:\.xsd|_(?:cal|def|lab|pre|htm)\.xml)$", re.IGNORECASE)


def _document_role(filename: str, index_type: str | None, *, primary: str | None, form: str | None) -> str:
    """Classify an EDGAR folder file: the filed report, an exhibit, XBRL data, or an EDGAR-generated file.

    Without a primary filename, the index row typed as the filing's own form is the report.
    """
    kind = (index_type or "").upper()
    if (filename == primary) if primary else (bool(kind) and kind == (form or "").upper()):
        return "report"
    if kind.startswith("EX-101") or _XBRL_DATA.search(filename):
        return "data"
    if kind.startswith("EX-"):
        return "exhibit"
    if _GENERATED.fullmatch(filename):
        return "generated"
    return "other"


def _media_type(filename: str) -> str | None:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "htm": "text/html", "html": "text/html", "txt": "text/plain", "xml": "application/xml",
        "xsd": "application/xml", "pdf": "application/pdf", "json": "application/json",
        "zip": "application/zip",
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    }.get(suffix)


def _index_documents(soup: BeautifulSoup) -> dict[str, dict[str, str]]:
    """Read raw document roles from the EDGAR filing index tables."""
    documents = {}
    for row in soup.select("table.tableFile tr"):
        cells = row.select("td")
        if len(cells) < 4:
            continue
        link = cells[2].select_one("a")
        filename = link.get_text(" ", strip=True) if link is not None and not _rendered(link) else ""
        if not filename or "/" in filename or "\\" in filename:
            continue
        documents[filename] = {
            "index_sequence": cells[0].get_text(" ", strip=True),
            "index_description": cells[1].get_text(" ", strip=True),
            "index_type": cells[3].get_text(" ", strip=True),
        }
    return documents


def _rendered(link) -> bool:
    """A link to SEC's XSL rendering of a filed XML form, not to a filed document."""
    return "/xsl" in (link.get("href") or "")


def _filed_primary(name: Any) -> Any:
    """The filed document behind a submissions `primaryDocument`, which names SEC's rendered view
    (`xslF345X05/form4.xml`) for ownership and other XML forms."""
    if isinstance(name, str) and name.startswith("xsl") and name.count("/") == 1:
        return name.split("/", 1)[1]
    return name


class SECProvider(FilingProvider):
    name = "sec"
    market = "US"
    regulator = "US Securities and Exchange Commission"
    identifies_amendments = True
    tier = "supported"
    identifier_kinds = ("ticker", "CIK")
    forms = ("annual", "quarterly", "interim", "current", "prospectus", "ownership", "other")
    auth = "required identifying User-Agent: user_agent= or OPENCORPFILINGS_SEC_USER_AGENT"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "direct_filing_lookup", "document_download", "streamed_download", "html", "text", "xbrl", "ixbrl", "raw_facts", "sections", "printed_pages"})

    def filing_matches_form(self, filing: Filing, requested: str) -> bool:
        return _form_matches(filing.filing_type_raw or "", requested)

    def __init__(self, *, user_agent: str | None = None, transport: HttpTransport | None = None) -> None:
        identity = user_agent or os.getenv("OPENCORPFILINGS_SEC_USER_AGENT")
        if not identity:
            raise AuthenticationError(
                "SEC requests require an identifying User-Agent. Set OPENCORPFILINGS_SEC_USER_AGENT "
                "to your organization/name and contact email, or pass user_agent=."
            )
        self.transport = transport or HttpTransport(user_agent=identity, min_interval=0.12, pace_key="sec.gov")
        self.transport.user_agent = identity
        self._searched_profile: tuple[str, dict[str, Any]] | None = None

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        url = f"{_WWW}/files/company_tickers_exchange.json"
        listings = self.transport.get_json(url)
        fields = listings.get("fields", [])
        needle = query.casefold()
        from ..directory import _tokens

        query_tokens = _tokens(query)
        matches = []
        for values in listings.get("data", []):
            row = dict(zip(fields, values))
            name = str(row.get("name", ""))
            ticker = str(row.get("ticker", ""))
            if not ticker or not name or "cik" not in row:
                continue
            ticker_key, name_key = ticker.casefold(), name.casefold()
            if needle not in ticker_key and needle not in name_key:
                continue
            # The company named by the query ("Apple" -> "Apple Inc.") ranks right after an exact ticker.
            rank = (0 if ticker_key == needle else 1 if query_tokens and _tokens(name) == query_tokens
                    else 2 if ticker_key.startswith(needle) else 3 if name_key.startswith(needle) else 4)
            matches.append((rank, len(name_key), name_key, ticker_key, row))
        results = []
        seen: set[str] = set()
        for *_, row in sorted(matches, key=lambda match: match[:4]):
            cik = str(row["cik"]).zfill(10)
            if cik in seen:
                continue
            seen.add(cik)
            ticker = str(row["ticker"])
            source_url = f"{_WWW}/edgar/browse/?CIK={int(cik)}"
            results.append(Entity(
                entity_id=cik, name=str(row["name"]), jurisdiction="US", provider=self.name,
                source_url=source_url,
                identifiers=(Identifier("CIK", cik, url), Identifier("ticker", ticker, url)),
                tickers=(ticker,), exchanges=(str(row.get("exchange", "")),) if row.get("exchange") else (),
                provider_metadata=row,
                provenance=Provenance(self.name, self.regulator, "US", url, cik, datetime.now(timezone.utc), row),
            ))
            if len(results) >= limit:
                break
        return results

    def resolve_entity(self, identifier: str) -> Entity:
        identifier = identifier.strip()
        by_ticker = not (identifier.isdecimal() and len(identifier) <= 10)
        used_exchange = False
        if not by_ticker:
            cik = identifier.zfill(10)
        else:
            try:
                ticker_rows = self.transport.get(f"{_WWW}/include/ticker.txt").decode("utf-8")
                ciks: set[str] = set()
                for line in ticker_rows.splitlines():
                    ticker, separator, raw_cik = line.partition("\t")
                    if (separator and ticker.casefold() == identifier.casefold()
                            and re.fullmatch(r"[0-9]{1,10}", raw_cik)):
                        ciks.add(raw_cik.zfill(10))
            except RateLimitError:
                raise
            except (ProviderError, UnicodeDecodeError):
                ciks = set()
            if not ciks:
                ciks = self._exchange_ticker_ciks(identifier)
                used_exchange = True
            if not ciks:
                raise EntityNotFoundError(f"SEC ticker {identifier!r} was not found")
            if len(ciks) > 1:
                raise AmbiguousEntityError(f"SEC ticker {identifier!r} maps to multiple CIKs; use a CIK")
            cik = next(iter(ciks))
        try:
            payload = self._submissions_profile(cik)
        except EntityNotFoundError:
            if not by_ticker or used_exchange:
                raise
            ciks = self._exchange_ticker_ciks(identifier)
            used_exchange = True
            if len(ciks) > 1:
                raise AmbiguousEntityError(f"SEC ticker {identifier!r} maps to multiple CIKs; use a CIK")
            if not ciks or cik in ciks:
                raise EntityNotFoundError(f"SEC ticker {identifier!r} has no current submissions profile")
            cik = next(iter(ciks))
            payload = self._submissions_profile(cik)
        tickers = tuple(str(ticker) for ticker in payload.get("tickers", []))
        if by_ticker and identifier.casefold() not in {ticker.casefold() for ticker in tickers}:
            if not used_exchange:
                ciks = self._exchange_ticker_ciks(identifier)
                if len(ciks) > 1:
                    raise AmbiguousEntityError(f"SEC ticker {identifier!r} maps to multiple CIKs; use a CIK")
                if ciks and cik not in ciks:
                    cik = next(iter(ciks))
                    payload = self._submissions_profile(cik)
                    tickers = tuple(str(ticker) for ticker in payload.get("tickers", []))
            if identifier.casefold() not in {ticker.casefold() for ticker in tickers}:
                raise EntityNotFoundError(f"SEC ticker {identifier!r} does not match the current submissions profile")
        url = f"{_DATA}/submissions/CIK{cik}.json"
        exchanges = tuple(str(exchange) for exchange in payload.get("exchanges", []))
        source_url = f"{_WWW}/edgar/browse/?CIK={int(cik)}"
        identifiers = [Identifier("CIK", cik, url)]
        identifiers.extend(Identifier("ticker", ticker, source_url) for ticker in tickers)
        return Entity(
            entity_id=cik, name=payload.get("name", ""), jurisdiction="US", provider=self.name,
            source_url=source_url, identifiers=tuple(identifiers), tickers=tickers, exchanges=exchanges,
            provider_metadata=payload,
            provenance=Provenance(self.name, self.regulator, "US", url, cik, datetime.now(timezone.utc), payload),
        )

    def _submissions_profile(self, cik: str) -> dict[str, Any]:
        try:
            return self.transport.get_json(f"{_DATA}/submissions/CIK{cik}.json")
        except ProviderError as exc:
            if "HTTP 404" in str(exc):
                raise EntityNotFoundError(f"SEC CIK {cik} was not found") from exc
            raise

    def _exchange_ticker_ciks(self, identifier: str) -> set[str]:
        listings = self.transport.get_json(f"{_WWW}/files/company_tickers_exchange.json")
        fields = listings.get("fields", [])
        return {
            str(row["cik"]).zfill(10)
            for values in listings.get("data", [])
            if (row := dict(zip(fields, values))).get("cik") is not None
            and str(row.get("ticker", "")).casefold() == identifier.casefold()
        }

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        """Read one accession's original EDGAR index without scanning submission pages."""
        if entity.jurisdiction != "US" or entity.provider != self.name:
            raise ValueError("entity is not from SEC EDGAR")
        if not _ACCESSION.fullmatch(filing_id):
            raise ValueError("SEC accession must have the form 0000000000-00-000000")
        folder = f"{_WWW}/Archives/edgar/data/{int(entity.entity_id)}/{filing_id.replace('-', '')}"
        url = f"{folder}/{filing_id}-index.htm"
        try:
            soup = BeautifulSoup(self.transport.get(url), "html.parser")
        except ProviderError as exc:
            if "HTTP 404" in str(exc):
                raise FilingNotFoundError(f"SEC accession {filing_id} was not found") from exc
            raise
        header = soup.select_one("#formHeader")
        form = soup.select_one("#formName strong")
        cik_links = soup.select('.companyInfo a[href*="CIK="]')
        if header is None or form is None or not cik_links:
            raise ParseError(f"SEC accession {filing_id} index lacks filing identity")
        if f"SEC Accession No. {filing_id}" not in header.get_text(" ", strip=True):
            raise ParseError(f"SEC accession {filing_id} index has another accession number")
        # A combined filing lists every co-registrant; the company may be any of them.
        ciks = {match.group(1) for link in cik_links
                if (match := re.match(r"\s*(\d{10})\b", link.get_text(" ", strip=True)))}
        if entity.entity_id not in ciks:
            raise FilingNotFoundError(f"SEC accession {filing_id} belongs to another company (CIK)")
        form_display = form.get_text(" ", strip=True)
        if not form_display.startswith("Form "):
            raise ParseError(f"SEC accession {filing_id} index lacks a form type")
        raw_form = form_display.removeprefix("Form ")
        fields = {}
        for group in soup.select(".formGrouping"):
            heads, values = group.select(".infoHead"), group.select(".info")
            if len(heads) != len(values):
                raise ParseError(f"SEC accession {filing_id} index has incomplete filing metadata")
            fields.update((head.get_text(" ", strip=True), value.get_text(" ", strip=True))
                          for head, value in zip(heads, values))
        try:
            filed = date.fromisoformat(fields["Filing Date"])
            period_end = _parse_date(fields.get("Period of Report"))
        except (KeyError, ValueError) as exc:
            raise ParseError(f"SEC accession {filing_id} index lacks a valid filing date or period") from exc
        index_documents = _index_documents(soup)
        filename = next((name for name, row in index_documents.items() if row["index_type"] == raw_form), None)
        if filename is None:
            raise ParseError(f"SEC accession {filing_id} index lacks a valid primary document")
        raw = {"archive_base_url": folder, "primaryDocument": filename,
               "form_display": form_display, "accepted_display": fields.get("Accepted"),
               "index_fields": fields, "index_documents": index_documents}
        return Filing(
            filing_id=filing_id, entity_id=entity.entity_id, jurisdiction="US", provider=self.name,
            regulator=self.regulator, source_url=url,
            provenance=Provenance(self.name, self.regulator, "US", url, filing_id,
                                  datetime.now(timezone.utc), raw),
            filing_type_raw=raw_form, filing_type_normalized=_form_category(raw_form),
            filing_date=filed, period_end=period_end, amendment=raw_form.endswith("/A"),
            provider_metadata=raw, _provider=self,
        )

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True, limit: int | None = None,
    ) -> Iterator[Filing]:
        payload = entity.provider_metadata
        if "filings" not in payload:
            cached = self._searched_profile
            if cached is not None and cached[0] == entity.entity_id:
                payload = cached[1]
            else:
                payload = self._submissions_profile(entity.entity_id)
                if str(payload.get("cik", "")).zfill(10) != entity.entity_id:
                    raise ProviderError(f"SEC submissions profile does not match CIK {entity.entity_id}")
                self._searched_profile = (entity.entity_id, payload)
        filing_set = payload.get("filings", {})
        sources = [filing_set.get("recent", {})]
        # SEC's recent array contains at least a year/1,000 filings. Older slices are loaded only
        # if the caller iterates past them; no bulk archive is downloaded.
        older = sorted(filing_set.get("files", []), key=lambda item: item.get("filingTo", ""), reverse=True)
        count = 0
        for source in sources + older:
            if isinstance(source, dict) and "name" in source:
                if start and source.get("filingTo"):
                    try:
                        if date.fromisoformat(source["filingTo"]) < start:
                            continue
                    except (TypeError, ValueError):
                        pass  # Unknown date range: read the source rather than lose filings.
                if end and source.get("filingFrom"):
                    try:
                        if date.fromisoformat(source["filingFrom"]) > end:
                            continue
                    except (TypeError, ValueError):
                        pass
                source = self.transport.get_json(f"{_DATA}/submissions/{source['name']}")
            for row in _rows(source):
                raw = row.get("form") or ""
                filed = _parse_date(row.get("filingDate"))
                if not include_amendments and raw.endswith("/A"):
                    continue
                if not _form_matches(raw, form) or (start and filed and filed < start) or (end and filed and filed > end):
                    continue
                accession = row["accessionNumber"]
                folder = f"{_WWW}/Archives/edgar/data/{int(entity.entity_id)}/{accession.replace('-', '')}"
                index_url = f"{folder}/{accession}-index.htm"
                row_meta = {**row, "archive_base_url": folder,
                            "primaryDocument": _filed_primary(row.get("primaryDocument"))}
                filing = Filing(
                    filing_id=accession, entity_id=entity.entity_id, jurisdiction="US", provider=self.name,
                    regulator=self.regulator, source_url=index_url,
                    provenance=Provenance(self.name, self.regulator, "US", index_url, accession, datetime.now(timezone.utc), row),
                    filing_type_raw=raw, filing_type_normalized=_form_category(raw),
                    filing_date=filed, published_at=_parse_timestamp(row.get("acceptanceDateTime")),
                    period_end=_parse_date(row.get("reportDate")), amendment=raw.endswith("/A"),
                    provider_metadata=row_meta, _provider=self,
                )
                yield filing
                count += 1
                if limit is not None and count >= limit:
                    return

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        folder = filing.provider_metadata["archive_base_url"]
        listing = self.transport.get_json(f"{folder}/index.json")
        if "index_documents" in filing.provider_metadata:
            index_documents = filing.provider_metadata["index_documents"]
        else:
            try:
                index_documents = _index_documents(BeautifulSoup(self.transport.get(filing.source_url), "html.parser"))
            except ProviderError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                index_documents = {}
        primary = filing.provider_metadata.get("primaryDocument")
        documents = []
        for item in listing.get("directory", {}).get("item", []):
            filename = item.get("name", "")
            if not filename or item.get("type") == "directory" or "/" in filename or "\\" in filename:
                continue
            url = f"{folder}/{filename}"
            index_row = index_documents.get(filename, {})
            metadata = {**item, **index_row}
            documents.append(FilingDocument(
                document_id=f"{filing.filing_id}:{filename}", filing_id=filing.filing_id,
                filename=filename, source_url=url,
                provenance=Provenance(self.name, self.regulator, "US", url, filename, datetime.now(timezone.utc), metadata),
                media_type=_media_type(filename), document_type=index_row.get("index_type") or (filing.filing_type_raw if filename == primary else None),
                is_primary=filename == primary, provider_metadata=metadata,
                description=index_row.get("index_description") or None,
                role=_document_role(filename, index_row.get("index_type"), primary=primary,
                                    form=filing.filing_type_raw), _provider=self,
            ))
        if primary and not any(document.filename == primary for document in documents):
            url = f"{folder}/{primary}"
            index_row = index_documents.get(primary, {})
            documents.insert(0, FilingDocument(
                document_id=f"{filing.filing_id}:{primary}", filing_id=filing.filing_id,
                filename=primary, source_url=url,
                provenance=Provenance(self.name, self.regulator, "US", url, primary,
                                      raw=index_row),
                media_type=_media_type(primary), document_type=index_row.get("index_type") or filing.filing_type_raw,
                is_primary=True, provider_metadata=index_row,
                description=index_row.get("index_description") or None, role="report", _provider=self,
            ))
        return documents

    def get_primary_document(self, filing: Filing) -> FilingDocument | None:
        filename = filing.provider_metadata.get("primaryDocument")
        if not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename:
            return None
        folder = filing.provider_metadata["archive_base_url"]
        url = f"{folder}/{filename}"
        index_row = filing.provider_metadata.get("index_documents", {}).get(filename, {})
        return FilingDocument(
            document_id=f"{filing.filing_id}:{filename}", filing_id=filing.filing_id,
            filename=filename, source_url=url,
            provenance=Provenance(self.name, self.regulator, "US", url, filename,
                                  datetime.now(timezone.utc), index_row or {"primaryDocument": filename}),
            media_type=_media_type(filename),
            document_type=index_row.get("index_type") or filing.filing_type_raw,
            is_primary=True, provider_metadata=index_row,
            description=index_row.get("index_description") or None, role="report", _provider=self,
        )

    def download_document(self, document: FilingDocument) -> bytes:
        content = self.transport.get(document.source_url)
        signature = _DOCUMENT_SIGNATURES.get(document.media_type)
        if signature is not None and not content.startswith(signature[0]):
            raise DownloadError(f"SEC returned an unexpected {signature[1]} document for {document.source_url}")
        return content

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        signature = _DOCUMENT_SIGNATURES.get(document.media_type)
        return self.transport.get_to_file(
            document.source_url, path,
            expected_prefix=signature[0] if signature is not None else None,
        )

    def extract_text(self, document: FilingDocument) -> str:
        if document.media_type == "text/plain":
            return document.download().decode("utf-8", errors="replace")
        if document.media_type == "text/html":
            return document._html_text()
        raise UnsupportedCapabilityError(f"SEC text extraction does not support {document.media_type or document.filename}")

    def extract_sections(self, filing: Filing) -> list[FilingSection]:
        if filing.filing_type_raw in {"10-K/A", "10-Q/A", "8-K/A"}:
            raise UnsupportedCapabilityError(
                f"SEC {filing.filing_type_raw} amendments may contain only changed Items; "
                f"to navigate the original filing, use company.filings(form='{filing.filing_type_raw[:-2]}', "
                "include_amendments=False).latest()"
            )
        if filing.filing_type_raw == "10-K":
            return sec_10k_sections(filing.primary_document)
        if filing.filing_type_raw == "10-Q":
            return sec_10q_sections(filing.primary_document)
        if filing.filing_type_raw == "8-K":
            return sec_8k_sections(filing.primary_document)
        raise UnsupportedCapabilityError("SEC verified section boundaries currently require an original 10-K, 10-Q or 8-K")

    def raw_facts(self, filing: Filing) -> list[FilingFact]:
        flags = filing.provider_metadata
        if flags.get("isXBRL") == 0 and flags.get("isInlineXBRL") == 0:
            raise UnsupportedCapabilityError(f"SEC filing {filing.filing_id} has no XBRL, by its submissions record")

        def priority(document: FilingDocument) -> tuple[int, str]:
            name = document.filename.lower()
            if document.document_type == "EX-101.INS":
                return (0, name)
            return (0 if name.endswith("_htm.xml") else 1 if name.endswith("_ins.xml") else 2, name)

        excluded = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")
        candidates = sorted(
            (document for document in filing.documents
             if document.filename.lower().endswith(".xml")
             and not document.filename.lower().endswith(excluded)
             and document.filename.lower() != "filingsummary.xml"),
            key=priority,
        )
        for document in candidates:
            try:
                with document._parse_content() as content:
                    return parse_xbrl_instance(
                        content, document_url=document.source_url,
                        entry_path=document.filename, provider=self.name, regulator=self.regulator,
                        jurisdiction="US", filing_id=filing.filing_id,
                    )
            except ParseError as exc:
                if "is not an XBRL instance" not in str(exc):
                    raise
        for document in filing.documents:
            if document.media_type not in {"text/html", "application/xhtml+xml"}:
                continue
            try:
                with document._parse_content() as content:
                    facts = parse_ixbrl_xhtml(
                        content, document_url=document.source_url,
                        entry_path=document.filename, provider=self.name, regulator=self.regulator,
                        jurisdiction="US", filing_id=filing.filing_id,
                    )
            except ParseError as exc:
                if "invalid iXBRL XHTML" not in str(exc):
                    raise
                continue
            if facts:
                return facts
        raise UnsupportedCapabilityError(
            f"SEC filing {filing.filing_id} has no original XBRL instance or readable XML iXBRL tags"
        )
