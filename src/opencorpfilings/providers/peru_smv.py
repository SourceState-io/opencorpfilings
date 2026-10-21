"""Original financial reports from SMV's public main-market issuer selector."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from uuid import UUID

from bs4 import BeautifulSoup

from ..errors import EntityNotFoundError, FilingNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..raw_xbrl import parse_xbrl_instance
from ..transport import HttpTransport
from ._oam import download, require_https_host, save


_HOST = "www.smv.gob.pe"
_BASE = f"https://{_HOST}/SIMV/"
_HOME = _BASE + "Default.aspx"
_PREFIX = "ctl00$MainContent$"
_DOCUMENT_PATH = "/ConsultasP8/documento.aspx"


def _document_id(url: str) -> str:
    require_https_host(url, _HOST, "SMV original-document link is outside its source")
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("vidDoc", [])
    if parsed.path != _DOCUMENT_PATH or len(values) != 1:
        raise ParseError("SMV original-document link is not recognized")
    try:
        return str(UUID(values[0].strip("{}")))
    except ValueError as exc:
        raise ParseError("SMV original-document ID is not a GUID") from exc


class PeruSMVProvider(FilingProvider):
    name = "peru_smv"
    market = "PE"
    regulator = "Superintendencia del Mercado de Valores (SMV)"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download",
                              "pdf", "text", "xbrl", "raw_facts", "streamed_download", "direct_filing_lookup"})
    identifier_kinds = ("SMV issuer selector ID", "exact company name")
    forms = ("annual", "interim", "quarterly")
    native_forms = False
    date_filters = False
    order_basis = "report_year"
    coverage_note = "Main-market issuers' annual/interim reports, consolidated by default; source report-year order. No amendment classification or filing-date filtering."

    def __init__(self, *, transport: HttpTransport | None = None, consolidated: bool = True,
                 max_years: int = 5) -> None:
        if not 1 <= max_years <= 30:
            raise ValueError("max_years must be between 1 and 30")
        self.transport = transport or HttpTransport(min_interval=1.0, timeout=90.0)
        self.balance = "C" if consolidated else "I"
        self.max_years = max_years
        self._url: str | None = None
        self._page: BeautifulSoup | None = None
        self._entities: list[Entity] | None = None
        self._years: list[int] = []
        self._reports: dict[tuple[str, int, str, str], list[Filing]] = {}

    def _registry(self) -> list[Entity]:
        if self._entities is None:
            home = BeautifulSoup(self.transport.get(_HOME).decode("utf-8-sig"), "html.parser")
            # The first financial-information link is under Emisores/Mercado
            # Principal. Later links address other venues and participants.
            anchor = home.select_one('a[href^="Frm_InformacionFinanciera?"]')
            if anchor is None:
                raise ParseError("SMV navigation lacks its main-market financial-information link")
            self._url = urljoin(_BASE, str(anchor["href"]).strip())
            require_https_host(self._url, _HOST, "SMV financial selector is outside its source")
            self._page = BeautifulSoup(self.transport.get(self._url).decode("utf-8-sig"), "html.parser")
            entities = []
            for option in self._page.select("#MainContent_cboDenominacionSocial option[value]"):
                key = str(option["value"])
                name = option.get_text(" ", strip=True)
                if not re.fullmatch(r"\d+", key) or not name:
                    continue
                raw = {"selector_id": key, "registry": "main-market issuer financial selector"}
                entities.append(Entity(key, name, "PE", self.name, self._url,
                    identifiers=(Identifier("SMV issuer selector ID", key, self._url),), provider_metadata=raw,
                    provenance=Provenance(self.name, self.regulator, "PE", self._url, key,
                                          datetime.now(timezone.utc), raw)))
            self._years = sorted({int(str(option["value"]))
                for option in self._page.select("#MainContent_cboAnio option[value]")
                if re.fullmatch(r"\d{4}", str(option["value"])) and int(str(option["value"])) <= date.today().year}, reverse=True)
            if not entities or not self._years:
                raise ParseError("SMV financial selector lacks its issuer or report-year options")
            self._entities = entities
        return self._entities

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        value = query.strip().casefold()
        if not value or limit < 1:
            return []
        return [entity for entity in self._registry() if value in entity.name.casefold() or value == entity.entity_id][:limit]

    def resolve_entity(self, identifier: str) -> Entity:
        value = identifier.strip().casefold()
        matches = [entity for entity in self._registry() if value in {entity.entity_id, entity.name.casefold()}]
        if len(matches) != 1:
            raise EntityNotFoundError("SMV lookup needs one main-market issuer selector ID or exact company name; RUC and tickers are not selector IDs")
        return matches[0]

    @staticmethod
    def _verify_selection(page: BeautifulSoup, entity: Entity, year: int, kind: str, balance: str) -> None:
        for name, expected in [("cboDenominacionSocial", entity.entity_id), ("cboAnio", str(year))]:
            selected = page.select_one(f"#MainContent_{name} option[selected]")
            if selected is None or str(selected.get("value")) != expected:
                raise ProviderError("SMV response does not retain the selected issuer/report year")
        for name, expected in [("cboTipo", balance), ("cboPeriodo", kind)]:
            selected = page.find("input", attrs={"name": _PREFIX + name, "checked": True})
            if selected is None or str(selected.get("value")) != expected:
                raise ProviderError("SMV response does not retain the selected report type/balance")

    def _select(self, entity: Entity, year: int, kind: str, balance: str) -> list[Filing]:
        key = entity.entity_id, year, kind, balance
        if key in self._reports:
            return self._reports[key]
        self._registry()
        # Start each independent selection from fresh public form state. Both
        # the name field and numeric selector are required by the source form.
        page = BeautifulSoup(self.transport.get(self._url, cache=False).decode("utf-8-sig"), "html.parser")
        data = {str(x["name"]): str(x.get("value", "")) for x in page.select('input[type="hidden"][name]')}
        if "__VIEWSTATE" not in data:
            raise ParseError("SMV form lacks its public WebForms state")
        data.update({_PREFIX + "cboDenominacionSocial": entity.entity_id, _PREFIX + "TextBox1": entity.name,
                     _PREFIX + "cboAnio": str(year),
                     _PREFIX + "cboTrimestre": "-1", _PREFIX + "cboTipo": balance, _PREFIX + "cboPeriodo": kind,
                     _PREFIX + "cbBuscar": "Buscar", "__EVENTTARGET": "", "__EVENTARGUMENT": ""})
        page = BeautifulSoup(self.transport.post_form(self._url, data=data).decode("utf-8-sig"), "html.parser")
        self._verify_selection(page, entity, year, kind, balance)
        grid = page.select_one("#MainContent_grdInfoFinanciera")
        if grid is None:
            raise ParseError("SMV response lacks a recognized financial-results table")
        if any("Page$" in str(anchor.get("href", "")) for anchor in grid.select("a[href]")):
            raise ProviderError("SMV financial results are paginated; this route cannot return a truncated selection")
        groups = {}
        for row in grid.select("tr"):
            cells = row.find_all("td", recursive=False)
            quarter = None
            if kind == "T" and len(cells) == 6:
                quarter = cells.pop(0).get_text(strip=True)
                if quarter not in {"I", "II", "III", "IV"}:
                    raise ParseError("SMV interim row has an unrecognized source quarter")
            if len(cells) != 5:
                continue
            if cells[0].get_text(" ", strip=True).casefold() != entity.name.casefold():
                raise ProviderError("SMV financial row belongs to a different issuer name")
            label = cells[1].get_text(" ", strip=True)
            case = cells[2].get_text(strip=True)
            printed = cells[3].get_text(" ", strip=True)
            if not re.fullmatch(r"\d+", case) or not re.match(r"\d{2}/\d{2}/\d{4}\b", printed):
                raise ParseError("SMV financial row lacks a case ID or presentation date")
            filed = datetime.strptime(printed[:10], "%d/%m/%Y").date()
            group = groups.setdefault(case, {"filed": filed, "quarter": quarter, "links": [], "source_times": []})
            if group["filed"] != filed or group["quarter"] != quarter:
                raise ProviderError("SMV case rows disagree on their presentation date or source quarter")
            group["source_times"].append(printed)
            anchor = row.select_one("a[href]")
            if anchor is None:
                continue
            href = urljoin(self._url, str(anchor["href"]).strip())
            if "Frm_DetalleInfoFinanciera" in href:
                continue  # rendered source view, not an original uploaded file
            lower = label.casefold()
            structured = "xbrl" in lower
            primary = (lower.startswith("estados financieros")
                       or lower in {"informacion financiera", "información financiera"})
            notes = lower.startswith("notas a los estados financieros")
            if not (structured or primary or notes):
                continue
            guid = _document_id(href)
            group["links"].append({"url": href, "guid": guid, "label": label, "xbrl": structured, "primary": primary})
        filings = []
        for case, group in groups.items():
            if not any(link["primary"] for link in group["links"]):
                for link in group["links"]:
                    link["primary"] = link["xbrl"]
            if not any(link["primary"] for link in group["links"]):
                raise ParseError("SMV financial case lacks original statements as PDF or XBRL; notes alone are not the full report")
            filing_id = f"{entity.entity_id}:{year}:{kind}:{balance}:{case}"
            raw = {"selector_id": entity.entity_id, "expediente": case, "report_year": year,
                   "source_period": kind, "source_quarter": group["quarter"], "balance": balance, "source_times": group["source_times"],
                   "source_links": group["links"], "filing_id_basis": "issuer, source report-year/type/balance selection and expediente"}
            label = ("Anual" if kind == "A" else "Intermedio") + (" Consolidada" if balance == "C" else " Individual")
            filings.append(Filing(filing_id, entity.entity_id, "PE", self.name, self.regulator, self._url,
                Provenance(self.name, self.regulator, "PE", self._url, case, datetime.now(timezone.utc), raw),
                filing_type_raw=label, filing_type_normalized="ANNUAL" if kind == "A" else "INTERIM",
                title=f"{label} {year} — expediente {case}", filing_date=group["filed"], language="es",
                provider_metadata=raw, _provider=self))
        if not groups and not re.search(r"No se encontraron registros|No (?:existen|hay) (?:registros|informaci[oó]n)|Sin registros", grid.get_text(" ", strip=True), re.I):
            raise ParseError("SMV financial table has no recognized rows or empty-result message")
        result = sorted(filings, key=lambda f: (f.filing_date, f.provenance.source_id), reverse=True)
        self._reports[key] = result
        return result

    def filing_matches_form(self, filing: Filing, requested: str) -> bool:
        return (super().filing_matches_form(filing, requested)
                or requested.upper() == "QUARTERLY" and filing.filing_type_normalized == "INTERIM")

    def iter_filings(self, entity: Entity, *, form: str | None = None, start: date | None = None,
                     end: date | None = None, include_amendments: bool = True,
                     limit: int | None = None) -> Iterator[Filing]:
        if start or end or not include_amendments:
            raise UnsupportedCapabilityError("SMV report-year browsing cannot filter filing dates or classify amendments")
        if form and form.casefold() not in self.forms:
            raise UnsupportedCapabilityError("SMV supports annual and interim (including quarterly) financial reports")
        self._registry()
        kinds = ("A", "T") if not form else ("A",) if form.casefold() == "annual" else ("T",)
        count = 0
        for index, year in enumerate(self._years):
            if index >= self.max_years:
                raise UnsupportedCapabilityError("SMV history reached max_years; increase it or select a filing directly")
            filings = [filing for kind in kinds for filing in self._select(entity, year, kind, self.balance)]
            for filing in sorted(filings, key=lambda f: (f.filing_date, f.provenance.source_id), reverse=True):
                yield filing
                count += 1
                if limit is not None and count >= limit:
                    return

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        match = re.fullmatch(r"(\d+):(\d{4}):([AT]):([CI]):(\d+)", filing_id)
        if match and match[1] == entity.entity_id:
            self._registry()
            if int(match[2]) in self._years:
                for filing in self._select(entity, int(match[2]), match[3], match[4]):
                    if filing.provenance.source_id == match[5]:
                        return filing
        raise FilingNotFoundError("SMV has no selected-issuer case for this report-year/type/balance key")

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        documents = []
        for link in filing.provider_metadata["source_links"]:
            key = _document_id(link["url"])
            documents.append(FilingDocument(key, filing.filing_id, key + (".xbrl" if link["xbrl"] else ".pdf"), link["url"],
                Provenance(self.name, self.regulator, "PE", link["url"], key,
                           raw={"source_label": link["label"], "expediente": filing.provenance.source_id,
                                "filename_basis": "source GUID; the listing supplies no original filename"}),
                media_type="application/xml" if link["xbrl"] else "application/pdf", document_type=link["label"],
                is_primary=link["primary"], language="es", role="data" if link["xbrl"] else "report" if link["primary"] else "exhibit", _provider=self))
        return documents

    def download_document(self, document: FilingDocument) -> bytes:
        _document_id(document.source_url)
        return download(self.transport, document.source_url, label="SMV original report")

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        _document_id(document.source_url)
        return save(self.transport, document.source_url, path, document.media_type, label="SMV original report")

    def raw_facts(self, filing: Filing):
        documents = [document for document in filing.documents if document.media_type == "application/xml"]
        if not documents:
            raise UnsupportedCapabilityError("This SMV case has no original classic XBRL instance")
        facts = []
        for document in documents:
            original = document.download()
            content = original
            encoding = None
            if re.match(br'<\?xml[^>]*encoding=["\']UTF-8["\']', original, re.I):
                try:
                    original.decode("utf-8")
                except UnicodeDecodeError:
                    # Several SMV instances declare UTF-8 but contain single-byte
                    # Spanish names and certificate text. Keep the original intact;
                    # disclose this source-specific decoding on every parsed fact.
                    try:
                        content = original.decode("cp1252").encode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise ParseError("SMV instance is neither declared UTF-8 nor readable Windows-1252") from exc
                    encoding = "windows-1252"
            parsed = parse_xbrl_instance(content, document_url=document.source_url, entry_path="",
                provider=self.name, regulator=self.regulator, jurisdiction="PE", filing_id=filing.filing_id)
            if encoding:
                for fact in parsed:
                    fact.provenance.raw.update(parser_encoding=encoding,
                        encoding_note="Source declares UTF-8 but has invalid UTF-8 bytes; Windows-1252 decoding used for parsing only")
            facts.extend(parsed)
        return facts
