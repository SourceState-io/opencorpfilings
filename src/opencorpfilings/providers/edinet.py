"""On-demand access to Japan's EDINET v2 disclosure API."""

from __future__ import annotations

import csv
import io
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..errors import AmbiguousEntityError, AuthenticationError, DownloadError, EntityNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..html_text import html_to_text
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..raw_xbrl import parse_ixbrl_xhtml, parse_xbrl_instance
from ..transport import HttpTransport


API = "https://api.edinet-fsa.go.jp/api/v2"
REGISTRY = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
_DOCUMENTS = f"{API}/documents.json"
_ANNUAL = {"120", "130"}
_QUARTERLY = {"140", "150"}
_INTERIM = {"160", "170"}
_CURRENT = {"180", "190"}
# Japan has no daylight saving; a fixed offset needs no tz database (absent on Windows).
_JST = timezone(timedelta(hours=9), "JST")
_DAY_CACHE_SIZE = 90
#: a TSE securities code; letters appear in the second and fourth places since 2024 (`130A`)
_SECURITIES_CODE = re.compile(r"[0-9][0-9A-Z][0-9][0-9A-Z]")


def _ticker(securities_code: str) -> str:
    """The four-character listing code of a five-character EDINET securities code ending in 0."""
    return securities_code[:4] if len(securities_code) == 5 and securities_code.endswith("0") \
        and _SECURITIES_CODE.fullmatch(securities_code[:4]) else ""
_XBRL_ROOT = "{http://www.xbrl.org/2003/instance}xbrl"


def _report_period(doc_type: str, start: object, end: object) -> tuple[date | None, date | None]:
    """The period a report covers. EDINET's periodStart/periodEnd give the fiscal year.

    A half-year report (160, amended 170) covers the first six months of that
    year by definition. A quarterly report (140, amended 150) does not say which
    quarter in these fields, so it has no period here.
    """
    first, last = _date(start), _date(end)
    if doc_type in {"160", "170"} and first is not None:
        month = first.month + 6
        year = first.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        return first, date(year, month, 1) - timedelta(days=1)
    if doc_type in {"140", "150"}:
        return None, None
    return first, last


def _date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _submission_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=_JST) if parsed.tzinfo is None else parsed


def _category(code: str) -> str:
    if code in _ANNUAL:
        return "annual"
    if code in _QUARTERLY:
        return "quarterly"
    if code in _INTERIM:
        return "interim"
    if code in _CURRENT:
        return "current"
    return "other"


def _registry_rows(raw: bytes) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1 or archive.testzip() is not None:
                raise ProviderError("EDINET code registry ZIP is invalid")
            text = archive.read(members[0]).decode("cp932")
    except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise ProviderError("EDINET code registry could not be read") from exc
    rows = list(csv.reader(io.StringIO(text, newline="")))
    header_at = next((i for i, row in enumerate(rows) if row and unicodedata.normalize("NFKC", row[0]).strip() == "EDINETコード"), None)
    if header_at is None:
        raise ProviderError("EDINET code registry header was not found")
    headers = [unicodedata.normalize("NFKC", value).strip() for value in rows[header_at]]
    result = []
    for values in rows[header_at + 1:]:
        if len(values) != len(headers):
            continue
        result.append(dict(zip(headers, values)))
    return result


