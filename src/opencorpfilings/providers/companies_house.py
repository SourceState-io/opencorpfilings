"""On-demand Companies House public pages or authenticated REST/Document APIs."""

from __future__ import annotations

import base64
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from ..errors import (
    AmbiguousEntityError, EntityNotFoundError, FilingNotFoundError, ParseError,
    ProviderError, UnsupportedCapabilityError,
)
from ..models import _BINARY_PREFIXES, Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..packages import best_reports
from ..raw_xbrl import parse_ixbrl_xhtml
from ..transport import HttpTransport


_API = "https://api.company-information.service.gov.uk"
_DOC = "https://document-api.company-information.service.gov.uk"
_SITE = "https://find-and-update.company-information.service.gov.uk"
_NUMBER = re.compile(r"(?:\d{8}|[A-Z]{2}\d{6})\Z")
_SITE_DOCUMENT = re.compile(r"/company/[^/]+/filing-history/([^/]+)/document\Z")
_EXTENSIONS = {
    "application/xhtml+xml": "xhtml", "application/xml": "xml", "application/pdf": "pdf",
    "application/json": "json", "application/zip": "zip", "text/csv": "csv",
}
_FILED_ACCOUNTS_TYPES = {"AA", "AAMD", "AA02"}


def _company_number(identifier: str) -> str:
    """A company number as the register writes it: an all-digit number is zero-padded to 8."""
    number = identifier.strip().upper()
    return number.zfill(8) if number.isdecimal() and len(number) < 8 else number


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


_MADE_UP_TO = re.compile(r"made up to (\d{1,2} [A-Za-z]+ \d{4})")


def _made_up_to(item: dict[str, Any]) -> date | None:
    """Accounts period end: the API's made_up_date, or the public page's "made up to" text."""
    values = item.get("description_values")
    if isinstance(values, dict) and values.get("made_up_date"):
        return date.fromisoformat(str(values["made_up_date"]))
    match = _MADE_UP_TO.search(str(item.get("description", "")))
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%d %B %Y").date()
    except ValueError:
        return None


def _category(item: dict[str, Any]) -> str:
    # Companies House also places reference-date changes (AA01) in the accounts
    # category. Those are not annual accounts filings.
    if item.get("category") == "accounts" and item.get("type", "").upper() in _FILED_ACCOUNTS_TYPES:
        return "ANNUAL"
    return "OTHER"


def _matches(item: dict[str, Any], form: str | None) -> bool:
    if not form:
        return True
    if form == "annual":
        return _category(item) == "ANNUAL"
    if form in {"quarterly", "interim", "current", "other"}:
        return _category(item).lower() == form
    return str(item.get("type", "")).casefold() == form.casefold()


