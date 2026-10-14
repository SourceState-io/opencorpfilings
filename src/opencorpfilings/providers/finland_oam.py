"""Individual annual notices and attachments from Finland's public OAM."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from heapq import merge
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..errors import AmbiguousEntityError, EntityNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..packages import package_facts, package_text
from ..transport import HttpTransport
from . import _oam


_ROOT = "https://oam.fi/"
_HOST = "oam.fi"
_ANNUAL_CATEGORY = "270"
_VIEW_ID = re.compile(r"/view/(\d+)")
_PUBLISHED = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) (EET|EEST|GMT)$")
_ANNUAL_LABEL = "Annual financial report"
_INTERIM_LABELS = ("Half year financial report",
                   "Interim report (Q1, Q3 and Q4) and Financial Statement Release")
_CORRECTION = re.compile(r"\b(?:CORRECTION|KORJAUSTIEDOTE|RÄTTELSE)\b", re.IGNORECASE)


def _soup(content: bytes) -> BeautifulSoup:
    return BeautifulSoup(content, "html.parser")


def _search_key(value: str) -> str:
    """Match typed issuer names while retaining the source's original spelling."""
    return "".join(character for character in unicodedata.normalize("NFKD", value)
                   if not unicodedata.combining(character)).casefold()


def _label_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _published(value: str) -> datetime:
    match = _PUBLISHED.fullmatch(value.strip())
    if match is None:
        raise ParseError(f"Finnish OAM returned an unrecognized publication time {value!r}")
    offset = {"EET": 2, "EEST": 3, "GMT": 0}[match.group(3)]
    return datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}").replace(
        tzinfo=timezone(timedelta(hours=offset))
    )


