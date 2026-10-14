"""Country-scoped access to the incomplete filings.xbrl.org ESEF index.

The index is a secondary collection, not a national filing register. Its
``date_added`` is never substituted for a regulator filing/publication date.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

from ..errors import (
    DownloadError,
    EntityNotFoundError,
    FilingNotFoundError,
    ParseError,
    ProviderError,
    UnsupportedCapabilityError,
)
from ..models import Entity, Filing, FilingDocument, FilingFact, Identifier, Provenance
from ..provider import FilingProvider
from ..packages import report_members
from ..raw_xbrl import parse_ixbrl_xhtml
from ..transport import HttpTransport
from . import _oam


_BASE = "https://filings.xbrl.org"
_LEI = re.compile(r"[A-Z0-9]{20}\Z")
# A country appears here only after a country-filtered index query returned
# records on 2026-10-07. CZ, CY, RO, LV and PL were removed on 2026-10-08:
# the index stopped receiving them (newest periods 2020-2023; PL's last record
# was added 2024-07-30). This says nothing about national OAM coverage.
INDEX_COUNTRIES = frozenset({
    "AT", "BE", "HR", "DK", "EE", "FI", "FR", "GR", "HU",
    "IS", "IT", "LT", "LU", "MT", "NL", "NO", "PT",
    "SK", "SI", "ES", "SE",
})
# ESEF naming ends a report or package file with its language: ...-1-de.xhtml
_FILE_LANGUAGE = re.compile(r"-([a-z]{2})\.(?:xhtml|html?|zip|xbri)\Z", re.IGNORECASE)


def _language(attrs: dict) -> str | None:
    for key in ("report_url", "package_url"):
        path = attrs.get(key)
        if isinstance(path, str) and (match := _FILE_LANGUAGE.search(unquote(urlparse(path).path))):
            return match.group(1).lower()
    return None


def _absolute(path: str) -> str:
    url = urljoin(_BASE + "/", path)
    if urlparse(url).netloc != "filings.xbrl.org" or not url.startswith("https://"):
        raise ProviderError(f"unexpected ESEF index URL: {path}")
    return url


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # The index currently returns naive timestamps. Preserve the missing timezone.
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ParseError(f"invalid ESEF index timestamp: {value!r}") from exc


def _date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ParseError(f"invalid ESEF report period end: {value!r}") from exc


def _period_dates(value: object) -> tuple[date | None, date | None]:
    """Convert OIM interval bounds; midnight end/instant means prior civil day."""
    if not isinstance(value, str) or value == "forever":
        return None, None

    def parsed(part: str) -> datetime | None:
        try:
            return datetime.fromisoformat(part.replace("Z", "+00:00"))
        except ValueError:
            return None

    def end_date(part: str) -> date | None:
        point = parsed(part)
        if point is None:
            return None
        if "T" in part and point.time().hour == point.time().minute == point.time().second == point.time().microsecond == 0:
            return point.date() - timedelta(days=1)
        return point.date()

    if "/" in value:
        start, end = value.split("/", 1)
        start_point = parsed(start)
        return (start_point.date() if start_point else None), end_date(end)
    return None, end_date(value)


def _package_hash(document: FilingDocument) -> str | None:
    if document.document_type != "source_package":
        return None
    expected = document.provider_metadata.get("index_sha256")
    if expected is None:
        return None
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise DownloadError(f"ESEF index has an invalid SHA-256 for {document.source_url}")
    return expected.lower()


class ESEFProvider(FilingProvider):
    name = "esef_index"
    regulator = "filings.xbrl.org index"
    capabilities = frozenset({"entity_lookup", "filing_discovery", "direct_filing_lookup", "document_download", "streamed_download", "html", "text", "raw_facts", "xbrl", "ixbrl", "source_package"})
    order_basis = "report_period"
    tier = "limited"
    identifier_kinds = ("LEI",)
    forms = ("annual",)
    native_forms = False
    date_filters = False
    coverage_note = ("Secondary index of ESEF annual reports by LEI; it lags regulators by months and is "
                     "incomplete. On 2026-10-08 it held 974 FY2025 December-year-end reports against "
                     "2,142 for FY2024 (45%), with whole countries at 0%.")

    def __init__(
        self,
        *,
        market: str,
        transport: HttpTransport | None = None,
        page_size: int = 100,
        max_pages: int = 20,
        prefer_language: str = "en",
    ) -> None:
        market = market.upper()
        if market not in INDEX_COUNTRIES:
            raise ValueError(f"ESEF index country {market!r} is not in the verified index-country set")
        if not 1 <= page_size <= 200:
            raise ValueError("page_size must be between 1 and 200")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self.market = market
        self.transport = transport or HttpTransport(min_interval=0.25)
        self.page_size = page_size
        self.max_pages = max_pages
        self.prefer_language = prefer_language.lower()

    def resolve_entity(self, identifier: str) -> Entity:
        lei = identifier.strip().upper()
        if not _oam.LEI.fullmatch(lei):
            raise EntityNotFoundError(f"{self.market} ESEF index lookup requires a 20-character LEI")
        api_url = f"{_BASE}/api/entities/{quote(lei)}"
        try:
            response = self.transport.get_json(api_url)
        except ProviderError as exc:
            if "HTTP 404" in str(exc):
                raise EntityNotFoundError(f"LEI {lei} is absent from the ESEF index") from exc
            raise
        row = response.get("data") if isinstance(response, dict) else None
        attrs = row.get("attributes") if isinstance(row, dict) else None
        if not isinstance(attrs, dict) or attrs.get("identifier") != lei:
            raise ProviderError(f"ESEF index returned an unexpected entity for LEI {lei}")
        name = attrs.get("name")
        if not isinstance(name, str) or not name:
            raise ParseError(f"ESEF index omitted the name for LEI {lei}")
        provenance = Provenance(
            provider=self.name,
            regulator=self.regulator,
            jurisdiction=self.market,
            source_url=api_url,
            source_id=str(row.get("id", lei)),
            retrieved_at=datetime.now(timezone.utc),
            raw=row,
        )
        return Entity(
            entity_id=lei,
            name=name,
            jurisdiction=self.market,
            provider=self.name,
            source_url=f"{_BASE}/entity/{lei}",
            identifiers=(Identifier(kind="LEI", value=lei, source_url=api_url),),
            provider_metadata=row,
            provenance=provenance,
        )

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        if entity.jurisdiction != self.market or not _oam.LEI.fullmatch(entity.entity_id):
            raise ValueError("entity jurisdiction or LEI does not match this ESEF provider")
        if not re.fullmatch(r"[1-9][0-9]*", filing_id):
            raise FilingNotFoundError(f"ESEF index filing ID {filing_id!r} is invalid")
        url = f"{_BASE}/api/filings/{filing_id}"
        try:
            response = self.transport.get_json(url)
        except ProviderError as exc:
            if "HTTP 404" in str(exc):
                raise FilingNotFoundError(f"ESEF index filing {filing_id} was not found") from exc
            raise
        row = response.get("data") if isinstance(response, dict) else None
        if not isinstance(row, dict) or str(row.get("id")) != filing_id:
            raise ProviderError(f"ESEF index returned an unexpected filing for ID {filing_id}")
        attrs = row.get("attributes")
        if not isinstance(attrs, dict) or not isinstance(attrs.get("fxo_id"), str):
            raise ParseError(f"ESEF index filing {filing_id} lacks fxo_id")
        if not isinstance(attrs.get("country"), str):
            raise ParseError(f"ESEF index filing {filing_id} lacks country")
        if attrs["country"] != self.market or not attrs["fxo_id"].startswith(entity.entity_id + "-"):
            raise FilingNotFoundError(f"ESEF index filing {filing_id} does not belong to {entity.entity_id} in {self.market}")
        return self._filing_from_row(entity, row)

    def iter_filings(
        self,
        entity: Entity,
        *,
        form: str | None = None,
        start: date | None = None,
        end: date | None = None,
        include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        if form is not None and form.lower() != "annual":
            raise UnsupportedCapabilityError(f"ESEF index holds annual reports only; form={form!r} is unavailable")
        if start is not None or end is not None:
            raise UnsupportedCapabilityError("ESEF central index has no regulator filing date for start/end filtering")
        if not include_amendments:
            raise UnsupportedCapabilityError("ESEF central index does not reliably identify amendment relationships")
        lei = entity.entity_id
        if entity.jurisdiction != self.market or not _oam.LEI.fullmatch(lei):
            raise ValueError("entity jurisdiction or LEI does not match this ESEF provider")
        # An issuer has few records, so the whole bounded listing is read and
        # ordered by report period: the index's own order is when it added a
        # record, which put Enel's FY2021 report ahead of FY2022.
        filings = sorted(self._all_filings(entity), key=lambda filing: (
            -(filing.period_end.toordinal() if filing.period_end else 0),
            filing.language != self.prefer_language,
            -(filing.index_added_at.timestamp() if filing.index_added_at else 0),
        ))
        yield from filings[:limit] if limit is not None else filings

    def _all_filings(self, entity: Entity) -> Iterator[Filing]:
        lei = entity.entity_id
        url = f"{_BASE}/api/entities/{quote(lei)}/filings"
        page = 1
        seen: set[str] = set()
        while page <= self.max_pages:
            params = {"page[size]": self.page_size, "page[number]": page, "sort": "-date_added"}
            response = self.transport.get_json(url, params=params)
            rows = response.get("data") if isinstance(response, dict) else None
            if not isinstance(rows, list):
                raise ParseError(f"ESEF index returned an invalid filing page for {lei}")
            if not rows:
                return
            for row in rows:
                filing = self._filing_from_row(entity, row)
                if filing.filing_id in seen:
                    raise ProviderError(f"ESEF index repeated filing {filing.filing_id} across pages")
                seen.add(filing.filing_id)
                if filing.jurisdiction != self.market:
                    continue
                yield filing
            count = response.get("meta", {}).get("count")
            if (isinstance(count, int) and page * self.page_size >= count) or len(rows) < self.page_size:
                return
            page += 1
        raise UnsupportedCapabilityError(
            f"ESEF index listing reached its {self.max_pages}-page safety bound; "
            "raise max_pages"
        )

    def _filing_from_row(self, entity: Entity, row: object) -> Filing:
        if not isinstance(row, dict) or row.get("type") != "filing":
            raise ParseError("ESEF index returned a non-filing record")
        attrs = row.get("attributes")
        if not isinstance(attrs, dict):
            raise ParseError("ESEF index filing lacks attributes")
        identifier = attrs.get("fxo_id")
        country = attrs.get("country")
        if not isinstance(identifier, str) or not identifier.startswith(entity.entity_id + "-"):
            raise ProviderError(f"ESEF index returned a filing for another issuer than {entity.entity_id}")
        if not isinstance(country, str) or f"-ESEF-{country}-" not in identifier:
            raise ProviderError(f"ESEF index filing {identifier} has inconsistent country metadata")
        related = row.get("relationships", {}).get("entity", {}).get("links", {}).get("related")
        if related and _absolute(related) != f"{_BASE}/api/entities/{entity.entity_id}":
            raise ProviderError(f"ESEF index filing {identifier} has a different entity relationship")
        filing_id = str(row.get("id") or "")
        if not filing_id:
            raise ParseError("ESEF index filing lacks an ID")
        api_url = _absolute(row.get("links", {}).get("self") or f"/api/filings/{filing_id}")
        provenance = Provenance(
            provider=self.name,
            regulator=self.regulator,
            jurisdiction=country,
            source_url=api_url,
            source_id=filing_id,
            retrieved_at=datetime.now(timezone.utc),
            raw=row,
        )
        return Filing(
            filing_id=filing_id,
            entity_id=entity.entity_id,
            jurisdiction=country,
            provider=self.name,
            regulator=self.regulator,
            source_url=f"{_BASE}/filing/{quote(identifier)}",
            provenance=provenance,
            # Period end is inferred from tagged facts; it is not a source filing date.
            filing_date=None,
            index_added_at=_datetime(attrs.get("date_added")),
            period_end=_date(attrs.get("period_end")),
            # ESEF tagging is mandated for annual financial reports; the index has no form field.
            filing_type_raw="ESEF",
            filing_type_normalized="ANNUAL",
            language=_language(attrs),
            amendment=None,
            provider_metadata={**attrs, "_jsonapi": row},
            _provider=self,
        )

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        attrs = filing.provider_metadata
        documents: list[FilingDocument] = []
        for key, kind, media_type in (
            ("report_url", "report_xhtml", "application/xhtml+xml"),
            ("package_url", "source_package", "application/zip"),
            ("json_url", "derived_xbrl_json", "application/json"),
        ):
            path = attrs.get(key)
            if not isinstance(path, str) or not path:
                continue
            url = _absolute(path)
            document_id = f"{filing.filing_id}:{kind}"
            documents.append(FilingDocument(
                document_id=document_id,
                filing_id=filing.filing_id,
                filename=unquote(urlparse(url).path.rsplit("/", 1)[-1]),
                source_url=url,
                media_type=media_type,
                document_type=kind,
                role="data" if kind == "derived_xbrl_json" else "report",
                is_primary=kind == "report_xhtml" or (kind == "source_package" and not attrs.get("report_url")),
                provenance=Provenance(
                    provider=self.name,
                    regulator=self.regulator,
                    jurisdiction=filing.jurisdiction,
                    source_url=url,
                    source_id=document_id,
                    raw={"index_filing_id": filing.filing_id, "index_sha256": attrs.get("sha256"), "representation": kind},
                ),
                provider_metadata={"index_sha256": attrs.get("sha256"), "representation": kind},
                _provider=self,
            ))
        return documents

    def download_document(self, document: FilingDocument) -> bytes:
        try:
            content = self.transport.get(_absolute(document.source_url), cache=False)
        except ProviderError as exc:
            raise DownloadError(f"could not download ESEF document {document.source_url}: {exc}") from exc
        expected = _package_hash(document)
        if expected is not None and hashlib.sha256(content).hexdigest() != expected:
            raise DownloadError(f"ESEF source package SHA-256 differs from index for {document.source_url}")
        return content

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        try:
            return self.transport.get_to_file(
                _absolute(document.source_url), path,
                expected_prefix=b"PK\x03\x04" if document.document_type == "source_package" else None,
                expected_sha256=_package_hash(document),
            )
        except ProviderError as exc:
            raise DownloadError(f"could not save ESEF document {document.source_url}: {exc}") from exc

    def extract_text(self, document: FilingDocument) -> str:
        if document.document_type == "report_xhtml":
            return document._html_text()
        if document.document_type == "source_package":
            reports = [member for member in report_members(document)
                       if "/reports/" in f"/{member.entry_path.lower()}"]
            if reports:
                return "\n\n".join(member.text() for member in reports)
        raise UnsupportedCapabilityError("ESEF filing has no available report XHTML")

    def raw_facts(self, filing: Filing) -> list[FilingFact]:
        document = next((item for item in filing.documents if item.document_type == "derived_xbrl_json"), None)
        if document is None:
            sources = sorted(filing.documents, key=lambda item: item.document_type != "source_package")
            for source in sources:
                if source.document_type == "report_xhtml":
                    candidates = [(source.filename, source)]
                elif source.document_type == "source_package":
                    candidates = ((member.entry_path, member) for member in report_members(source)
                                  if "/reports/" in f"/{member.entry_path.lower()}")
                else:
                    continue
                all_facts: list[FilingFact] = []
                for path, candidate in candidates:
                    with candidate._parse_content() as content:
                        all_facts.extend(parse_ixbrl_xhtml(content, document_url=source.source_url,
                                                            entry_path=path, provider=self.name, regulator=self.regulator,
                                                            jurisdiction=filing.jurisdiction, filing_id=filing.filing_id))
                if all_facts:
                    return all_facts
            raise UnsupportedCapabilityError("this ESEF index filing has no available structured facts")
        try:
            report = json.loads(document.download())
        except (ValueError, UnicodeDecodeError) as exc:
            raise ParseError(f"invalid ESEF xBRL-JSON at {document.source_url}") from exc
        if not isinstance(report, dict) or not isinstance(report.get("facts"), dict):
            raise ParseError(f"ESEF xBRL-JSON lacks a facts object at {document.source_url}")
        info = report.get("documentInfo", {})
        taxonomy = info.get("taxonomy") if isinstance(info, dict) else None
        taxonomy_single = taxonomy[0] if isinstance(taxonomy, list) and len(taxonomy) == 1 and isinstance(taxonomy[0], str) else None
        facts: list[FilingFact] = []
        for fact_id, raw in report["facts"].items():
            dimensions = raw.get("dimensions") if isinstance(raw, dict) else None
            if not isinstance(dimensions, dict) or not isinstance(dimensions.get("concept"), str):
                raise ParseError(f"ESEF xBRL-JSON fact {fact_id} lacks a concept")
            start, end = _period_dates(dimensions.get("period"))
            facts.append(FilingFact(
                concept_raw=dimensions["concept"],
                value="" if raw.get("value") is None else str(raw["value"]),
                unit=str(dimensions["unit"]) if dimensions.get("unit") is not None else None,
                period_start=start,
                period_end=end,
                context_id=None,
                dimensions={str(key): str(value) for key, value in dimensions.items() if value is not None},
                taxonomy=taxonomy_single,
                source_location=f"{document.source_url}#/facts/{quote(str(fact_id).replace('~', '~0').replace('/', '~1'), safe='')}",
                provenance=Provenance(
                    provider=self.name,
                    regulator=self.regulator,
                    jurisdiction=filing.jurisdiction,
                    source_url=document.source_url,
                    source_id=str(fact_id),
                    raw=raw,
                ),
                provider_metadata={"fact_id": fact_id, "raw": raw, "document_info": info},
            ))
        return facts
