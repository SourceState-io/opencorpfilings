"""On-demand access to Korea's official Open DART disclosure API."""

from __future__ import annotations

import io
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..errors import (
    AmbiguousEntityError,
    AuthenticationError,
    DownloadError,
    EntityNotFoundError,
    ParseError,
    ProviderError,
    RateLimitError,
    SourceUnavailableError,
    UnsupportedCapabilityError,
)
from ..html_text import html_to_text
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..raw_xbrl import parse_xbrl_instance
from ..transport import HttpTransport


API = "https://engopendart.fss.or.kr/engapi"
VIEWER = "https://dart.fss.or.kr/dsaf001/main.do"
CORP_CODES = f"{API}/corpCode.xml"
CORP_SEARCH = "https://dart.fss.or.kr/corp/searchCorp.ax"
CORP_SEARCH_EN = "https://englishdart.fss.or.kr/corp/searchCorp.ax"
COMPANY = f"{API}/company.json"
LIST = f"{API}/list.json"
# Korea has no daylight saving. Open DART report-type codes per category.
_KST = timezone(timedelta(hours=9), "KST")
_REPORT_TYPES = {"annual": "A001", "interim": "A002", "quarterly": "A003"}
DOCUMENT = f"{API}/document.xml"
XBRL = f"{API}/fnlttXbrl.xml"
_PERIODIC = {"annual": "11011", "interim": "11012", "quarterly": None}
_DATE_IN_TITLE = re.compile(r"(?P<year>20\d{2})\s*[./년-]\s*(?P<month>\d{1,2})(?:\s*[./월-]\s*(?P<day>\d{1,2}))?")
_CORRECTION = re.compile(r"^\s*(?:\[[^]]*(?:정정|correct|amend|revis)[^]]*\]|정정|첨부정정)", re.I)
_XBRL_ROOT = "{http://www.xbrl.org/2003/instance}xbrl"


def _status(data: dict[str, object], *, no_data_ok: bool = False) -> bool:
    status = str(data.get("status", ""))
    if status == "000":
        return True
    if status == "013" and no_data_ok:
        return False
    if status in {"010", "011", "012", "901"}:
        raise AuthenticationError(f"Open DART rejected the API key or account (status {status})")
    if status == "020":
        raise RateLimitError("Open DART request limit exceeded (status 020)")
    if status == "800":
        raise SourceUnavailableError("Open DART service is temporarily unavailable for maintenance (status 800)")
    raise ProviderError(f"Open DART returned status {status or 'unknown'}")


def _zip_or_error(body: bytes, *, source: str) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise DownloadError(f"Open DART returned an invalid {source} ZIP")
        return body
    except zipfile.BadZipFile:
        pass
    try:
        root = ET.fromstring(body)
        data = {child.tag.rsplit("}", 1)[-1]: child.text for child in root}
    except ET.ParseError as exc:
        raise DownloadError(f"Open DART did not return a {source} ZIP") from exc
    if "status" in data:
        if data["status"] in {"013", "014"}:
            raise DownloadError(f"Open DART has no {source} for this receipt (status {data['status']})")
        if not _status(data, no_data_ok=True):
            raise DownloadError(f"Open DART has no {source} for this receipt (status 013)")
    raise DownloadError(f"Open DART did not return a {source} ZIP")


_CORRECTION_PREFIX = re.compile(r"^\s*(?:\[[^]]*\]|기재정정|첨부정정|첨부추가|정정)\s*")
_REPORT_TITLES = (
    ("interim", "11012", r"반기보고서|semi[- ]?annual report|half[- ]?year(?:ly)? report"),
    ("quarterly", None, r"분기보고서|quarterly report"),
    ("annual", "11011", r"사업보고서|annual report|business report"),
)