class FinlandOAMProvider(FilingProvider):
    name = "finland_oam"
    market = "FI"
    regulator = "Finland OAM / Nasdaq Helsinki"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download",
                              "streamed_download", "source_package", "pdf", "html", "text", "raw_facts", "ixbrl"})
    identifier_kinds = ("exact OAM company name", "numeric source company ID")
    forms = ("annual", "interim")
    native_forms = False
    coverage_note = ("Nasdaq's general terms restrict automated capture; the owner's decision on "
                     "this route is pending before any distribution.")
    order_basis = "published_at"

    def __init__(self, *, transport: HttpTransport | None = None,
                 page_size: int = 50, max_pages: int = 20) -> None:
        if not 1 <= page_size <= 500:
            raise ValueError("page_size must be between 1 and 500")
        if not 1 <= max_pages <= 100:
            raise ValueError("max_pages must be between 1 and 100")
        self.transport = transport or HttpTransport(min_interval=0.5)
        self.page_size = page_size
        self.max_pages = max_pages
        self._landing: BeautifulSoup | None = None
        self._issuer_options: list[dict] | None = None

    def _landing_page(self) -> BeautifulSoup:
        if self._landing is None:
            self._landing = _soup(self.transport.get(_ROOT))
        return self._landing

    def _issuers(self) -> list[dict]:
        if self._issuer_options is not None:
            return self._issuer_options
        selector = self._landing_page().select_one('[name="company"][options]')
        if selector is None:
            raise ParseError("FI OAM has no company selector")
        try:
            options = json.loads(selector["options"])
        except (ValueError, TypeError) as exc:
            raise ParseError("FI OAM company selector is invalid") from exc
        if not isinstance(options, list):
            raise ParseError("FI OAM company selector is not a list")
        self._issuer_options = [item for item in options if isinstance(item, dict) and
                                str(item.get("value", "")).isdecimal() and item.get("label")]
        return self._issuer_options

    def _entity(self, row: dict) -> Entity:
        company_id, name = str(row["value"]), str(row["label"])
        return Entity(
            entity_id=company_id, name=name, jurisdiction="FI", provider=self.name,
            source_url=_ROOT,
            identifiers=(Identifier("OAM company ID", company_id, _ROOT),),
            provider_metadata={"selector": row, "identity_basis": "exact OAM company ID/name"},
            provenance=Provenance(self.name, self.regulator, self.market, _ROOT, company_id,
                                  datetime.now(timezone.utc), row),
        )

    def resolve_entity(self, identifier: str) -> Entity:
        requested = identifier.strip()
        matches = [item for item in self._issuers() if
                   (str(item.get("value")) == requested or
                    str(item.get("label", "")).casefold() == requested.casefold())]
        if not matches:
            fragment = requested.split()[0] if requested else requested
            raise EntityNotFoundError(
                f"FI OAM has no exact company name or company ID {requested!r}; "
                f"try search_companies({fragment!r}, market={self.market!r}) to find a "
                "source-listed name or ID, or source='esef_index' for LEI lookup"
            )
        if len(matches) > 1:
            raise AmbiguousEntityError(f"FI OAM has {len(matches)} companies matching {requested!r}")
        return self._entity(matches[0])

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        needle = _search_key(query.strip())
        if not needle:
            raise ValueError("query must not be empty")
        return [self._entity(row) for row in self._issuers()
                if needle in _search_key(str(row["label"])) or needle == str(row["value"])][:limit]

    @staticmethod
    def _category_filters(form: str | None) -> list[tuple[str, str | None]]:
        if form == "annual":
            return [(_ANNUAL_CATEGORY, _ANNUAL_LABEL)]
        if form == "interim":
            return [("78", _INTERIM_LABELS[0]), ("153", _INTERIM_LABELS[1])]
        return [("", None)]

    @staticmethod
    def _normalized_kind(kind: str) -> str | None:
        if _label_key(kind) == _label_key(_ANNUAL_LABEL):
            return "ANNUAL"
        if any(_label_key(kind) == _label_key(label) for label in _INTERIM_LABELS):
            return "INTERIM"
        return None

    def _search(self, company_id: str, company_name: str, category: str, expected_label: str | None,
                start: date, end: date, page: int) -> list[Filing]:
        landing = self._landing_page()
        token = landing.select_one('input[name="_csrf"]')
        if token is None or not token.get("value"):
            raise ParseError("FI OAM search form lacks its CSRF token")
        payload = {
            "_csrf": str(token["value"]), "oam": "fi", "language": "en",
            "pageSize": str(self.page_size), "page": str(page), "freeText": "",
            "market": "2", "company": company_id, "category": category,
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "includeObsoleteCompanies": "true",
        }
        content = self.transport.post_form(_ROOT, data=payload)
        soup = _soup(content)
        if soup.select_one("nef-table") is None:
            raise ParseError("FI OAM search returned no recognizable results table")
        filings: list[Filing] = []
        for row in soup.select("nef-table-row.message-row"):
            cells = row.select("nef-table-cell")
            if len(cells) != 4:
                raise ParseError("FI OAM search row has an unexpected number of cells")
            link = cells[2].select_one("nef-link[href]")
            match = _VIEW_ID.search(str(link.get("href", ""))) if link else None
            if match is None:
                raise ParseError("FI OAM search row lacks a notice link")
            # The search is scoped to the source company ID. A row shows the name
            # used when the notice was published ("Kesko" for "Kesko Oyj", a
            # former name after a rename), so it is recorded, not required to match.
            row_company = cells[1].get_text(" ", strip=True)
            kind = cells[3].get_text(" ", strip=True)
            if expected_label is not None and _label_key(kind) != _label_key(expected_label):
                raise ProviderError("FI OAM returned a different report category")
            published = _published(cells[0].get_text(" ", strip=True))
            view_id = match.group(1)
            url = urljoin(_ROOT, f"view/{view_id}?lang=en")
            raw = {"search_company_id": company_id, "company": row_company, "issuer_list_name": company_name,
                   "category": kind, "category_id": category or None,
                   "headline": link.get_text(" ", strip=True),
                   "published_display": cells[0].get_text(" ", strip=True),
                   "notice_href": link.get("href")}
            filings.append(Filing(
                filing_id=view_id, entity_id=company_id, jurisdiction="FI",
                provider=self.name, regulator=self.regulator, source_url=url,
                provenance=Provenance(self.name, self.regulator, self.market, url, view_id,
                                      datetime.now(timezone.utc), raw),
                filing_type_raw=kind, filing_type_normalized=self._normalized_kind(kind),
                title=raw["headline"], filing_date=published.date(), published_at=published,
                amendment=True if _CORRECTION.search(raw["headline"]) else None,
                provider_metadata=raw, _provider=self,
            ))
        return filings

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        if form is not None and form.lower() not in {"annual", "interim"}:
            raise UnsupportedCapabilityError("FI OAM supports annual and interim report categories")
        if not include_amendments:
            raise UnsupportedCapabilityError("FI OAM correction status requires notice-level interpretation")
        if not entity.entity_id.isdecimal() or entity.jurisdiction != self.market:
            raise ValueError("entity does not have a FI OAM company ID")
        # A bounded default keeps source search polite; an explicit start reaches older notices.
        today = datetime.now(timezone.utc).date()
        start_date = start or date(today.year - 5, 1, 1)
        end_date = end or today
        filters = self._category_filters(form.lower() if form else None)
        streams = [self._iter_category(entity, category, label, start_date, end_date)
                   for category, label in filters]
        ordered = streams[0] if len(streams) == 1 else merge(
            *streams, key=lambda filing: (filing.published_at, filing.filing_id), reverse=True)
        seen: set[str] = set()
        yielded = 0
        for filing in ordered:
            if filing.filing_id in seen:
                raise ProviderError(f"FI OAM repeated notice {filing.filing_id}")
            seen.add(filing.filing_id)
            yield filing
            yielded += 1
            if limit is not None and yielded >= limit:
                return

    def _iter_category(self, entity: Entity, category: str, label: str | None,
                       start_date: date, end_date: date) -> Iterator[Filing]:
        page = 1
        while page <= self.max_pages:
            rows = self._search(entity.entity_id, entity.name, category, label, start_date, end_date, page)
            if not rows:
                return
            for filing in rows:
                yield filing
            if len(rows) < self.page_size:
                return
            page += 1
        raise UnsupportedCapabilityError(
            f"FI OAM search reached its {self.max_pages}-page safety bound; "
            "narrow the date range or raise max_pages"
        )

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        if filing.jurisdiction != self.market or not filing.filing_id.isdecimal():
            raise ValueError("filing is not a FI OAM notice")
        content = self.transport.get(filing.source_url)
        soup = _soup(content)
        documents: list[FilingDocument] = []
        for link in soup.select("nef-link[href]"):
            href = link.get("href", "")
            if "viewAttachment.action?messageAttachmentId=" not in href:
                continue
            url = urljoin(_ROOT, href)
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != _HOST:
                raise ProviderError("FI OAM returned an attachment outside its HTTPS host")
            filename = link.get_text(" ", strip=True)
            if not filename:
                raise ParseError(f"FI OAM attachment lacks a filename in notice {filing.filing_id}")
            attachment_id = parsed.query.split("messageAttachmentId=", 1)[-1]
            if not attachment_id.isdecimal():
                raise ParseError("FI OAM attachment lacks a numeric ID")
            documents.append(FilingDocument(
                document_id=attachment_id, filing_id=filing.filing_id,
                filename=filename, source_url=url,
                provenance=Provenance(self.name, self.regulator, self.market, url, attachment_id,
                                      raw={"notice_id": filing.filing_id, "filename": filename}),
                media_type=_oam.media_type(filename), document_type="original_oam_attachment",
                is_primary=False, provider_metadata={"notice_url": filing.source_url},
                _provider=self,
            ))
        if documents:
            priority = {"application/zip": 0, "application/xhtml+xml": 1, "application/pdf": 2}
            primary = min(documents, key=lambda item: priority.get(item.media_type or "", 3))
            primary.is_primary = True
        return documents

    def download_document(self, document: FilingDocument) -> bytes:
        _oam.require_https_host(document.source_url, _HOST, "FI OAM attachment URL is outside its HTTPS host")
        return _oam.download(self.transport, document.source_url, label="FI OAM attachment")

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        _oam.require_https_host(document.source_url, _HOST, "FI OAM attachment URL is outside its HTTPS host")
        return _oam.save(self.transport, document.source_url, path, document.media_type,
                         label="FI OAM attachment")

    def extract_text(self, document: FilingDocument) -> str:
        return package_text(document, label="FI OAM")

    def raw_facts(self, filing: Filing):
        return package_facts(filing, name=self.name, regulator=self.regulator, jurisdiction="FI", label="FI OAM")