class EDINETProvider(FilingProvider):
    name = "edinet"
    market = "JP"
    regulator = "Financial Services Agency EDINET"
    order_basis = "source_file_date"
    identifies_amendments = True
    tier = "supported"
    identifier_kinds = ("four-digit securities code", "EDINET code")
    forms = ("annual", "interim", "quarterly", "current", "other")
    native_forms = False
    auth = "required API key: api_key=, OPENCORPFILINGS_EDINET_API_KEY or EDINET_API_KEY"
    coverage_note = ("Discovery scans EDINET's daily lists one day per request: about 30 s for a recent "
                     "filing, minutes for one filed many months back unless start= narrows it. "
                     "Quarterly reports ended in April 2024.")
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download", "streamed_download", "text", "source_package", "xbrl", "ixbrl", "pdf", "raw_facts"})

    def filing_date_for_filter(self, filing: Filing) -> date | None:
        return _date(filing.provider_metadata.get("source_file_date"))

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: HttpTransport | None = None,
        default_lookback_days: int = 550,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENCORPFILINGS_EDINET_API_KEY") or os.getenv("EDINET_API_KEY")
        if not self.api_key:
            raise AuthenticationError("EDINET requires OPENCORPFILINGS_EDINET_API_KEY or EDINET_API_KEY")
        if default_lookback_days <= 0:
            raise ValueError("default_lookback_days must be positive")
        self.default_lookback_days = default_lookback_days
        self.transport = transport or HttpTransport(min_interval=0.2)
        self._registry: list[dict[str, str]] | None = None
        # documents.json answers Cache-Control: no-cache, so the transport never
        # reuses a day. Past JST days are kept here, bounded to the most recent
        # _DAY_CACHE_SIZE lists read (a peak day is about 1.2 MB of JSON).
        self._days: dict[date, list[dict[str, object]]] = {}
        self._days_lock = Lock()

    def _issuer_rows(self) -> list[dict[str, str]]:
        if self._registry is None:
            self._registry = _registry_rows(self.transport.get(REGISTRY))
        return self._registry

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        needle = unicodedata.normalize("NFKC", query.strip()).casefold()
        candidates = []
        for row in self._issuer_rows():
            code = row.get("EDINETコード", "")
            securities_code = row.get("証券コード", "")
            name = row.get("提出者名", "")
            english = row.get("提出者名(英字)", "")
            ticker = _ticker(securities_code)
            identifiers = (code.casefold(), securities_code.casefold(), ticker.casefold())
            names = (unicodedata.normalize("NFKC", name).casefold(), english.casefold())
            if not code or not name or not any(needle in value for value in identifiers + names if value):
                continue
            rank = 0 if needle in identifiers else 1 if needle in names else (
                2 if any(value.startswith(needle) for value in identifiers + names if value) else 3)
            candidates.append((rank, 0 if ticker else 1, names[0], code, row))
        results = []
        seen: set[str] = set()
        for _, _, _, code, row in sorted(candidates, key=lambda candidate: candidate[:4]):
            if code in seen:
                continue
            seen.add(code)
            results.append(self._entity_from_row(row))
            if len(results) >= limit:
                break
        return results

    def resolve_entity(self, identifier: str) -> Entity:
        value = identifier.strip().upper()
        if re.fullmatch(r"E\d{5}", value):
            matches = [row for row in self._issuer_rows() if row.get("EDINETコード") == value]
        elif _SECURITIES_CODE.fullmatch(value):
            matches = [row for row in self._issuer_rows() if row.get("証券コード") == value + "0"]
        else:
            raise ValueError("JP identifier must be an EDINET code or four-character securities code")
        if not matches:
            raise EntityNotFoundError(f"EDINET issuer {value} was not found in the official code list")
        if len(matches) > 1:
            raise AmbiguousEntityError(f"EDINET identifier {value} matches {len(matches)} issuer rows")
        return self._entity_from_row(matches[0])

    def _entity_from_row(self, row: dict[str, str]) -> Entity:
        code = row["EDINETコード"]
        securities_code = row.get("証券コード", "")
        ticker = _ticker(securities_code)
        source_url = f"https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx?edinetCode={code}"
        identifiers = [Identifier("edinet_code", code, REGISTRY)]
        if securities_code:
            identifiers.append(Identifier("securities_code", securities_code, REGISTRY))
        corporate_number = row.get("提出者法人番号", "")
        if corporate_number:
            identifiers.append(Identifier("jcn", corporate_number, REGISTRY))
        return Entity(
            entity_id=code,
            name=row.get("提出者名") or code,
            jurisdiction="JP",
            provider=self.name,
            source_url=source_url,
            identifiers=tuple(identifiers),
            tickers=(ticker,) if ticker else (),
            provider_metadata={**row, "registry_url": REGISTRY},
            provenance=Provenance(self.name, self.regulator, "JP", REGISTRY, code, datetime.now(timezone.utc), row),
        )

    def _daily(self, day: date) -> list[dict[str, object]]:
        with self._days_lock:
            if day in self._days:
                return self._days[day]
        rows = self._fetch_daily(day)
        if day < datetime.now(_JST).date():
            with self._days_lock:
                self._days[day] = rows
                while len(self._days) > _DAY_CACHE_SIZE:
                    del self._days[min(self._days)]  # keep the newest days, where every scan starts
        return rows

    def _fetch_daily(self, day: date) -> list[dict[str, object]]:
        data = self.transport.get_json(
            _DOCUMENTS,
            params={"date": day.isoformat(), "type": 2, "Subscription-Key": self.api_key},
            cache_credentials_in_memory=True,
        )
        if not isinstance(data, dict) or not isinstance(data.get("metadata"), dict):
            raise ProviderError(f"EDINET returned an invalid daily list for {day}")
        status = str(data["metadata"].get("status") or "")
        if status in {"401", "403"}:
            raise AuthenticationError("EDINET rejected the API key")
        if status != "200" or not isinstance(data.get("results"), list):
            raise ProviderError(f"EDINET daily list failed for {day} (status {status or 'unknown'})")
        return [row for row in data["results"] if isinstance(row, dict)]

    def _daily_in_order(self, start_day: date, end_day: date):
        # EDINET lists one source day per call. Overlap network waits, but
        # consume every day in descending order so latest() remains exact.
        with ThreadPoolExecutor(max_workers=4) as executor:
            day = end_day
            pending = deque()
            for _ in range(4):
                if day < start_day:
                    break
                pending.append((day, executor.submit(self._daily, day)))
                day -= timedelta(days=1)
            while pending:
                item, future = pending.popleft()
                rows = future.result()
                yield item, rows
                if day >= start_day:
                    pending.append((day, executor.submit(self._daily, day)))
                    day -= timedelta(days=1)

    def iter_filings(
        self,
        entity: Entity,
        *,
        form: str | None = None,
        start: date | None = None,
        end: date | None = None,
        include_amendments: bool = True,
        limit: int | None = None,
    ):
        if form not in {None, "annual", "quarterly", "interim", "current", "other"}:
            raise ValueError(f"unsupported EDINET filing category {form!r}")
        end_day = end or datetime.now(_JST).date()
        start_day = start or end_day - timedelta(days=self.default_lookback_days - 1)
        count = 0
        for day, rows in self._daily_in_order(start_day, end_day):
            rows.sort(key=lambda row: (str(row.get("submitDateTime") or ""), str(row.get("docID") or "")), reverse=True)
            for row in rows:
                if row.get("edinetCode") != entity.entity_id:
                    continue
                # A later file date may repeat an earlier docID to announce
                # a correction or disclosure change. The original day's row
                # carries the updated filing metadata.
                if (row.get("docInfoEditStatus") == "1"
                        or row.get("disclosureStatus") in {"1", "3"}
                        or row.get("withdrawalStatus") == "1"):
                    continue
                document_id = str(row.get("docID") or "")
                if not re.fullmatch(r"S[0-9A-Z]{7}", document_id):
                    continue
                code = str(row.get("docTypeCode") or "")
                period = _report_period(code, row.get("periodStart"), row.get("periodEnd"))
                category = _category(code)
                if form is not None and form != category:
                    continue
                amendment = code in {"130", "150", "170", "190"} or bool(row.get("parentDocID"))
                if amendment and not include_amendments:
                    continue
                submitted_at = _submission_time(row.get("submitDateTime"))
                filing_date = submitted_at.date() if submitted_at else day
                source_url = f"{API}/documents/{document_id}?type=1"
                provenance = Provenance(self.name, self.regulator, "JP", source_url, document_id, datetime.now(timezone.utc), row)
                yield Filing(
                    filing_id=document_id,
                    entity_id=entity.entity_id,
                    jurisdiction="JP",
                    provider=self.name,
                    regulator=self.regulator,
                    source_url=source_url,
                    provenance=provenance,
                    filing_type_raw=code,
                    filing_type_normalized=category.upper(),
                    title=str(row.get("docDescription") or ""),
                    filing_date=filing_date,
                    published_at=submitted_at,
                    period_start=period[0],
                    period_end=period[1],
                    amendment=amendment,
                    language="ja",
                    provider_metadata={**row, "source_file_date": day.isoformat()},
                    _provider=self,
                )
                count += 1
                if limit is not None and count >= limit:
                    return

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        row = filing.provider_metadata
        if row.get("withdrawalStatus") != "0" or row.get("disclosureStatus") != "0" or row.get("legalStatus") not in {"1", "2"}:
            return []
        kinds = [(1, "original", "application/zip", "zip", True)]
        if row.get("pdfFlag") == "1":
            kinds.append((2, "pdf", "application/pdf", "pdf", False))
        if row.get("attachDocFlag") == "1":
            kinds.append((3, "attachments", "application/zip", "zip", False))
        if row.get("englishDocFlag") == "1":
            kinds.append((4, "english", "application/zip", "zip", False))
        if row.get("csvFlag") == "1":
            kinds.append((5, "csv", "application/zip", "zip", False))
        result = []
        for kind, role, media_type, extension, primary in kinds:
            source_url = f"{API}/documents/{filing.filing_id}?type={kind}"
            result.append(FilingDocument(
                document_id=f"{filing.filing_id}:{kind}",
                filing_id=filing.filing_id,
                filename=f"{filing.filing_id}-{role}.{extension}",
                source_url=source_url,
                provenance=Provenance(self.name, self.regulator, "JP", source_url, f"{filing.filing_id}:{kind}", raw=row),
                media_type=media_type,
                document_type=role,
                language="en" if kind == 4 else "ja",
                is_primary=primary,
                role={"attachments": "annex", "csv": "data"}.get(role, "report"),
                provider_metadata={"doc_id": filing.filing_id, "kind": kind,
                                   "archive_encoding": "cp932" if kind != 2 else None},
                _provider=self,
            ))
        return result

    def _document_request(self, document: FilingDocument) -> tuple[str, dict[str, str | int], int]:
        doc_id = str(document.provider_metadata.get("doc_id") or "")
        kind = document.provider_metadata.get("kind")
        if not re.fullmatch(r"S[0-9A-Z]{7}", doc_id) or kind not in {1, 2, 3, 4, 5}:
            raise ValueError("invalid EDINET document reference")
        return f"{API}/documents/{doc_id}", {"type": int(kind), "Subscription-Key": self.api_key}, int(kind)

    def download_document(self, document: FilingDocument) -> bytes:
        endpoint, params, kind = self._document_request(document)
        doc_id = str(document.provider_metadata["doc_id"])
        body = self.transport.get(endpoint, params=params)
        if kind == 2:
            if not body.startswith(b"%PDF-"):
                raise DownloadError(f"EDINET did not return a PDF for {doc_id}")
            return body
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                if not archive.namelist() or archive.testzip() is not None:
                    raise DownloadError(f"EDINET returned an invalid ZIP for {doc_id}")
        except zipfile.BadZipFile as exc:
            raise DownloadError(f"EDINET did not return a ZIP for {doc_id}") from exc
        return body

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        endpoint, params, kind = self._document_request(document)
        return self.transport.get_to_file(
            endpoint, path, params=params,
            expected_prefix=b"%PDF-" if kind == 2 else b"PK\x03\x04",
            validate_zip_crc=kind != 2,
        )

    def extract_text(self, document: FilingDocument) -> str:
        if document.media_type != "application/zip" or document.document_type not in {"original", "english"}:
            return super().extract_text(document)
        chunks = []
        with zipfile.ZipFile(document._archive_source(), metadata_encoding="cp932") as archive:
            names = [name for name in archive.namelist() if name.lower().endswith((".htm", ".html", ".xhtml"))]
            public = [name for name in names if "/publicdoc/" in name.lower()]
            for name in sorted(public or names):
                raw = archive.read(name)
                for encoding in ("utf-8-sig", "cp932"):
                    try:
                        raw.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    continue
                text = html_to_text(raw, encoding=encoding)
                if text:
                    chunks.append(f"[{name}]\n{text}")
        if not chunks:
            return super().extract_text(document)
        return "\n\n".join(chunks)

    def raw_facts(self, filing: Filing):
        if filing.provider_metadata.get("xbrlFlag") != "1":
            raise UnsupportedCapabilityError(f"EDINET filing {filing.filing_id} has no XBRL source package")
        document = next((item for item in filing.documents if item.document_type == "original"), None)
        if document is None:
            raise UnsupportedCapabilityError(f"EDINET filing {filing.filing_id} has no available original package")
        facts = []
        instances = 0
        for member in document.members:
            if not member.entry_path.lower().endswith((".xbrl", ".xml")):
                continue
            with member._parse_content(max_bytes=50_000_000) as content:
                try:
                    source = str(content) if isinstance(content, Path) else io.BytesIO(content)
                    root = next(ET.iterparse(source, events=("start",)))[1]
                except (ET.ParseError, StopIteration):
                    if member.entry_path.lower().endswith(".xbrl"):
                        raise ParseError(f"EDINET XBRL member {member.entry_path} is invalid XML")
                    continue
                if root.tag != _XBRL_ROOT:
                    continue
                instances += 1
                facts.extend(parse_xbrl_instance(
                    content,
                    document_url=document.source_url,
                    entry_path=member.entry_path,
                    provider=self.name,
                    regulator=self.regulator,
                    jurisdiction="JP",
                    filing_id=filing.filing_id,
                ))
        if not instances:
            for member in document.members:
                if not member.entry_path.lower().endswith((".htm", ".html", ".xhtml")):
                    continue
                try:
                    with member._parse_content() as content:
                        facts.extend(parse_ixbrl_xhtml(
                            content, document_url=document.source_url,
                            entry_path=member.entry_path, provider=self.name, regulator=self.regulator,
                            jurisdiction="JP", filing_id=filing.filing_id,
                        ))
                except ParseError as exc:
                    if "invalid iXBRL XHTML" not in str(exc):
                        raise
            if not facts:
                raise UnsupportedCapabilityError(
                    f"EDINET package for {filing.filing_id} has no readable classic XBRL or XML iXBRL facts"
                )
        return facts
