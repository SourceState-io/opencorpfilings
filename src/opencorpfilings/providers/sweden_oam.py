"""Individual reports from Sweden's public Finanscentralen register."""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from ..errors import DownloadError, EntityNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance, _looks_like_markup
from ..provider import FilingProvider
from ..packages import package_facts, package_text
from ..transport import HttpTransport


_HOST = "finanscentralen.fi.se"
_SEARCH = f"https://{_HOST}/search/Search.aspx"
_DETAIL = f"https://{_HOST}/search/ViewCompany2.aspx"
_ORG = re.compile(r"\d{6}-\d{4}\Z")
_TABLES = {
    "ANNUAL": ("ctl00_main_gvwYearReports", "Annual report"),
    "INTERIM": ("ctl00_main_gvwHalfYearReports", "Half-year report (Q2)"),
    "QUARTERLY": ("ctl00_main_gvwQuarterReports", "Quarterly report (Q1 & Q3)"),
}
_LANGUAGES = {"svenska": "sv", "swedish": "sv", "engelska": "en", "english": "en"}


def _file_link(href: str) -> tuple[str, str]:
    url = urljoin(_SEARCH, href)
    parsed = urlparse(url)
    file_ids = parse_qs(parsed.query).get("fid", [])
    if (parsed.scheme != "https" or parsed.hostname != _HOST
            or parsed.path != "/search/GetFile.aspx" or len(file_ids) != 1
            or not file_ids[0].isdecimal()):
        raise ProviderError("Finanscentralen returned an invalid source file link")
    return file_ids[0], url


def _original_format(prefix: bytes, file_id: str) -> tuple[str, str]:
    if prefix.startswith(b"PK\x03\x04"):
        return "application/zip", ".zip"
    if prefix.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if _looks_like_markup(prefix):
        return "application/xhtml+xml", ".xhtml"
    raise DownloadError(f"Finanscentralen file {file_id} has an unrecognized format")