def _category(title: str) -> tuple[str, str | None]:
    """Classify only a title that IS the periodic report, after correction tags.

    A substring test classified notices such as a deadline-extension filing
    (사업보고서제출기한연장신고서) as the annual report it mentions.
    """
    base = title.casefold()
    while (stripped := _CORRECTION_PREFIX.sub("", base, count=1)) != base:
        base = stripped
    for category, code, names in _REPORT_TITLES:
        if re.fullmatch(rf"(?:{names})(?:\s*\(\d{{4}}\.\d{{2}}\))?\s*", base):
            return category, code
    return "other", None


def _period_end(title: str) -> date | None:
    match = _DATE_IN_TITLE.search(title)
    if not match:
        return None
    year, month = int(match["year"]), int(match["month"])
    if not 1 <= month <= 12:
        return None
    if match["day"]:
        day = int(match["day"])
    else:
        import calendar

        day = calendar.monthrange(year, month)[1]
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _report_code(category: str, period_end: date | None, fiscal_end: int | None) -> str | None:
    if category in {"annual", "interim"}:
        return _PERIODIC[category]
    if category != "quarterly" or period_end is None or fiscal_end is None:
        return None
    elapsed = (period_end.month - fiscal_end) % 12
    return {3: "11013", 9: "11014"}.get(elapsed)