class CompaniesHouseProvider(FilingProvider):
    name = "companies_house"
    market = "UK"
    regulator = "Companies House"
    identifies_amendments = True
    tier = "supported"
    identifier_kinds = ("company number", "exact company name")
    forms = ("annual", "other")
    auth = "optional API key: OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY (public pages otherwise)"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download", "streamed_download", "pdf", "html", "text", "ixbrl", "raw_facts"})

    def __init__(self, *, api_key: str | None = None, transport: HttpTransport | None = None) -> None:
        key = api_key or os.getenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY")
        self._headers = {"Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode()} if key else {}
        self._public_site = not bool(key)
        self.capabilities = type(self).capabilities | (
            frozenset() if self._public_site else frozenset({"direct_filing_lookup"})
        )
        self.transport = transport or HttpTransport(min_interval=0.51)

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        if self._public_site:
            url = f"{_SITE}/search?{urlencode({'q': query})}"
            raw_items = []
            page_url = url
            seen_pages: set[str] = set()
            seen_numbers: set[str] = set()
            for _ in range(20):
                if page_url in seen_pages:
                    raise ProviderError("Companies House public search repeated a search page")
                seen_pages.add(page_url)
                page = self._page(page_url)
                for link in page.select('a[href^="/company/"]'):
                    match = re.fullmatch(r"/company/([A-Za-z0-9]{8})", link.get("href", ""))
                    if not match:
                        continue
                    number = match.group(1).upper()
                    name = link.get_text(" ", strip=True)
                    if not _NUMBER.fullmatch(number) or not name or number in seen_numbers:
                        continue
                    seen_numbers.add(number)
                    raw_items.append({
                        "title": name, "company_number": number,
                        "source": "public_website", "search_url": page_url,
                    })
                    if len(raw_items) >= limit:
                        break
                if len(raw_items) >= limit:
                    break
                next_link = next((link.get("href") for link in page.select("a[href]")
                                  if link.get_text(" ", strip=True) == "Next page"), None)
                if not next_link:
                    break
                next_url = urljoin(_SITE, next_link)
                parsed = urlparse(next_url)
                if (parsed.scheme != "https" or parsed.netloc != urlparse(_SITE).netloc
                        or parsed.path != "/search" or parse_qs(parsed.query).get("q") != [query]):
                    raise ProviderError("Companies House public search points to an unexpected search page")
                page_url = next_url
            else:
                if not raw_items:
                    raise UnsupportedCapabilityError("Companies House public search reached 20 pages; narrow the query")
        else:
            url = f"{_API}/search/companies?{urlencode({'q': query, 'items_per_page': limit})}"
            raw_items = self._json(f"{_API}/search/companies", params={"q": query, "items_per_page": limit}).get("items", [])
        results = []
        seen: set[str] = set()
        for item in raw_items:
            number = str(item.get("company_number", "")).upper()
            name = str(item.get("title", "")).strip()
            if not _NUMBER.fullmatch(number) or not name or number in seen:
                continue
            seen.add(number)
            source_url = f"{_SITE}/company/{number}"
            search_url = item.get("search_url", url)
            results.append(Entity(
                entity_id=number, name=name, jurisdiction="UK", provider=self.name,
                source_url=source_url, identifiers=(Identifier("company_number", number, source_url),),
                provider_metadata=item,
                provenance=Provenance(self.name, self.regulator, "UK", search_url, number, datetime.now(timezone.utc), item),
            ))
            if len(results) >= limit:
                break
        return results

    def _json(self, url: str, **kwargs: Any) -> Any:
        return self.transport.get_json(url, headers=self._headers, **kwargs)

    def resolve_entity(self, identifier: str) -> Entity:
        if self._public_site:
            return self._resolve_entity_public(identifier)
        identifier = identifier.strip()
        number = _company_number(identifier)
        if not _NUMBER.fullmatch(number):
            search = self._json(f"{_API}/search/companies", params={"q": identifier, "items_per_page": 100})
            matches = [item for item in search.get("items", []) if item.get("title", "").casefold() == identifier.casefold()]
            if not matches:
                raise EntityNotFoundError(
                    f"Companies House name {identifier!r} has no exact match; use a company number"
                )
            numbers = {item["company_number"] for item in matches}
            if len(numbers) > 1:
                raise AmbiguousEntityError(
                    f"Companies House name {identifier!r} matches multiple companies; use a company number"
                )
            number = next(iter(numbers))
        url = f"{_API}/company/{number}"
        try:
            profile = self._json(url)
        except ProviderError as exc:
            if "HTTP 404" in str(exc):
                raise EntityNotFoundError(f"Companies House number {number!r} was not found") from exc
            raise
        number = profile.get("company_number", number)
        source_url = f"https://find-and-update.company-information.service.gov.uk/company/{number}"
        return Entity(
            entity_id=number, name=profile.get("company_name", ""), jurisdiction="UK", provider=self.name,
            source_url=source_url, identifiers=(Identifier("company_number", number, url),),
            provider_metadata=profile,
            provenance=Provenance(self.name, self.regulator, "UK", url, number, datetime.now(timezone.utc), profile),
        )

    def _page(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.transport.get(url), "html.parser")

    def _resolve_entity_public(self, identifier: str) -> Entity:
        identifier = identifier.strip()
        number = _company_number(identifier)
        if not _NUMBER.fullmatch(number):
            search = self._page(f"{_SITE}/search?{urlencode({'q': identifier})}")
            numbers = {
                match.group(1).upper()
                for link in search.select('a[href^="/company/"]')
                if link.get_text(" ", strip=True).casefold() == identifier.casefold()
                if (match := re.fullmatch(r"/company/([A-Za-z0-9]{8})", link.get("href", "")))
            }
            if not numbers:
                raise EntityNotFoundError(f"Companies House name {identifier!r} has no exact match; use a company number")
            if len(numbers) > 1:
                raise AmbiguousEntityError(f"Companies House name {identifier!r} matches multiple companies; use a company number")
            number = next(iter(numbers))
        url = f"{_SITE}/company/{number}"
        try:
            page = self._page(url)
        except ProviderError as exc:
            if "HTTP 404" in str(exc):
                raise EntityNotFoundError(f"Companies House number {number!r} was not found") from exc
            raise
        heading = page.select_one("h1.heading-xlarge")
        if heading is None:
            raise ProviderError(f"Companies House public profile lacks a company heading for {number}")
        name = heading.get_text(" ", strip=True)
        raw = {"source": "public_website", "company_number": number, "company_name": name}
        return Entity(
            entity_id=number, name=name, jurisdiction="UK", provider=self.name,
            source_url=url, identifiers=(Identifier("company_number", number, url),),
            provider_metadata=raw,
            provenance=Provenance(self.name, self.regulator, "UK", url, number, datetime.now(timezone.utc), raw),
        )

    def _api_filing(self, entity: Entity, item: dict[str, Any]) -> Filing:
        transaction = str(item["transaction_id"])
        raw_link = item.get("links", {}).get("self")
        source_url = f"{_API}{raw_link}" if raw_link and raw_link.startswith("/") else (
            raw_link or f"{_API}/company/{entity.entity_id}/filing-history/{transaction}"
        )
        description = str(item.get("description", ""))
        form = str(item.get("type", ""))
        amended = form.upper().endswith("AMD") or "amend" in description.lower()
        return Filing(
            filing_id=transaction, entity_id=entity.entity_id, jurisdiction="UK", provider=self.name,
            regulator=self.regulator, source_url=source_url,
            provenance=Provenance(self.name, self.regulator, "UK", source_url, transaction,
                                  datetime.now(timezone.utc), item),
            filing_type_raw=form, filing_type_normalized=_category(item),
            title=description, filing_date=_date(item.get("date")), amendment=amended,
            period_end=_made_up_to(item), provider_metadata=item, _provider=self,
        )

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        if self._public_site:
            raise UnsupportedCapabilityError("Companies House keyless pages have no direct filing-ID route")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", filing_id):
            raise ValueError("invalid Companies House transaction ID")
        path = f"/company/{entity.entity_id}/filing-history/{filing_id}"
        try:
            item = self._json(f"{_API}{path}")
        except ProviderError as exc:
            if "HTTP 404" in str(exc):
                raise FilingNotFoundError(f"Companies House filing {filing_id!r} was not found") from exc
            raise
        if not isinstance(item, dict) or item.get("transaction_id") != filing_id:
            raise ParseError("Companies House direct filing returned a mismatched transaction")
        source_link = item.get("links", {}).get("self")
        if source_link:
            parsed_link = urlparse(source_link)
            if parsed_link.path != path or (parsed_link.netloc and parsed_link.netloc != urlparse(_API).netloc):
                raise ParseError("Companies House direct filing returned a mismatched company or transaction link")
        return self._api_filing(entity, item)

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True, limit: int | None = None,
    ) -> Iterator[Filing]:
        if self._public_site:
            yield from self._iter_filings_public(
                entity, form=form, start=start, end=end,
                include_amendments=include_amendments, limit=limit,
            )
            return
        endpoint = f"{_API}/company/{entity.entity_id}/filing-history"
        # Only "annual" maps to one source category; "other" and native types
        # are filtered here (AA01 shares "accounts" with annual accounts).
        category = {"category": "accounts"} if form == "annual" else {}
        index = count = 0
        while True:
            page = self._json(endpoint, params={"items_per_page": 100, "start_index": index, **category})
            items = page.get("items", [])
            for item in items:
                filing = self._api_filing(entity, item)
                filed = filing.filing_date
                if start and filed and filed < start:
                    return  # the history is newest first
                if not include_amendments and filing.amendment:
                    continue
                if not _matches(item, form) or (end and filed and filed > end):
                    continue
                yield filing
                count += 1
                if limit is not None and count >= limit:
                    return
            index += len(items)
            if not items or index >= page.get("total_count", index):
                return

    def _iter_filings_public(
        self, entity: Entity, *, form: str | None, start: date | None,
        end: date | None, include_amendments: bool, limit: int | None,
    ) -> Iterator[Filing]:
        url = f"{_SITE}/company/{entity.entity_id}/filing-history"
        seen_pages: set[str] = set()
        count = 0
        while url not in seen_pages:
            seen_pages.add(url)
            page = self._page(url)
            table = page.select_one("table#fhTable")
            if table is None:
                raise ProviderError(f"Companies House public filing history lacks a table for {entity.entity_id}")
            for row in table.select("tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) < 4:
                    continue
                raw_date = cells[0].get_text(" ", strip=True)
                try:
                    filed = datetime.strptime(raw_date, "%d %b %Y").date()
                except ValueError as exc:
                    raise ProviderError(f"unexpected Companies House filing date {raw_date!r}") from exc
                if start and filed < start:
                    return  # the history is newest first
                raw_form = cells[1].get_text(" ", strip=True)
                title = cells[2].get_text(" ", strip=True)
                links = [urljoin(_SITE, link["href"]) for link in cells[3].select("a[href]")]
                document_links = [
                    link for link in links
                    if urlparse(link).netloc == urlparse(_SITE).netloc
                    and _SITE_DOCUMENT.fullmatch(urlparse(link).path)
                ]
                if not document_links:
                    continue  # The public page does not expose a source transaction ID for this row.
                transaction = _SITE_DOCUMENT.fullmatch(urlparse(document_links[0]).path).group(1)
                item = {
                    "source": "public_website", "date": filed.isoformat(), "type": raw_form,
                    "description": title, "category": "accounts" if raw_form.upper() in _FILED_ACCOUNTS_TYPES else None,
                    "history_url": url, "document_urls": document_links,
                }
                amended = raw_form.upper().endswith("AMD") or "amend" in title.casefold()
                if not include_amendments and amended:
                    continue
                if not _matches(item, form) or (end and filed > end):
                    continue
                yield Filing(
                    filing_id=transaction, entity_id=entity.entity_id, jurisdiction="UK", provider=self.name,
                    regulator=self.regulator, source_url=url,
                    provenance=Provenance(self.name, self.regulator, "UK", url, transaction, datetime.now(timezone.utc), item),
                    filing_type_raw=raw_form, filing_type_normalized=_category(item), title=title,
                    filing_date=filed, amendment=amended, period_end=_made_up_to(item),
                    provider_metadata=item, _provider=self,
                )
                count += 1
                if limit is not None and count >= limit:
                    return
            next_link = next(
                (link.get("href") for link in page.select("a[href]") if link.get_text(" ", strip=True) == "Next page"),
                None,
            )
            if not next_link:
                return
            next_url = urljoin(_SITE, next_link)
            if urlparse(next_url).netloc != urlparse(_SITE).netloc:
                raise ProviderError("Companies House filing history points to an unexpected host")
            url = next_url

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        if filing.provider_metadata.get("source") == "public_website":
            links = filing.provider_metadata.get("document_urls", [])
            preferred = next((kind for kind in ("xhtml", "xml", "zip", "pdf")
                              if any(parse_qs(urlparse(link).query).get("format") == [kind] for link in links)), None)
            documents = []
            for index, url in enumerate(links):
                kind = parse_qs(urlparse(url).query).get("format", [""])[0]
                media_type = {
                    "xhtml": "application/xhtml+xml", "xml": "application/xml",
                    "zip": "application/zip", "pdf": "application/pdf",
                }.get(kind)
                documents.append(FilingDocument(
                    document_id=f"{filing.filing_id}:{kind or index}", filing_id=filing.filing_id,
                    filename=f"{filing.filing_id}.{kind or 'bin'}", source_url=url,
                    provenance=Provenance(self.name, self.regulator, "UK", url, filing.filing_id,
                                          datetime.now(timezone.utc), filing.provider_metadata),
                    media_type=media_type, document_type=filing.filing_type_raw,
                    is_primary=kind == preferred, role="report",
                    provider_metadata={"source": "public_website", "format": kind},
                    _provider=self,
                ))
            return documents
        metadata_link = filing.provider_metadata.get("links", {}).get("document_metadata")
        if not metadata_link:
            return []
        if metadata_link.startswith("/"):
            metadata_url = f"{_DOC}{metadata_link}"
        elif metadata_link.startswith(_DOC):
            metadata_url = metadata_link
        else:
            raise ProviderError(f"unexpected Companies House document metadata URL for {filing.filing_id}")
        metadata = self._json(metadata_url)
        document_id = str(metadata.get("id") or urlparse(metadata_url).path.rsplit("/", 1)[-1])
        formats = metadata.get("resources", {})
        preferred = next((kind for kind in ("application/xhtml+xml", "application/xml", "application/pdf") if kind in formats), None)
        documents = []
        for media_type, resource in formats.items():
            url = f"{_DOC}/document/{document_id}/content"
            documents.append(FilingDocument(
                document_id=f"{document_id}:{media_type}", filing_id=filing.filing_id,
                filename=f"{filing.filing_id}.{_EXTENSIONS.get(media_type, 'bin')}", source_url=url,
                provenance=Provenance(self.name, self.regulator, "UK", url, document_id, datetime.now(timezone.utc), metadata),
                media_type=media_type, document_type=filing.filing_type_raw,
                is_primary=media_type == preferred, role="report",
                provider_metadata={"resource": resource, "document_metadata": metadata},
                _provider=self,
            ))
        return documents

    def download_document(self, document: FilingDocument) -> bytes:
        return self.transport.get(document.source_url, headers={**self._headers, "Accept": document.media_type or "application/pdf"})

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        return self.transport.get_to_file(
            document.source_url, path,
            headers={**self._headers, "Accept": document.media_type or "application/pdf"},
            expected_prefix=_BINARY_PREFIXES.get(document.media_type),
        )

    def extract_text(self, document: FilingDocument) -> str:
        if document.media_type == "text/csv":
            return document.download().decode("utf-8", errors="replace")
        if document.media_type == "application/xhtml+xml":
            return document._html_text()
        if document.media_type == "application/zip":
            reports = best_reports(document)
            if reports:
                return reports[0].text()
        raise UnsupportedCapabilityError(
            f"Companies House text extraction does not support {document.media_type or document.filename}"
        )

    def raw_facts(self, filing: Filing):
        candidates = [document for document in filing.documents if document.media_type == "application/xhtml+xml"]
        for document in candidates:
            with document._parse_content() as content:
                facts = parse_ixbrl_xhtml(
                    content, document_url=document.source_url,
                    entry_path=document.filename, provider=self.name, regulator=self.regulator,
                    jurisdiction="UK", filing_id=filing.filing_id,
                )
            if facts:
                return facts
        for document in filing.documents:
            if document.media_type != "application/zip":
                continue
            for member in best_reports(document):
                if not member.entry_path.lower().endswith(".xhtml"):
                    continue
                with member._parse_content() as content:
                    facts = parse_ixbrl_xhtml(
                        content, document_url=document.source_url,
                        entry_path=member.entry_path, provider=self.name, regulator=self.regulator,
                        jurisdiction="UK", filing_id=filing.filing_id,
                    )
                if facts:
                    return facts
        raise UnsupportedCapabilityError(
            f"Companies House filing {filing.filing_id} has no inline XBRL facts in an XHTML representation"
        )
