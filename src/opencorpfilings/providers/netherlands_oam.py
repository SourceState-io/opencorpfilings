"""AFM public financial-reporting register, one issuer and document at a time."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import re
from urllib.parse import parse_qs, urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from ..errors import EntityNotFoundError, FilingNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..packages import package_facts, package_text
from ..transport import HttpTransport
from . import _oam


_ROOT = "https://www.afm.nl"
_REGISTER = f"{_ROOT}/en/sector/registers/meldingenregisters/financiele-verslaggeving"
_EXPORT = f"{_ROOT}/export.aspx"
_REGISTER_TYPE = "e8825b05-4004-4301-b736-651e8c61053d"
_SOURCE_ID = re.compile(r"^(?:[A-Z][0-9]{4}-[0-9]{5}|[1-9][0-9]*)$")
_AMSTERDAM = ZoneInfo("Europe/Amsterdam")
_CATEGORY = {"Annual financial report": "ANNUAL",
             "Half-yearly financial report": "INTERIM"}
_MONTH = {"jan": 1, "feb": 2, "mar": 3, "mrt": 3, "apr": 4, "may": 5,
          "mei": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
          "oct": 10, "okt": 10, "nov": 11, "dec": 12}


def _detail_url(source_id: str) -> str:
    if not _SOURCE_ID.fullmatch(source_id):
        raise ValueError("AFM filing ID has an invalid source format")
    return f"{_REGISTER}/details?id={source_id}"


def _download_url(href: str) -> str:
    url = urljoin(_ROOT, href)
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != "https" or parsed.hostname != "www.afm.nl"
            or parsed.path != "/downloadregisterfile.aspx"
            or query.get("type") != ["financiele-verslaggeving"]
            or len(query.get("enc", [])) != 1 or not query["enc"][0]):
        raise ProviderError("AFM returned an invalid original-file URL")
    return url


def _detail_fields(content: bytes) -> tuple[BeautifulSoup, dict[str, str]]:
    soup = BeautifulSoup(content.decode("cp1252"), "html.parser")
    fields: dict[str, str] = {}
    for item in soup.select(".cc-em--detail-list__item"):
        label = item.select_one(".cc-em--detail-list__label")
        value = item.select_one(".cc-em--detail-list__value")
        if label and value:
            fields[label.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
    if not all(fields.get(key) for key in ("Issuing institution", "Filing date", "Reporting year")):
        raise ParseError("AFM detail lacks issuer, filing date or reporting year")
    return soup, fields


def _filing_date(display: str) -> date:
    parts = display.strip().lower().split()
    if len(parts) != 3 or parts[1] not in _MONTH:
        raise ParseError("AFM detail has an invalid filing date")
    try:
        return date(int(parts[2]), _MONTH[parts[1]], int(parts[0]))
    except ValueError as exc:
        raise ParseError("AFM detail has an invalid filing date") from exc


def _raw_detail_type(soup: BeautifulSoup) -> str:
    cell = soup.select_one("table.cc-table-wrap-text tbody tr td")
    if cell is None:
        cell = soup.select_one("table.cc-table-wrap-text tr:has(td) td")
    if cell is None:
        raise ParseError("AFM detail lacks a document type")
    for label in cell.select(".cc-mobile-title"):
        label.decompose()
    value = cell.get_text(" ", strip=True)
    if not value:
        raise ParseError("AFM detail has an empty document type")
    return value


class NetherlandsOAMProvider(FilingProvider):
    name = "netherlands_oam"
    market = "NL"
    regulator = "Netherlands Authority for the Financial Markets / AFM"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery",
                              "document_download", "streamed_download", "source_package",
                              "pdf", "html", "text", "raw_facts", "ixbrl",
                              "direct_filing_lookup"})
    identifier_kinds = ("exact register issuer name",)
    forms = ("annual", "interim")
    native_forms = False
    order_basis = "filing_date"

    def __init__(self, *, transport: HttpTransport | None = None, max_records: int = 500) -> None:
        if not 1 <= max_records <= 5000:
            raise ValueError("max_records must be between 1 and 5000")
        self.transport = transport or HttpTransport(min_interval=0.5)
        self.max_records = max_records

    def _records(self, query: str) -> list[dict[str, str | datetime]]:
        if len(query.strip()) < 3:
            raise ValueError("AFM issuer search needs at least three characters")
        params = {"KeyWords": query.strip(), "type": _REGISTER_TYPE, "format": "xml"}
        content = self.transport.get(_EXPORT, params=params)
        if len(content) > 5_000_000:
            raise UnsupportedCapabilityError("AFM issuer search is too broad; use a more specific name")
        try:
            # The export's older records contain Windows-1252 bytes without an
            # XML encoding declaration. Preserve those native source labels.
            root = ElementTree.fromstring(content.decode("cp1252"))
        except (UnicodeError, ElementTree.ParseError) as exc:
            raise ParseError("AFM returned an invalid financial-reporting export") from exc
        if root.tag != "register" or root.get("name") != "financiele-verslaggeving":
            raise ParseError("AFM returned a different register")
        rows = root.findall("vermelding")
        if len(rows) > self.max_records:
            raise UnsupportedCapabilityError("AFM issuer search exceeded max_records; use a more specific name")
        records: list[dict[str, str | datetime]] = []
        for row in rows:
            raw = {key: (row.findtext(key) or "").strip() for key in
                   ("id", "datum", "uitgevende-instelling", "boekjaar", "filename",
                    "objecttype", "objecttype_eng")}
            if not raw["uitgevende-instelling"] or not raw["datum"]:
                raise ParseError("AFM financial-reporting row lacks issuer or filing time")
            source_id = raw["id"]
            if not _SOURCE_ID.fullmatch(source_id):
                raise ParseError("AFM financial-reporting row has an invalid source ID")
            try:
                # The export states Amsterdam wall-clock time without an offset.
                published_at = datetime.strptime(raw["datum"], "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=_AMSTERDAM)
            except ValueError as exc:
                raise ParseError("AFM financial-reporting row has an invalid source date") from exc
            records.append({**raw, "published_at": published_at})
        records.sort(key=lambda item: item["published_at"], reverse=True)
        return records

    def _entity(self, name: str, source_id: str) -> Entity:
        url = _detail_url(source_id)
        raw = {"identity_basis": "exact source issuer name", "register": "financiele-verslaggeving"}
        return Entity(name, name, "NL", self.name, url,
                      (Identifier("SOURCE_NAME", name, url),), provider_metadata=raw,
                      provenance=Provenance(self.name, self.regulator, "NL", url, name,
                                            datetime.now(timezone.utc), raw))

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        seen: set[str] = set()
        result: list[Entity] = []
        for raw in self._records(query):
            name = str(raw["uitgevende-instelling"])
            if name in seen:
                continue
            seen.add(name)
            result.append(self._entity(name, str(raw["id"])))
            if len(result) >= limit:
                break
        return result

    def resolve_entity(self, identifier: str) -> Entity:
        name = identifier.strip()
        for raw in self._records(name):
            if str(raw["uitgevende-instelling"]).casefold() == name.casefold():
                return self._entity(str(raw["uitgevende-instelling"]), str(raw["id"]))
        raise EntityNotFoundError(f"AFM found no exact source issuer name {name!r}")

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        if entity.jurisdiction != "NL" or entity.provider != self.name:
            raise ValueError("entity is not from the AFM financial-reporting register")
        url = _detail_url(filing_id)
        soup, fields = _detail_fields(self.transport.get(url))
        if fields["Issuing institution"] != entity.name:
            raise FilingNotFoundError(f"AFM record {filing_id} does not belong to the selected issuer")
        raw_type = _raw_detail_type(soup)
        normalized = "ANNUAL" if raw_type.startswith("Jaarlijkse ") else "INTERIM" if raw_type.startswith("Halfjaarlijkse ") else None
        when = _filing_date(fields["Filing date"])
        raw = {"report_year": fields["Reporting year"], "detail_fields": fields,
               "published_display": fields["Filing date"]}
        return Filing(filing_id, entity.entity_id, "NL", self.name, self.regulator, url,
                      Provenance(self.name, self.regulator, "NL", url, filing_id,
                                 datetime.now(timezone.utc), {**raw, "type_raw": raw_type}),
                      filing_type_raw=raw_type, filing_type_normalized=normalized,
                      title=raw_type, filing_date=when, amendment=None,
                      provider_metadata=raw, _provider=self)

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        if form not in {None, "annual", "interim"}:
            raise UnsupportedCapabilityError("AFM financial reporting maps only annual and half-yearly categories")
        if not include_amendments:
            raise UnsupportedCapabilityError("AFM export does not establish amendment status")
        if entity.jurisdiction != "NL" or entity.provider != self.name:
            raise ValueError("entity is not from the AFM financial-reporting register")
        count = 0
        for raw in self._records(entity.entity_id):
            if str(raw["uitgevende-instelling"]) != entity.name:
                continue
            category = _CATEGORY.get(str(raw["objecttype_eng"]))
            if form is not None and category != form.upper():
                continue
            published_at = raw["published_at"]
            when = published_at.date()
            if start and when < start:
                break
            if end and when > end:
                continue
            source_id = str(raw["id"])
            url = _detail_url(source_id)
            metadata = {"report_year": raw["boekjaar"], "source_filename": raw["filename"],
                        "type_english": raw["objecttype_eng"], "published_display": raw["datum"]}
            yield Filing(source_id, entity.entity_id, "NL", self.name, self.regulator, url,
                         Provenance(self.name, self.regulator, "NL", url, source_id,
                                    datetime.now(timezone.utc), {**metadata, "type_raw": raw["objecttype"]}),
                         filing_type_raw=str(raw["objecttype"]), filing_type_normalized=category,
                         title=str(raw["objecttype_eng"]), filing_date=when,
                         published_at=published_at, amendment=None, provider_metadata=metadata,
                         _provider=self)
            count += 1
            if limit is not None and count >= limit:
                return

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        if filing.jurisdiction != "NL" or filing.provider != self.name or filing.source_url != _detail_url(filing.filing_id):
            raise ValueError("filing is not an AFM financial-reporting record")
        soup, details = _detail_fields(self.transport.get(filing.source_url))
        if details.get("Issuing institution") != filing.entity_id:
            raise ProviderError("AFM detail does not match the selected issuer")
        if details.get("Reporting year") != filing.provider_metadata.get("report_year"):
            raise ProviderError("AFM detail reporting year differs from the register export")
        if _filing_date(details["Filing date"]) != filing.filing_date:
            raise ProviderError("AFM detail filing date differs from the selected record")
        documents: list[FilingDocument] = []
        for link in soup.select('table.cc-table-wrap-text a[href*="downloadregisterfile.aspx"]'):
            filename = link.get_text(" ", strip=True)
            if not filename:
                raise ParseError("AFM detail has an original file without a filename")
            url = _download_url(str(link["href"]))
            document_id = f"{filing.filing_id}:{len(documents) + 1}"
            raw = {"register_id": filing.filing_id, "source_filename": filename,
                   "report_year": details["Reporting year"]}
            documents.append(FilingDocument(document_id, filing.filing_id, filename, url,
                                            Provenance(self.name, self.regulator, "NL", url, document_id,
                                                       datetime.now(timezone.utc), raw),
                                            media_type=_oam.media_type(filename),
                                            document_type=filing.filing_type_raw, is_primary=not documents,
                                            provider_metadata=raw, _provider=self))
        if not documents:
            raise ParseError("AFM detail has no original document link")
        return documents

    def download_document(self, document: FilingDocument) -> bytes:
        return _oam.download(self.transport, _download_url(document.source_url), label="AFM original file")

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        return _oam.save(self.transport, _download_url(document.source_url), path, document.media_type,
                         label="AFM original file")

    def extract_text(self, document: FilingDocument) -> str:
        return package_text(document, label="AFM")

    def raw_facts(self, filing: Filing):
        return package_facts(filing, name=self.name, regulator=self.regulator, jurisdiction="NL", label="AFM")