class OpenDARTProvider(FilingProvider):
    name = "open_dart"
    market = "KR"
    regulator = "Financial Supervisory Service Open DART"
    identifies_amendments = True
    tier = "experimental"
    identifier_kinds = ("six-character stock code", "eight-digit corporation code")
    forms = ("annual", "interim", "quarterly", "other")
    native_forms = False
    auth = "required API key: api_key=, OPENCORPFILINGS_DART_API_KEY or OPENDART_API_KEY"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download", "streamed_download", "text", "source_package", "xbrl", "raw_facts"})

    def __init__(self, *, api_key: str | None = None, transport: HttpTransport | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENCORPFILINGS_DART_API_KEY") or os.getenv("OPENDART_API_KEY")
        if not self.api_key:
            raise AuthenticationError("Open DART requires OPENCORPFILINGS_DART_API_KEY or OPENDART_API_KEY")
        self.transport = transport or HttpTransport(min_interval=0.2)
        self._registry: list[dict[str, str]] | None = None

    def _get_json(self, url: str, params: dict[str, str | int]) -> dict[str, object]:
        data = self.transport.get_json(url, params={**params, "crtfc_key": self.api_key})
        if not isinstance(data, dict):
            raise ProviderError("Open DART returned a non-object JSON response")
        return data

    def _corp_registry(self) -> list[dict[str, str]]:
        if self._registry is None:
            body = self.transport.get(CORP_CODES, params={"crtfc_key": self.api_key})
            _zip_or_error(body, source="corporation registry")
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                members = [name for name in archive.namelist() if name.lower().endswith(".xml")]
                if len(members) != 1:
                    raise ProviderError("Open DART corporation registry has no unique XML member")
                with archive.open(members[0]) as source:
                    root = ET.parse(source).getroot()
            self._registry = [{child.tag: (child.text or "").strip() for child in item}
                              for item in root.findall("list")]
        return self._registry

    def _selector_rows(self, query: str, *, contains: bool = False,
                       source: str = CORP_SEARCH) -> tuple[str, list[dict[str, str]]]:
        params = {"textCrpNm": query}
        if contains:
            params["likeYn"] = "Y"
        source_url = f"{source}?{urlencode(params)}"
        body = self.transport.get(source, params=params, max_bytes=1_000_000)
        page = BeautifulSoup(body, "html.parser")
        table = page.select_one("table.tb")
        if table is None:
            raise ParseError("DART company search returned no company table")
        page_info = page.select_one(".pageInfo")
        if page_info is not None:
            pages = re.search(r"\[\s*\d+\s*/\s*(\d+)\s*\]", page_info.get_text(" ", strip=True))
            if pages and int(pages.group(1)) > 1:
                raise ParseError("DART company search returned more than one page")
        rows: list[dict[str, str]] = []
        for row in table.select("tbody tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 4:
                continue
            code_input = row.select_one('input[name^="hiddenCikCD"]')
            code = str(code_input.get("value") or "") if code_input else ""
            if not re.fullmatch(r"\d{8}", code):
                raise ParseError("DART company search returned an invalid corporation code")
            name_input = row.select_one('input[name^="hiddenCikNM"]')
            name = str(name_input.get("value") or "").strip() if name_input else ""
            if not name:
                name = "".join(cells[1].find_all(string=True, recursive=False)).strip()
            stock = cells[3].get_text(" ", strip=True)
            if stock and not re.fullmatch(r"[0-9A-Z]{6}", stock):
                raise ParseError("DART company search returned an invalid stock code")
            if not name:
                raise ParseError("DART company search returned a corporation without a name")
            rows.append({"corp_code": code, "corp_name": name, "stock_code": stock})
        return source_url, rows

    def _corp_code_for_stock(self, stock_code: str) -> str:
        # DART's public company selector accepts a stock code. This exact
        # lookup avoids the multi-megabyte full registry on the common path.
        _, rows = self._selector_rows(stock_code)
        matches: set[str] = set()
        for row in rows:
            if row["stock_code"] == stock_code:
                matches.add(row["corp_code"])
        if not matches:
            raise EntityNotFoundError(f"no Open DART corporation for stock code {stock_code}")
        if len(matches) > 1:
            raise AmbiguousEntityError(f"stock code {stock_code} maps to {len(matches)} Open DART corporations")
        return next(iter(matches))

    def _registry_code_for_stock(self, stock_code: str) -> str:
        matches = {item["corp_code"] for item in self._corp_registry()
                   if item.get("stock_code") == stock_code and re.fullmatch(r"\d{8}", item.get("corp_code", ""))}
        if not matches:
            raise EntityNotFoundError(f"no Open DART corporation for stock code {stock_code}")
        if len(matches) > 1:
            raise AmbiguousEntityError(f"stock code {stock_code} maps to {len(matches)} Open DART corporations")
        return next(iter(matches))

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        needle = query.strip().casefold()
        if re.fullmatch(r"\d{8}", needle):
            try:
                return [self.resolve_entity(needle)]
            except EntityNotFoundError:
                return []
        stock_query = bool(re.fullmatch(r"[0-9a-z]{6}", needle) and any(c.isdigit() for c in needle))
        korean_query = bool(re.search(r"[\uac00-\ud7a3]", needle))
        english_query = bool(re.search(r"[a-z]", needle)) and not (stock_query or korean_query)
        if stock_query or korean_query or english_query:
            try:
                source_url, rows = self._selector_rows(
                    query.strip().upper() if stock_query else query.strip(), contains=not stock_query,
                    source=CORP_SEARCH_EN if english_query else CORP_SEARCH)
            except ParseError:
                # The unversioned HTML selector can change; the API registry
                # retains the broad search behavior on that failure path.
                pass
            else:
                candidates = []
                for row in rows:
                    code, name, stock = row["corp_code"], row["corp_name"], row["stock_code"]
                    if needle not in (code, stock.casefold()) and needle not in name.casefold():
                        continue
                    rank = 0 if needle in (code, stock.casefold()) else 1 if needle == name.casefold() else (
                        2 if name.casefold().startswith(needle) else 3)
                    candidates.append((rank, 0 if stock else 1, name.casefold(), code, row))
                results = []
                seen: set[str] = set()
                for _, _, _, code, row in sorted(candidates, key=lambda candidate: candidate[:4]):
                    if code in seen:
                        continue
                    seen.add(code)
                    stock = row["stock_code"]
                    results.append(Entity(
                        entity_id=code, name=row["corp_name"], jurisdiction="KR", provider=self.name,
                        source_url=source_url,
                        identifiers=(Identifier("corp_code", code, source_url),)
                        + ((Identifier("stock_code", stock, source_url),) if stock else ()),
                        tickers=(stock,) if stock else (), provider_metadata=row,
                        provenance=Provenance(self.name, self.regulator, "KR", source_url, code,
                                              datetime.now(timezone.utc), row),
                    ))
                    if len(results) >= limit:
                        break
                if results or not english_query:
                    return results
        candidates = []
        for row in self._corp_registry():
            code, stock = row.get("corp_code", ""), row.get("stock_code", "")
            name, english = row.get("corp_name", ""), row.get("corp_eng_name", "")
            fields = (code.casefold(), stock.casefold(), name.casefold(), english.casefold())
            if not code or not name or not any(needle in value for value in fields if value):
                continue
            rank = 0 if needle in fields[:2] else 1 if needle in fields[2:] else (
                2 if any(value.startswith(needle) for value in fields if value) else 3)
            candidates.append((rank, 0 if stock else 1, name.casefold(), code, row))
        results = []
        seen: set[str] = set()
        for _, _, _, code, row in sorted(candidates, key=lambda candidate: candidate[:4]):
            if code in seen:
                continue
            seen.add(code)
            stock = row.get("stock_code", "")
            source_url = f"{COMPANY}?{urlencode({'corp_code': code})}"
            results.append(Entity(
                entity_id=code, name=row["corp_name"], jurisdiction="KR", provider=self.name,
                source_url=source_url,
                identifiers=(Identifier("corp_code", code, CORP_CODES),)
                + ((Identifier("stock_code", stock, CORP_CODES),) if stock else ()),
                tickers=(stock,) if stock else (), provider_metadata=row,
                provenance=Provenance(self.name, self.regulator, "KR", CORP_CODES, code,
                                      datetime.now(timezone.utc), row),
            ))
            if len(results) >= limit:
                break
        return results

    def resolve_entity(self, identifier: str) -> Entity:
        value = identifier.strip()
        if re.fullmatch(r"\d{8}", value):
            code = value
        elif re.fullmatch(r"[0-9A-Za-z]{6}", value) and any(c.isdigit() for c in value):
            value = value.upper()
            try:
                code = self._corp_code_for_stock(value)
            except ParseError:
                # The website selector is not a versioned API. Retain the
                # documented registry as a correctness fallback if it changes.
                code = self._registry_code_for_stock(value)
        else:
            raise ValueError("KR identifier must be an eight-digit corporation code or six-character stock code")
        data = self._get_json(COMPANY, {"corp_code": code})
        if not _status(data, no_data_ok=True):
            raise EntityNotFoundError(f"Open DART corporation {code} was not found")
        stock = str(data.get("stock_code") or "").strip()
        if re.fullmatch(r"[0-9A-Z]{6}", value) and stock != value:
            raise ParseError(f"Open DART company profile does not match stock code {value}")
        source_url = f"{COMPANY}?{urlencode({'corp_code': code})}"
        retrieved_at = datetime.now(timezone.utc)
        return Entity(
            entity_id=code,
            name=str(data.get("corp_name") or code),
            jurisdiction="KR",
            provider=self.name,
            source_url=source_url,
            identifiers=(Identifier("corp_code", code, source_url),)
            + ((Identifier("stock_code", stock, source_url),) if stock else ()),
            tickers=(stock,) if stock else (),
            provider_metadata=data,
            provenance=Provenance(self.name, self.regulator, "KR", source_url, code, retrieved_at, data),
        )

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
        if form not in {None, "annual", "interim", "quarterly", "other"}:
            raise ValueError(f"unsupported Open DART filing category {form!r}")
        today = datetime.now(_KST).date()
        params: dict[str, str | int] = {
            "corp_code": entity.entity_id,
            "bgn_de": (start or date(1900, 1, 1)).strftime("%Y%m%d"),
            "end_de": (end or today).strftime("%Y%m%d"),
            "last_reprt_at": "N",
            "sort": "date",
            "sort_mth": "desc",
            "page_count": 100,
        }
        if form in _REPORT_TYPES:
            # Without it Samsung's annual lookup paged through 3,602 disclosures.
            params["pblntf_detail_ty"] = _REPORT_TYPES[form]
        count = 0
        page = 1
        while True:
            data = self._get_json(LIST, {**params, "page_no": page})
            if not _status(data, no_data_ok=True):
                return
            rows = data.get("list")
            if not isinstance(rows, list):
                raise ProviderError("Open DART filing response has no list")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("corp_code") or "") != entity.entity_id:
                    raise ProviderError("Open DART filing response contains another issuer")
                receipt = str(row.get("rcept_no") or "")
                if not re.fullmatch(r"\d{14}", receipt):
                    continue
                title = str(row.get("report_nm") or "")
                category, _ = _category(title)
                if form is not None and category != form:
                    continue
                amendment = bool(_CORRECTION.match(title))
                if amendment and not include_amendments:
                    continue
                filing_date = date.fromisoformat(str(row["rcept_dt"])) if row.get("rcept_dt") else None
                period_end = _period_end(title)
                fiscal = entity.provider_metadata.get("acc_mt")
                fiscal_end = int(fiscal) if str(fiscal or "").isdigit() else None
                report_code = _report_code(category, period_end, fiscal_end)
                viewer = f"{VIEWER}?{urlencode({'rcpNo': receipt})}"
                raw = {**row, "report_code": report_code, "report_code_basis": "title and company fiscal end" if report_code else None}
                provenance = Provenance(self.name, self.regulator, "KR", viewer, receipt, datetime.now(timezone.utc), raw)
                yield Filing(
                    filing_id=receipt,
                    entity_id=entity.entity_id,
                    jurisdiction="KR",
                    provider=self.name,
                    regulator=self.regulator,
                    source_url=viewer,
                    provenance=provenance,
                    filing_type_raw=title,
                    filing_type_normalized=category.upper(),
                    title=title,
                    filing_date=filing_date,
                    period_end=period_end,
                    amendment=amendment,
                    language="ko",
                    provider_metadata=raw,
                    _provider=self,
                )
                count += 1
                if limit is not None and count >= limit:
                    return
            total_pages = int(data.get("total_page") or 1)
            if page >= total_pages:
                return
            page += 1

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        receipt = filing.filing_id
        documents = []
        for kind, url, extra, primary in (
            ("original", DOCUMENT, {"rcept_no": receipt}, True),
            ("xbrl", XBRL, {"rcept_no": receipt, "reprt_code": filing.provider_metadata.get("report_code")}, False),
        ):
            if kind == "xbrl" and not extra["reprt_code"]:
                continue
            safe_url = f"{url}?{urlencode(extra)}"
            documents.append(FilingDocument(
                document_id=f"{receipt}:{kind}",
                filing_id=receipt,
                filename=f"{receipt}-{kind}.zip",
                source_url=safe_url,
                provenance=Provenance(self.name, self.regulator, "KR", safe_url, f"{receipt}:{kind}", raw=filing.provider_metadata),
                media_type="application/zip",
                document_type=kind,
                language="ko",
                is_primary=primary,
                role="report" if kind == "original" else "data",
                provider_metadata={"receipt": receipt, "report_code": extra.get("reprt_code"),
                                   "availability": "unverified", "archive_encoding": "cp949"},
                _provider=self,
            ))
        return documents

    def _document_request(self, document: FilingDocument) -> tuple[str, dict[str, str]]:
        receipt = str(document.provider_metadata.get("receipt") or "")
        if not re.fullmatch(r"\d{14}", receipt):
            raise ValueError("invalid Open DART receipt number")
        if document.document_type == "original":
            endpoint, params = DOCUMENT, {"rcept_no": receipt}
        elif document.document_type == "xbrl":
            code = str(document.provider_metadata.get("report_code") or "")
            if code not in {"11011", "11012", "11013", "11014"}:
                raise ValueError("invalid Open DART XBRL report code")
            endpoint, params = XBRL, {"rcept_no": receipt, "reprt_code": code}
        else:
            raise ValueError("unknown Open DART document type")
        return endpoint, {**params, "crtfc_key": self.api_key}

    def download_document(self, document: FilingDocument) -> bytes:
        endpoint, params = self._document_request(document)
        body = self.transport.get(endpoint, params=params)
        return _zip_or_error(body, source=document.document_type)

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        endpoint, params = self._document_request(document)
        target = Path(path)
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".stage", dir=target.parent)
        os.close(fd)
        staged = Path(name)
        try:
            self.transport.get_to_file(endpoint, staged, params=params)
            with staged.open("rb") as saved:
                signature = saved.read(4)
            if signature != b"PK\x03\x04":
                with staged.open("rb") as saved:
                    _zip_or_error(saved.read(65537), source=document.document_type)
                raise DownloadError(f"Open DART did not return a {document.document_type} ZIP")
            try:
                with zipfile.ZipFile(staged) as archive:
                    if not archive.namelist() or archive.testzip() is not None:
                        raise DownloadError(f"Open DART returned an invalid {document.document_type} ZIP")
            except zipfile.BadZipFile as exc:
                raise DownloadError(f"Open DART returned an invalid {document.document_type} ZIP") from exc
            os.replace(staged, target)
            return target
        finally:
            staged.unlink(missing_ok=True)

    def extract_text(self, document: FilingDocument) -> str:
        if document.document_type != "original":
            return super().extract_text(document)
        chunks = []
        with zipfile.ZipFile(document._archive_source(), metadata_encoding="cp949") as archive:
            for name in sorted(archive.namelist()):
                if not name.lower().endswith((".xml", ".htm", ".html", ".xhtml")):
                    continue
                raw = archive.read(name)
                if name.lower().endswith(".xml"):
                    try:
                        text = " ".join(" ".join(ET.fromstring(raw).itertext()).split())
                    except ET.ParseError:
                        continue
                else:
                    for encoding in ("utf-8-sig", "cp949"):
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
        document = next((item for item in filing.documents if item.document_type == "xbrl"), None)
        if document is None:
            raise UnsupportedCapabilityError(f"Open DART has no qualified XBRL package reference for {filing.filing_id}")
        try:
            source = document._archive_source()
        except DownloadError as exc:
            if "has no xbrl" in str(exc):
                raise UnsupportedCapabilityError(f"Open DART has no XBRL package for {filing.filing_id}") from exc
            raise
        facts = []
        instances = 0
        with zipfile.ZipFile(source, metadata_encoding="cp949") as archive:
            for info in archive.infolist():
                if not info.filename.lower().endswith((".xbrl", ".xml")):
                    continue
                if info.file_size > 50_000_000:
                    raise ParseError(f"Open DART XBRL member {info.filename} exceeds the 50 MB parser limit")
                content = archive.read(info)
                try:
                    root = next(ET.iterparse(io.BytesIO(content), events=("start",)))[1]
                except (ET.ParseError, StopIteration):
                    if info.filename.lower().endswith(".xbrl"):
                        raise ParseError(f"Open DART XBRL member {info.filename} is invalid XML")
                    continue
                if root.tag != _XBRL_ROOT:
                    continue
                instances += 1
                facts.extend(parse_xbrl_instance(
                    content,
                    document_url=document.source_url,
                    entry_path=info.filename,
                    provider=self.name,
                    regulator=self.regulator,
                    jurisdiction="KR",
                    filing_id=filing.filing_id,
                ))
        if not instances:
            raise UnsupportedCapabilityError(f"Open DART package for {filing.filing_id} has no classic XBRL facts")
        return facts
