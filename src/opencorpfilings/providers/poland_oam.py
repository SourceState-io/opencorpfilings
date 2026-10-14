"""Source reports and original nested packages from Poland's KNF OAM."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from ..errors import AmbiguousEntityError, DownloadError, EntityNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..packages import package_facts, package_text
from ..transport import HttpTransport
from . import _oam


_BASE = "https://moam.knf.gov.pl/moam.nsf/"
_SEARCH = urljoin(_BASE, "search")
_ANNUAL = frozenset({"RR", "SRR", "SRR-I"})
_ID = re.compile(r"/moam\.nsf/0/([A-F0-9]{32})\Z")
_PL_TIME = "%m/%d/%Y %I:%M:%S %p"


def _checked_record_url(href: str) -> tuple[str, str]:
    url = urljoin(_BASE, href)
    parsed = urlparse(url)
    match = _ID.fullmatch(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "moam.knf.gov.pl" or match is None:
        raise ProviderError("KNF OAM returned an invalid source report URL")
    return match.group(1), url


def _checked_launch_url(href: str) -> str:
    url = urljoin(_BASE, href)
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if parsed.scheme != "https" or parsed.hostname != "moam.knf.gov.pl" or parsed.path != "/moam.nsf/AppForm":
        raise ProviderError("KNF OAM returned an invalid report launcher URL")
    if not all(query.get(key) for key in ("rok", "kat", "plik")):
        raise ProviderError("KNF OAM launcher lacks its report path parameters")
    return url


def _source_detail(content: bytes) -> dict[str, str]:
    soup = BeautifulSoup(content, "html.parser")
    result: dict[str, str] = {}
    for strong in soup.select("strong"):
        key = strong.get_text(" ", strip=True).rstrip(":")
        cell = strong.find_parent("td")
        siblings = cell.find_next_siblings("td") if cell else []
        if siblings:
            result[key] = siblings[-1].get_text(" ", strip=True)
            if key == "Plik raportu":
                anchor = siblings[-1].select_one("a[href]")
                if anchor:
                    result["launcher_url"] = _checked_launch_url(str(anchor["href"]))
    for key in ("Emitent", "Nazwa raportu", "Data odebrania", "Rok", "Korekta", "launcher_url"):
        if not result.get(key):
            raise ParseError(f"KNF OAM report detail lacks {key}")
    return result


class PolandOAMProvider(FilingProvider):
    name = "poland_oam"
    market = "PL"
    regulator = "Polish Financial Supervision Authority / KNF OAM"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download", "streamed_download",
                              "source_package", "html", "text", "raw_facts", "ixbrl"})
    identifies_amendments = True
    identifier_kinds = ("exact source issuer name",)
    forms = ("annual",)
    native_forms = False
    coverage_note = ("annual includes standalone (RR) and consolidated (SRR) reports; filing_type_raw "
                     "tells them apart. A KNF package holds several documents; text() reads the ESEF-named "
                     "report when there is one, otherwise the largest (often the management report). "
                     "Standalone reports carry no XBRL tags.")
    order_basis = "source_search_order"

    def __init__(self, *, transport: HttpTransport | None = None, max_pages: int = 20) -> None:
        if not 1 <= max_pages <= 100:
            raise ValueError("max_pages must be between 1 and 100")
        self.transport = transport or HttpTransport(min_interval=0.5)
        self.max_pages = max_pages

    def _search(self, name: str, page: int) -> list[dict[str, str]]:
        if page < 1:
            raise ValueError("page must be positive")
        content = self.transport.get(_SEARCH, params={
            "OpenNavigator": "", "Field": "NazwaPodmiot", "Value": name,
            "start": 1 + (page - 1) * 20, "count": 20,
        })
        soup = BeautifulSoup(content, "html.parser")
        table = soup.select_one("table.edittable")
        if table is None:
            if "Nie znaleziono dokument" in soup.get_text(" ", strip=True):
                return []
            raise ParseError("KNF OAM search lacks its results table")
        rows: list[dict[str, str]] = []
        for tr in table.select("tr"):
            cells = tr.select("td")
            if len(cells) != 4:
                continue
            title_link = cells[2].select_one("a[href]")
            launch_link = cells[3].select_one("a[href]")
            if title_link is None or launch_link is None:
                raise ParseError("KNF OAM report row lacks record or file link")
            filing_id, record_url = _checked_record_url(str(title_link["href"]))
            launcher_url = _checked_launch_url(str(launch_link["href"]))
            date_raw = cells[1].get_text(" ", strip=True)
            try:
                date.fromisoformat(date_raw)
            except ValueError as exc:
                raise ParseError(f"KNF OAM returned invalid receipt date {date_raw!r}") from exc
            title_raw = title_link.get_text(" ", strip=True)
            rows.append({"name": cells[0].get_text(" ", strip=True), "date": date_raw,
                         "title": title_raw, "form_raw": title_raw.split(",", 1)[0].strip(),
                         "filing_id": filing_id, "record_url": record_url,
                         "launcher_url": launcher_url})
        return rows

    def _entity(self, name: str, *, first_page_count: int | None = None,
                search_page_scope: str | None = None) -> Entity:
        source_url = f"{_SEARCH}?{urlencode({'OpenNavigator': '', 'Field': 'NazwaPodmiot', 'Value': name})}"
        raw = {"identity_basis": "exact source issuer name", "search_name": name}
        if first_page_count is not None:
            raw["first_page_count"] = first_page_count
        if search_page_scope is not None:
            raw["search_page_scope"] = search_page_scope
        return Entity(
            entity_id=name, name=name, jurisdiction="PL", provider=self.name,
            source_url=source_url, identifiers=(Identifier("KNF OAM issuer name", name, source_url),),
            provider_metadata=raw,
            provenance=Provenance(self.name, self.regulator, "PL", source_url, name,
                                  datetime.now(timezone.utc), raw),
        )

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        if len(query) > 200:
            raise ValueError("KNF OAM issuer search exceeds 200 characters")
        seen: set[str] = set()
        results: list[Entity] = []
        for row in self._search(query, 1):
            name = row["name"]
            if not name:
                raise ParseError("KNF OAM report row lacks an issuer name")
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            results.append(self._entity(name, search_page_scope="first_page"))
            if len(results) >= limit:
                break
        return results

    def resolve_entity(self, identifier: str) -> Entity:
        requested = identifier.strip()
        if not requested or len(requested) > 200:
            raise EntityNotFoundError("KNF OAM lookup requires an exact source issuer name")
        rows = self._search(requested, 1)
        matches = sorted({row["name"] for row in rows if row["name"].casefold() == requested.casefold()})
        if not matches:
            names = sorted({row["name"] for row in rows})
            if len(names) > 1:
                raise AmbiguousEntityError(
                    f"KNF OAM search for {requested!r} matches multiple issuers; use the exact source name"
                )
            raise EntityNotFoundError(f"KNF OAM has no exact issuer name {requested!r} on the first search page")
        return self._entity(matches[0], first_page_count=len(rows))

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        requested = form.lower() if form is not None else None
        if requested is not None and requested != "annual":
            raise UnsupportedCapabilityError("KNF OAM currently verifies only an annual convenience mapping")
        seen: set[str] = set()
        yielded = 0
        for page in range(1, self.max_pages + 1):
            rows = self._search(entity.entity_id, page)
            if not rows:
                return
            for row in rows:
                when = date.fromisoformat(row["date"])
                if start is not None and when < start:
                    return
                if row["name"].casefold() != entity.name.casefold():
                    continue
                if end is not None and when > end:
                    continue
                if requested == "annual" and row["form_raw"] not in _ANNUAL:
                    continue
                filing_id = row["filing_id"]
                if filing_id in seen:
                    raise ProviderError(f"KNF OAM repeated report {filing_id}")
                seen.add(filing_id)
                detail = _source_detail(self.transport.get(row["record_url"]))
                if detail["Emitent"].casefold() != entity.name.casefold():
                    raise ProviderError("KNF OAM detail has a different issuer")
                if detail["Nazwa raportu"] != row["form_raw"]:
                    raise ProviderError("KNF OAM detail has a different report form")
                if detail["launcher_url"] != row["launcher_url"]:
                    raise ProviderError("KNF OAM detail has a different report launcher")
                amendment_raw = detail["Korekta"].casefold()
                amendment = True if amendment_raw == "tak" else False if amendment_raw == "nie" else None
                # Only a flagged correction is excluded; an unrecognized flag keeps the row (as France does).
                if not include_amendments and amendment:
                    continue
                try:
                    received = datetime.strptime(detail["Data odebrania"], _PL_TIME)
                except ValueError as exc:
                    raise ParseError("KNF OAM detail has an invalid local receipt time") from exc
                if received.date() != when:
                    raise ProviderError("KNF OAM search and detail receipt dates differ")
                raw = {**row, **detail, "receipt_time_local": detail["Data odebrania"],
                       "receipt_timezone_assumption": None}
                yield Filing(
                    filing_id=filing_id, entity_id=entity.entity_id, jurisdiction="PL",
                    provider=self.name, regulator=self.regulator,
                    source_url=row["record_url"],
                    provenance=Provenance(self.name, self.regulator, "PL", row["record_url"],
                                          filing_id, datetime.now(timezone.utc), raw),
                    filing_type_raw=row["form_raw"],
                    filing_type_normalized="ANNUAL" if row["form_raw"] in _ANNUAL else None,
                    title=row["title"], filing_date=when, amendment=amendment,
                    provider_metadata=raw, _provider=self,
                )
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
        raise UnsupportedCapabilityError(
            f"KNF OAM search reached its {self.max_pages}-page safety bound; set a narrower date range or higher max_pages"
        )

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        launcher_url = _checked_launch_url(str(filing.provider_metadata["launcher_url"]))
        content = self.transport.get(launcher_url)
        if len(content) > 2_000_000:
            raise ParseError("KNF OAM launcher exceeds 2 MB")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ParseError("KNF OAM launcher is not valid JNLP XML") from exc
        args = [item.text or "" for item in root.iter() if item.tag.rsplit("}", 1)[-1] == "argument"]
        if "-reportPath" not in args or args.index("-reportPath") + 1 >= len(args):
            raise ParseError("KNF OAM launcher lacks an original report path")
        url = args[args.index("-reportPath") + 1]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "moam.knf.gov.pl" or not parsed.path.startswith("/mOAM/") or not parsed.path.endswith(".zip"):
            raise ProviderError("KNF OAM launcher points outside the original report store")
        filename = PurePosixPath(parsed.path).name
        return [FilingDocument(
            document_id=f"{filing.filing_id}:{filename}", filing_id=filing.filing_id,
            filename=filename, source_url=url,
            provenance=Provenance(self.name, self.regulator, "PL", url,
                                  f"{filing.filing_id}:{filename}",
                                  raw={"record_url": filing.source_url, "launcher_url": launcher_url}),
            media_type="application/zip", document_type="KNF_original_report_package",
            is_primary=True, provider_metadata={"launcher_url": launcher_url,
                                                "report_year_raw": filing.provider_metadata["Rok"]},
            _provider=self,
        )]

    def download_document(self, document: FilingDocument) -> bytes:
        parsed = urlparse(document.source_url)
        if parsed.scheme != "https" or parsed.hostname != "moam.knf.gov.pl" or not parsed.path.startswith("/mOAM/"):
            raise DownloadError("KNF original report URL is outside its HTTPS source host")
        return _oam.download(self.transport, document.source_url, label="KNF original report")

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        parsed = urlparse(document.source_url)
        if parsed.scheme != "https" or parsed.hostname != "moam.knf.gov.pl" or not parsed.path.startswith("/mOAM/"):
            raise DownloadError("KNF original report URL is outside its HTTPS source host")
        return _oam.save(self.transport, document.source_url, path, document.media_type, label="KNF original report")

    def extract_text(self, document: FilingDocument) -> str:
        return package_text(document, label="KNF")

    def raw_facts(self, filing: Filing):
        return package_facts(filing, name=self.name, regulator=self.regulator, jurisdiction="PL", label="KNF")