class SwedenOAMProvider(FilingProvider):
    name = "sweden_oam"
    market = "SE"
    regulator = "Finansinspektionen / Finanscentralen"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download",
                              "source_package", "html", "text", "raw_facts", "ixbrl",
                              "streamed_download"})
    identifier_kinds = ("company registration number",)
    forms = ("annual", "interim", "quarterly")
    native_forms = False
    date_filters = False
    coverage_note = "The source gives report-period labels only: no filing date and no period_end."
    order_basis = "report_period_label"

    def __init__(self, *, transport: HttpTransport | None = None,
                 max_search_pages: int = 20, max_report_pages: int = 20) -> None:
        if not 1 <= max_search_pages <= 100:
            raise ValueError("max_search_pages must be between 1 and 100")
        if not 1 <= max_report_pages <= 100:
            raise ValueError("max_report_pages must be between 1 and 100")
        self.transport = transport or HttpTransport(min_interval=1.0, timeout=45.0)
        self.max_search_pages = max_search_pages
        self.max_report_pages = max_report_pages
        self._pages: dict[str, BeautifulSoup] = {}
        self._report_pages: dict[tuple[str, str, int], BeautifulSoup] = {}

    @staticmethod
    def _form_state(page: BeautifulSoup) -> dict[str, str]:
        form = page.select_one("form")
        if form is None:
            raise ParseError("Finanscentralen search page lacks its form")
        data = {str(item["name"]): str(item.get("value", "")) for item in form.select("input[name]")
                if item.get("type") == "hidden"}
        if "__VIEWSTATE" not in data or "__EVENTVALIDATION" not in data:
            raise ParseError("Finanscentralen search form lacks its state tokens")
        return data

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        landing = BeautifulSoup(self.transport.get(_SEARCH), "html.parser")
        data = self._form_state(landing)
        data["ctl00$main$txtCompanyName"] = query
        data["ctl00$main$btnSearch"] = "Sök"
        page = BeautifulSoup(self.transport.post_form(_SEARCH, data=data), "html.parser")
        direct = page.select_one("#ctl00_main_lblOrganizationNumberValue")
        if direct is not None:
            org_number = direct.get_text(" ", strip=True)
            name_node = page.select_one("#ctl00_main_lblCompanyName")
            name = name_node.get_text(" ", strip=True) if name_node else ""
            if not _ORG.fullmatch(org_number) or not name:
                raise ParseError("Finanscentralen issuer search has an invalid direct company detail")
            lei_node = page.select_one("#ctl00_main_lblLEIValue")
            lei = lei_node.get_text(" ", strip=True) if lei_node else ""
            identifiers = [Identifier("Swedish company registration number", org_number, _SEARCH)]
            if lei:
                identifiers.append(Identifier("LEI", lei, _SEARCH))
            raw = {"search_query": query, "source_page": 1, "result_layout": "direct_company_detail",
                   "organization_number": org_number, "lei": lei or None}
            self._pages[org_number] = page
            return [Entity(
                entity_id=org_number, name=name, jurisdiction="SE", provider=self.name,
                source_url=_SEARCH, identifiers=tuple(identifiers), provider_metadata=raw,
                provenance=Provenance(self.name, self.regulator, "SE", _SEARCH, org_number,
                                      datetime.now(timezone.utc), raw),
            )]
        found: list[Entity] = []
        seen: set[str] = set()
        for page_number in range(1, self.max_search_pages + 1):
            table = page.select_one("#ctl00_main_dgrInstitutes")
            if table is None:
                raise ParseError("Finanscentralen issuer search lacks its result table")
            no_match = False
            for row in table.select("tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) == 1 and "kningen gav ingen tr" in cells[0].get_text(" ", strip=True):
                    no_match = True
                    continue
                if len(cells) != 2:
                    continue
                anchor = cells[0].select_one('a[id$="_lnkInstitute"]')
                if anchor is None:
                    continue
                name = anchor.get_text(" ", strip=True)
                org_number = cells[1].get_text(" ", strip=True)
                if not name or not _ORG.fullmatch(org_number):
                    raise ParseError("Finanscentralen issuer search has an invalid result row")
                if org_number in seen:
                    continue
                seen.add(org_number)
                raw = {"search_query": query, "source_page": page_number}
                found.append(Entity(
                    entity_id=org_number, name=name, jurisdiction="SE", provider=self.name,
                    source_url=_SEARCH,
                    identifiers=(Identifier("Swedish company registration number", org_number, _SEARCH),),
                    provider_metadata=raw,
                    provenance=Provenance(self.name, self.regulator, "SE", _SEARCH, org_number,
                                          datetime.now(timezone.utc), raw),
                ))
                if len(found) >= limit:
                    return found
            if no_match:
                return found
            next_link = table.select_one('a[href*="Page$Next"]')
            if next_link is None:
                if not found:
                    raise ParseError("Finanscentralen issuer search has no recognized results")
                return found
            if page_number == self.max_search_pages:
                raise UnsupportedCapabilityError(
                    "Finanscentralen issuer search reached its page bound; narrow the query or increase max_search_pages")
            data = self._form_state(page)
            data["__EVENTTARGET"] = "ctl00$main$dgrInstitutes"
            data["__EVENTARGUMENT"] = "Page$Next"
            page = BeautifulSoup(self.transport.post_form(_SEARCH, data=data), "html.parser")
        return found

    def _company_page(self, org_number: str) -> BeautifulSoup:
        if org_number in self._pages:
            return self._pages[org_number]
        landing = BeautifulSoup(self.transport.get(_SEARCH), "html.parser")
        data = self._form_state(landing)
        data["ctl00$main$txtOrganizationNumber"] = org_number
        data["ctl00$main$btnSearch"] = "Sök"
        page = BeautifulSoup(self.transport.post_form(_SEARCH, data=data), "html.parser")
        actual = page.select_one("#ctl00_main_lblOrganizationNumberValue")
        if actual is None:
            raise EntityNotFoundError(f"Finanscentralen has no exact company registration number {org_number}")
        if actual.get_text(" ", strip=True) != org_number:
            raise ProviderError("Finanscentralen search returned a different company")
        self._pages[org_number] = page
        return page

    def resolve_entity(self, identifier: str) -> Entity:
        org_number = identifier.strip()
        if not _ORG.fullmatch(org_number):
            raise EntityNotFoundError("Sweden OAM lookup requires a company registration number, e.g. 502017-7753")
        page = self._company_page(org_number)
        name = page.select_one("#ctl00_main_lblCompanyName")
        if name is None or not name.get_text(" ", strip=True):
            raise ParseError("Finanscentralen company page lacks its issuer name")
        lei = page.select_one("#ctl00_main_lblLEIValue")
        identifiers = [Identifier("Swedish company registration number", org_number, _SEARCH)]
        if lei and lei.get_text(" ", strip=True):
            identifiers.append(Identifier("LEI", lei.get_text(" ", strip=True), _SEARCH))
        raw = {"organization_number": org_number, "lei": identifiers[-1].value if len(identifiers) > 1 else None,
               "lookup_method": "exact public registration-number form"}
        return Entity(
            entity_id=org_number, name=name.get_text(" ", strip=True), jurisdiction="SE",
            provider=self.name, source_url=_SEARCH, identifiers=tuple(identifiers),
            provider_metadata=raw,
            provenance=Provenance(self.name, self.regulator, "SE", _SEARCH, org_number,
                                  datetime.now(timezone.utc), raw),
        )

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        if not include_amendments:
            raise UnsupportedCapabilityError("Finanscentralen report history is not classified for amendment filtering")
        if start is not None or end is not None:
            raise UnsupportedCapabilityError("Finanscentralen report tables give a period label but no exact filing date")
        requested = form.upper() if form else None
        if requested == "HALF-YEAR":
            requested = "INTERIM"
        if requested not in {None, *_TABLES}:
            raise UnsupportedCapabilityError("Sweden OAM supports annual, interim and quarterly report tables")
        page = self._company_page(entity.entity_id)
        rows: list[tuple[date, int, Filing]] = []
        for kind, (table_id, label) in _TABLES.items():
            if requested is not None and kind != requested:
                continue
            current_page = page
            period_filings: dict[str, Filing] = {}
            repeats: dict[str, int] = {}
            for page_number in range(1, self.max_report_pages + 1):
                table = current_page.select_one(f"table[id={table_id}]")
                if table is None:
                    raise ParseError(f"Finanscentralen company page lacks {label} table")
                last_period: str | None = None
                for tr in table.select("tr"):
                    cells = tr.select("td")
                    if len(cells) < 2:
                        continue
                    links = []
                    for anchor in cells[1].select("a[href]"):
                        if "GetFile.aspx" not in str(anchor.get("href", "")):
                            continue
                        fid, url = _file_link(str(anchor["href"]))
                        language_label = anchor.get_text(" ", strip=True)
                        links.append({"fid": fid, "url": url, "language_raw": language_label,
                                      "language": _LANGUAGES.get(language_label.casefold())})
                    if not links:
                        continue
                    period = cells[0].get_text(" ", strip=True)
                    last_period = period
                    existing = period_filings.get(period)
                    repeat = 1
                    if existing is not None:
                        source_links = existing.provider_metadata["source_links"]
                        old_languages = {link["language_raw"].casefold() for link in source_links}
                        new_languages = {link["language_raw"].casefold() for link in links}
                        if not (old_languages & new_languages or len(new_languages) != len(links)):
                            source_links.extend(links)
                            existing.provider_metadata["source_file_ids"].extend(link["fid"] for link in links)
                            continue
                        # A second row repeating a language for one period (Sandvik's 2024
                        # half-year report appears twice) is kept as its own record, never merged.
                        repeat = repeats[period] = repeats.get(period, 1) + 1
                        existing.provider_metadata["repeated_period"] = True
                    try:
                        if kind == "QUARTERLY":
                            year, month = (int(part) for part in period.split("-"))
                            if month not in {3, 9}:
                                raise ValueError("unexpected quarter")
                        else:
                            year, month = int(period), (12 if kind == "ANNUAL" else 6)
                        period_sort = date(year, month, 31 if month in {3, 12} else 30)
                    except (ValueError, TypeError) as exc:
                        raise ParseError(f"Finanscentralen returned invalid {label} period {period!r}") from exc
                    filing_id = f"{entity.entity_id}:{kind.lower()}:{period}" + (f":{repeat}" if repeat > 1 else "")
                    # The table groups language links, but has no separate filing ID or publication date.
                    raw = {"organization_number": entity.entity_id, "report_period_raw": period,
                           "report_table": table_id, "source_category": label,
                           "source_file_ids": [link["fid"] for link in links],
                           "source_links": links, "filing_id_basis": "library grouping of source report class and period",
                           "repeated_period": repeat > 1}
                    filing = Filing(
                        filing_id=filing_id, entity_id=entity.entity_id, jurisdiction="SE",
                        provider=self.name, regulator=self.regulator, source_url=links[0]["url"],
                        provenance=Provenance(self.name, self.regulator, "SE", links[0]["url"],
                                              links[0]["fid"], datetime.now(timezone.utc), raw),
                        filing_type_raw=label, filing_type_normalized=kind,
                        title=f"{label} {period}",
                        amendment=None, provider_metadata=raw, _provider=self,
                    )
                    period_filings[period] = filing
                    rows.append((period_sort, -len(rows), filing))
                event_target = "ctl00$main$" + table_id.removeprefix("ctl00_main_")
                has_next = any(event_target in str(a.get("href", "")) and "Page$Next" in str(a.get("href", ""))
                               for a in table.select("a[href]"))
                # The page break can split language links for one report period.
                # Read the next page while its first rows may extend a selected filing.
                if (limit is not None and len(period_filings) >= limit
                        and last_period not in list(period_filings)[:limit]):
                    break
                if not has_next:
                    break
                if page_number == self.max_report_pages:
                    raise UnsupportedCapabilityError(
                        "Finanscentralen report history reached its page bound; increase max_report_pages")
                key = (entity.entity_id, kind, page_number + 1)
                if key in self._report_pages:
                    current_page = self._report_pages[key]
                    continue
                form_node = current_page.select_one("form")
                if form_node is None or urljoin(_SEARCH, str(form_node.get("action", ""))) != _DETAIL:
                    raise ParseError("Finanscentralen report page lacks its expected detail form")
                data = self._form_state(current_page)
                data["__EVENTTARGET"] = event_target
                data["__EVENTARGUMENT"] = "Page$Next"
                next_page = BeautifulSoup(self.transport.post_form(_DETAIL, data=data), "html.parser")
                actual = next_page.select_one("#ctl00_main_lblOrganizationNumberValue")
                if actual is None or actual.get_text(" ", strip=True) != entity.entity_id:
                    raise ProviderError("Finanscentralen report page returned a different company")
                self._report_pages[key] = next_page
                current_page = next_page
        # Newest period first; within one period, the source's own row order.
        rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _, _, filing in rows[:limit]:
            yield filing

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        result: list[FilingDocument] = []
        for link in filing.provider_metadata.get("source_links", []):
            fid, url = _file_link(link["url"])
            result.append(FilingDocument(
                document_id=fid, filing_id=filing.filing_id,
                filename=f"Finanscentralen-{fid}", source_url=url,
                provenance=Provenance(self.name, self.regulator, "SE", url, fid,
                                      raw={"report_period": filing.provider_metadata.get("report_period_raw"),
                                           "language_label": link["language_raw"]}),
                document_type="original_oam_file", language=link["language"],
                is_primary=not result, provider_metadata={"language_label": link["language_raw"],
                                                        "format_discovered_on_download": True}, _provider=self,
            ))
        return result

    def download_document(self, document: FilingDocument) -> bytes:
        file_id, url = _file_link(document.source_url)
        if file_id != document.document_id:
            raise DownloadError("Finanscentralen source file ID differs from the selected document")
        try:
            content = self.transport.get(url, cache=False)
        except ProviderError as exc:
            raise DownloadError(f"Finanscentralen file failed: {exc}") from exc
        media_type, suffix = _original_format(content[:1024], document.document_id)
        if media_type == "application/zip":
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    archive.infolist()
            except zipfile.BadZipFile as exc:
                raise DownloadError(f"Finanscentralen file {document.document_id} is an invalid ZIP") from exc
        document.media_type = media_type
        document.filename = str(Path(document.filename).with_suffix(suffix))
        return content

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        file_id, url = _file_link(document.source_url)
        if file_id != document.document_id:
            raise DownloadError("Finanscentralen source file ID differs from the selected document")
        target = Path(path)
        fd, staged_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".stage", dir=target.parent)
        os.close(fd)
        staged = Path(staged_name)
        try:
            try:
                self.transport.get_to_file(url, staged)
            except ProviderError as exc:
                raise DownloadError(f"Finanscentralen file failed: {exc}") from exc
            with staged.open("rb") as saved:
                media_type, suffix = _original_format(saved.read(1024), document.document_id)
            if media_type == "application/zip":
                try:
                    with zipfile.ZipFile(staged) as archive:
                        archive.infolist()
                except zipfile.BadZipFile as exc:
                    raise DownloadError(f"Finanscentralen file {document.document_id} is an invalid ZIP") from exc
            os.replace(staged, target)
            document.media_type = media_type
            document.filename = str(Path(document.filename).with_suffix(suffix))
            return target
        finally:
            staged.unlink(missing_ok=True)

    def extract_text(self, document: FilingDocument) -> str:
        if document.media_type is None:
            document.download()  # the format is learned from the original
        return package_text(document, label="Finanscentralen")

    def raw_facts(self, filing: Filing):
        for document in filing.documents:
            if document.media_type is None:
                document.download()
        return package_facts(filing, name=self.name, regulator=self.regulator, jurisdiction="SE", label="Finanscentralen")
