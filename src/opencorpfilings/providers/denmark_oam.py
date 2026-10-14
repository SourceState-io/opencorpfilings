"""Danish FSA public OAM announcements through its embedded GoPublic search."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlparse

from ..errors import EntityNotFoundError, FilingNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..packages import package_facts, package_text
from ..transport import HttpTransport
from . import _oam


_PORTAL = "https://www.dfsa.dk/financial-themes/capital-market/company-announcements"
_APP = "https://appft.gold.extension.gopublic.dk"
_API = f"{_APP}/api/9217fa13-5d9a-46c6-9921-69ee7e6cfaf6"
_BLOB_HOST = "saesappublicprd.blob.core.windows.net"
_BUSINESS_ID = re.compile(r"^[A-Z]{2}-[A-Z0-9.-]+$")
_NOTICE_ID = re.compile(r"^[1-9][0-9]*$")
_COPENHAGEN = ZoneInfo("Europe/Copenhagen")
_CATEGORY = {"Annual financial report": "ANNUAL",
             "Half year financial report": "INTERIM"}
_FORM_CODE = {"annual": "ANFIRE", "interim": "HYFIRE"}


def _notice_url(notice_id: str) -> str:
    if not _NOTICE_ID.fullmatch(notice_id):
        raise ValueError("Danish OAM announcement ID must be numeric")
    return f"{_APP}/details/{notice_id}"


def _published(display: str) -> datetime:
    try:
        # The source shows Copenhagen wall-clock time without an offset.
        return datetime.strptime(display, "%d-%m-%Y %H:%M:%S").replace(tzinfo=_COPENHAGEN)
    except ValueError as exc:
        raise ParseError("Danish OAM returned an invalid source publication time") from exc


def _original_url(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != _BLOB_HOST
            or not parsed.path.startswith("/stc-public-submissions/")
            or "/documents/" not in parsed.path or parsed.query or parsed.fragment):
        raise ProviderError("Danish OAM returned an original file outside its public source store")
    return url


def _detail_values(data: object) -> tuple[dict[str, str], list[dict[str, str]]]:
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        raise ParseError("Danish OAM detail lacks source sections")
    fields: dict[str, str] = {}
    links: list[dict[str, str]] = []
    for section in data["sections"]:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading", ""))
        for element in section.get("elements", []):
            if not isinstance(element, dict) or not isinstance(element.get("value"), dict):
                continue
            key = element.get("key") or {}
            name = str(key.get("name", "")) if isinstance(key, dict) else ""
            value = element["value"]
            if value.get("type") == "link":
                links.append({"title": str(value.get("title", "")),
                              "url": str(value.get("url", ""))})
            elif value.get("type") == "text" and name:
                fields[f"{heading}:{name}"] = str(value.get("value", ""))
    if not all(fields.get(key) for key in
               ("Notification:Announcement ID", "Notification:Type", "Time:Published",
                "Issuer:Company", "Issuer:National business ID")):
        raise ParseError("Danish OAM detail lacks required announcement or issuer fields")
    return fields, links


class DenmarkOAMProvider(FilingProvider):
    name = "denmark_oam"
    market = "DK"
    regulator = "Danish Financial Supervisory Authority / OAM"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery",
                              "direct_filing_lookup", "document_download", "streamed_download",
                              "source_package", "pdf", "html", "text", "raw_facts", "ixbrl"})
    identifier_kinds = ("source business ID", "exact issuer name")
    forms = ("annual", "interim")
    native_forms = False
    coverage_note = ("Some issuers file only an HTML announcement and publish the report elsewhere "
                     "(Danske Bank's H1 2026); then the announcement is the only document.")
    order_basis = "published_at"

    def __init__(self, *, transport: HttpTransport | None = None, max_pages: int = 20) -> None:
        if not 1 <= max_pages <= 100:
            raise ValueError("max_pages must be between 1 and 100")
        self.transport = transport or HttpTransport(min_interval=0.5)
        self.max_pages = max_pages
        self._issuer_options: list[dict[str, str]] | None = None

    def _issuers(self) -> list[dict[str, str]]:
        if self._issuer_options is not None:
            return self._issuer_options
        config = self.transport.get_json(f"{_API}/config")
        if not isinstance(config, dict) or not isinstance(config.get("components"), dict):
            raise ParseError("Danish OAM returned an invalid public search configuration")
        for item in config["components"].get("filters", []):
            if isinstance(item, dict) and item.get("key") == "IssuerFilter":
                options = item.get("options")
                if isinstance(options, list):
                    result = [{"id": str(option.get("id", "")), "label": str(option.get("label", ""))}
                              for option in options if isinstance(option, dict)]
                    if all(_BUSINESS_ID.fullmatch(row["id"]) and row["label"] for row in result):
                        self._issuer_options = result
                        return result
        raise ParseError("Danish OAM public search has no valid issuer filter")

    def _issuer_names(self, source_id: str) -> set[str]:
        return {item["label"] for item in self._issuers() if item["id"] == source_id}

    def _entity(self, source_id: str, name: str) -> Entity:
        raw = {"identity_basis": "source national business ID", "source_issuer_name": name}
        return Entity(source_id, name, "DK", self.name, _PORTAL,
                      (Identifier("NATIONAL_BUSINESS_ID", source_id, _PORTAL),),
                      provider_metadata=raw,
                      provenance=Provenance(self.name, self.regulator, "DK", _PORTAL, source_id,
                                            datetime.now(timezone.utc), raw))

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        def search_key(value: str) -> str:
            return value.casefold().replace("æ", "ae").replace("ø", "o").replace("å", "aa")

        query = search_key(query.strip())
        return [self._entity(item["id"], item["label"])
                for item in self._issuers() if query in search_key(item["label"])][:limit]

    def resolve_entity(self, identifier: str) -> Entity:
        query = identifier.strip()
        issuers = self._issuers()
        id_matches = [item for item in issuers if item["id"] == query.upper()]
        if id_matches:
            name = id_matches[0]["label"]
            if len({item["label"] for item in id_matches}) > 1:
                rows, _ = self._search(self._entity(query.upper(), name), None, 1)
                if rows:
                    recent_name = str(rows[0].get("IssuerColumn") or "")
                    if recent_name not in {item["label"] for item in id_matches}:
                        raise ProviderError("Danish OAM search returned another issuer")
                    name = recent_name
            return self._entity(query.upper(), name)
        for item in issuers:
            if item["label"].casefold() == query.casefold():
                return self._entity(item["id"], item["label"])
        raise EntityNotFoundError("Danish OAM needs a listed national business ID or exact source issuer name")

    def _search(self, entity: Entity, form: str | None, page: int) -> tuple[list[dict], int]:
        filters = [{"type": "dropdown", "key": "IssuerFilter", "options": [entity.entity_id]}]
        if form is not None:
            filters.append({"type": "dropdown", "key": "CategoryFilter", "options": [_FORM_CODE[form]]})
        data = self.transport.post_json(f"{_API}/search",
                                        {"query": "", "filters": filters, "page": page, "pageSize": 25})
        if not isinstance(data, dict) or not isinstance(data.get("paging"), dict) or not isinstance(data.get("data"), dict):
            raise ParseError("Danish OAM search returned an invalid result page")
        rows = data["data"].get("rows")
        pages = data["paging"].get("totalPages")
        if not isinstance(rows, list) or not isinstance(pages, int) or pages < 1:
            raise ParseError("Danish OAM search lacks result rows or page count")
        return rows, pages

    def _filing(self, entity: Entity, raw: dict) -> Filing:
        if not isinstance(raw, dict):
            raise ParseError("Danish OAM search returned an invalid record")
        source_id = str(raw.get("id", ""))
        url = _notice_url(source_id)
        source_issuer_name = str(raw.get("IssuerColumn") or "")
        if source_issuer_name not in self._issuer_names(entity.entity_id):
            raise ProviderError("Danish OAM search returned another issuer")
        category = str(raw.get("CategoryColumn", ""))
        published_at = _published(str(raw.get("PublicationDateColumn", "")))
        metadata = {"registration_display": raw.get("RegistrationDateColumn"),
                    "historical": raw.get("IsHistoricalColumn"),
                    "issuer_business_id": entity.entity_id, "source_issuer_name": source_issuer_name,
                    "headline": raw.get("HeadlineColumn")}
        return Filing(source_id, entity.entity_id, "DK", self.name, self.regulator, url,
                      Provenance(self.name, self.regulator, "DK", url, source_id,
                                 datetime.now(timezone.utc), dict(raw)),
                      filing_type_raw=category, filing_type_normalized=_CATEGORY.get(category),
                      title=str(raw.get("HeadlineColumn", "")), filing_date=published_at.date(),
                      published_at=published_at, amendment=None, provider_metadata=metadata,
                      _provider=self)

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        if form not in {None, "annual", "interim"}:
            raise UnsupportedCapabilityError("Danish OAM currently maps only annual and half-yearly categories")
        if not include_amendments:
            raise UnsupportedCapabilityError("Danish OAM does not establish amendment status")
        if entity.jurisdiction != "DK" or entity.provider != self.name:
            raise ValueError("entity is not from Danish OAM")
        yielded = 0
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            rows, total_pages = self._search(entity, form, page)
            if not rows:
                return
            for raw in rows:
                filing = self._filing(entity, raw)
                if filing.filing_id in seen:
                    raise ProviderError(f"Danish OAM repeated announcement {filing.filing_id}")
                seen.add(filing.filing_id)
                if form and filing.filing_type_normalized != form.upper():
                    raise ProviderError("Danish OAM category filter returned another source type")
                when = filing.filing_date
                if start and when < start:
                    return
                if end and when > end:
                    continue
                yield filing
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            if page >= total_pages:
                return
        raise UnsupportedCapabilityError(
            f"Danish OAM search reached its {self.max_pages}-page safety bound; narrow the date range or raise max_pages"
        )

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        if entity.jurisdiction != "DK" or entity.provider != self.name:
            raise ValueError("entity is not from Danish OAM")
        _notice_url(filing_id)
        detail = self.transport.get_json(f"{_API}/details/{filing_id}")
        fields, _ = _detail_values(detail)
        if fields["Notification:Announcement ID"] != filing_id:
            raise ProviderError("Danish OAM detail ID differs from the requested announcement")
        if (fields["Issuer:National business ID"] != entity.entity_id
                or fields["Issuer:Company"] not in self._issuer_names(entity.entity_id)):
            raise FilingNotFoundError(f"Danish OAM notice {filing_id} does not belong to the selected issuer")
        published_at = _published(fields["Time:Published"])
        category = fields["Notification:Type"]
        metadata = {"registration_display": fields.get("Time:Registration time"),
                    "issuer_lei": fields.get("Issuer:LEI code"),
                    "source_issuer_name": fields["Issuer:Company"], "detail_fields": fields}
        url = _notice_url(filing_id)
        return Filing(filing_id, entity.entity_id, "DK", self.name, self.regulator, url,
                      Provenance(self.name, self.regulator, "DK", url, filing_id,
                                 datetime.now(timezone.utc), metadata),
                      filing_type_raw=category, filing_type_normalized=_CATEGORY.get(category),
                      title=str(detail.get("heading", "")), filing_date=published_at.date(),
                      published_at=published_at, amendment=None, provider_metadata=metadata,
                      _provider=self)

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        if filing.jurisdiction != "DK" or filing.provider != self.name or filing.source_url != _notice_url(filing.filing_id):
            raise ValueError("filing is not a Danish OAM announcement")
        fields, links = _detail_values(self.transport.get_json(f"{_API}/details/{filing.filing_id}"))
        if (fields["Notification:Announcement ID"] != filing.filing_id
                or fields["Issuer:National business ID"] != filing.entity_id
                or fields["Issuer:Company"] != filing.provider_metadata.get("source_issuer_name")
                or fields["Notification:Type"] != filing.filing_type_raw
                or _published(fields["Time:Published"]).date() != filing.filing_date):
            raise ProviderError("Danish OAM detail differs from the selected filing")
        documents: list[FilingDocument] = []
        for link in links:
            url = _original_url(link["url"])
            filename = PurePosixPath(unquote(urlparse(url).path)).name
            if not filename:
                raise ParseError("Danish OAM original link lacks a filename")
            document_id = f"{filing.filing_id}:{len(documents) + 1}"
            language = "en" if link["title"].endswith("(English)") else None
            raw = {"source_label": link["title"], "issuer_business_id": filing.entity_id,
                   "issuer_lei": fields.get("Issuer:LEI code") if _oam.LEI.fullmatch(fields.get("Issuer:LEI code", "")) else None}
            documents.append(FilingDocument(document_id, filing.filing_id, filename, url,
                                            Provenance(self.name, self.regulator, "DK", url, document_id,
                                                       datetime.now(timezone.utc), raw),
                                            media_type=_oam.media_type(filename),
                                            document_type=filing.filing_type_raw, language=language,
                                            provider_metadata=raw, _provider=self))
        if not documents:
            raise UnsupportedCapabilityError(f"Danish OAM notice {filing.filing_id} has no original file")
        # An HTML or text file beside a PDF/ZIP/XHTML is the announcement, not the
        # report (DSV, Coloplast and Danske interims were ~8k-character notices).
        notice_types = {"text/html", "text/plain"}
        has_attachment = any(document.media_type not in notice_types for document in documents)
        periodic = filing.filing_type_normalized in {"ANNUAL", "INTERIM", "QUARTERLY"}
        for document in documents:
            if document.media_type in notice_types and has_attachment:
                document.role = "announcement"
            elif periodic:
                document.role = "report"
        return documents

    def download_document(self, document: FilingDocument) -> bytes:
        return _oam.download(self.transport, _original_url(document.source_url), label="Danish OAM original file")

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        return _oam.save(self.transport, _original_url(document.source_url), path, document.media_type,
                         label="Danish OAM original file")

    def extract_text(self, document: FilingDocument) -> str:
        if document.media_type == "text/plain":
            return document.download().decode("utf-8", errors="replace")
        return package_text(document, label="Danish OAM")

    def raw_facts(self, filing: Filing):
        return package_facts(filing, name=self.name, regulator=self.regulator, jurisdiction="DK", label="Danish OAM")
