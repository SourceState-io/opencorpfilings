"""Original IFRS financial reports from Chile's public CMF issuer portal."""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from ..errors import EntityNotFoundError, FilingNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..raw_xbrl import parse_xbrl_instance
from ..transport import HttpTransport
from ._oam import download, require_https_host, save


_HOST = "www.cmfchile.cl"
_BASE = f"https://{_HOST}/institucional/mercados/"
_REGISTRY = _BASE + "consulta.php?mercado=V&Estado=VI&entidad=RVEMI"
_DOWNLOAD_PATH = "/institucional/inc/inf_financiera/ifrs/safec_ifrs_verarchivo.php"


def _report_url(rut: str) -> str:
    return _BASE + "entidad.php?" + urlencode({"mercado": "V", "rut": rut, "tipoentidad": "RVEMI",
                                             "vig": "VI", "control": "svs", "pestania": "3"})


def _document_url(url: str) -> str:
    require_https_host(url, _HOST, "CMF document link is outside the original source")
    if urlparse(url).path != _DOWNLOAD_PATH:
        raise ProviderError("CMF document link has an unexpected path")
    return url


class ChileCMFProvider(FilingProvider):
    name = "chile_cmf"
    market = "CL"
    regulator = "Comisión para el Mercado Financiero (CMF)"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download",
                              "pdf", "text", "xbrl", "raw_facts", "source_package",
                              "streamed_download", "direct_filing_lookup"})
    identifier_kinds = ("RUT", "exact company name")
    forms = ("annual", "interim", "quarterly")
    native_forms = False
    date_filters = False
    order_basis = "report_period"
    coverage_note = "Active securities issuers' IFRS reports, consolidated by default. No filing date or amendment classification."

    def __init__(self, *, transport: HttpTransport | None = None, consolidated: bool = True,
                 max_periods: int = 20) -> None:
        if not 1 <= max_periods <= 100:
            raise ValueError("max_periods must be between 1 and 100")
        self.transport = transport or HttpTransport(min_interval=1.0, timeout=60.0)
        self.balance = "C" if consolidated else "I"
        self.max_periods = max_periods
        self._entities: list[Entity] | None = None
        self._years: dict[str, list[int]] = {}
        self._reports: dict[str, Filing | None] = {}

    def _registry(self) -> list[Entity]:
        if self._entities is None:
            page = BeautifulSoup(self.transport.get(_REGISTRY), "html.parser")
            entities = []
            for row in page.select("tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) < 2:
                    continue
                rut = cells[0].get_text(" ", strip=True).upper()
                link = cells[0].select_one('a[href*="entidad.php"]')
                if link is None or not re.fullmatch(r"\d{5,8}-[\dK]", rut):
                    continue
                body = rut.split("-")[0]
                source_url = urljoin(_BASE, str(link["href"]))
                parsed = urlparse(source_url)
                if (parsed.hostname != _HOST or parsed.scheme != "https"
                        or parse_qs(parsed.query).get("rut") != [body]):
                    raise ParseError("CMF registry link disagrees with its issuer RUT")
                raw = {"rut": rut, "registry": "active securities issuers"}
                entities.append(Entity(
                    body, cells[1].get_text(" ", strip=True), "CL", self.name, source_url,
                    identifiers=(Identifier("RUT", rut, _REGISTRY),), provider_metadata=raw,
                    provenance=Provenance(self.name, self.regulator, "CL", _REGISTRY, body,
                                          datetime.now(timezone.utc), raw),
                ))
            if not entities:
                raise ParseError("CMF registry has no recognized issuer rows")
            self._entities = entities
        return self._entities

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        query = query.strip().casefold()
        if not query or limit < 1:
            return []
        return [entity for entity in self._registry() if query in entity.name.casefold()
                or query in {entity.entity_id, entity.provider_metadata["rut"].casefold()}][:limit]

    def resolve_entity(self, identifier: str) -> Entity:
        value = identifier.strip().replace(".", "").casefold()
        matches = [entity for entity in self._registry()
                   if value in {entity.entity_id, entity.provider_metadata["rut"].casefold()}
                   or identifier.strip().casefold() == entity.name.casefold()]
        if len(matches) != 1:
            raise EntityNotFoundError("CMF lookup needs one listed RUT or exact active securities issuer name")
        return matches[0]

    def _available_years(self, entity: Entity) -> list[int]:
        if entity.entity_id not in self._years:
            page = BeautifulSoup(self.transport.get(_report_url(entity.entity_id)), "html.parser")
            self._verify_issuer(page, entity)
            years = [int(str(option["value"])) for option in page.select('form#fm select[name="aa"] option[value]')
                     if re.fullmatch(r"\d{4}", str(option["value"]))]
            if not years:
                raise ParseError("CMF IFRS selector lacks its report years")
            self._years[entity.entity_id] = sorted(set(years), reverse=True)
        return self._years[entity.entity_id]

    @staticmethod
    def _verify_issuer(page: BeautifulSoup, entity: Entity) -> None:
        identity = page.select_one("#datos_ent")
        expected = entity.provider_metadata["rut"]
        if identity is None or expected not in re.findall(r"\d{5,8}-[\dKk]", identity.get_text(" ", strip=True)):
            raise ProviderError("CMF response does not identify the selected issuer RUT")

    def _report(self, entity: Entity, year: int, month: int, balance: str) -> Filing | None:
        key = f"{entity.entity_id}:{year}{month:02d}:{balance}"
        if key in self._reports:
            return self._reports[key]
        data = {"forma": "F", "mm": f"{month:02d}", "aa": str(year), "tipo": balance, "tipo_norma": "IFRS"}
        url = _report_url(entity.entity_id)
        page = BeautifulSoup(self.transport.post_form(url, data=data), "html.parser")
        content = page.select_one("#contenido")
        text = content.get_text(" ", strip=True) if content else ""
        self._verify_issuer(page, entity)
        if re.search(r"No existe informaci[oó]n (?:de la entidad )?para el per[ií]odo (?:seleccionado|señalado)", text, re.I):
            self._reports[key] = None
            return None
        printed = re.search(r"Per[ií]odo\s*:?\s*(\d{1,2})\s*/\s*(\d{4})", text, re.I)
        expected_balance = "CONSOLIDADO" if balance == "C" else "INDIVIDUAL"
        if (printed is None or (int(printed[2]), int(printed[1])) != (year, month)
                or not re.search(r"Tipo de Balance\s*:?\s*" + expected_balance, text, re.I)):
            raise ProviderError("CMF response period or balance differs from the selected report")
        links = []
        seen = set()
        for anchor in content.select("a[href]"):
            href = urljoin(url, str(anchor["href"]))
            if "safec_ifrs_verarchivo.php" not in href:
                continue
            _document_url(href)
            if href in seen:
                continue
            seen.add(href)
            label = anchor.get_text(" ", strip=True)
            xbrl = "(XBRL)" in label.upper()
            primary = "ESTADOS FINANCIEROS (PDF)" in label.upper()
            links.append({"url": href, "label": label, "xbrl": xbrl, "primary": primary})
        if not links or not any(link["primary"] for link in links):
            raise ParseError("CMF IFRS report lacks its original financial statements PDF link")
        raw = {"rut": entity.provider_metadata["rut"], "request_form": data,
               "report_period": f"{year}-{month:02d}", "balance": balance, "source_links": links,
               "filing_id_basis": "public portal issuer, report period and balance selection"}
        filing = Filing(
            key, entity.entity_id, "CL", self.name, self.regulator, url,
            Provenance(self.name, self.regulator, "CL", url, key, datetime.now(timezone.utc), raw),
            filing_type_raw="IFRS " + expected_balance,
            filing_type_normalized="ANNUAL" if month == 12 else "INTERIM" if month == 6 else "QUARTERLY",
            title=f"IFRS {expected_balance.lower()} {year}-{month:02d}",
            period_end=date(year, month, calendar.monthrange(year, month)[1]), language="es",
            provider_metadata=raw, _provider=self,
        )
        self._reports[key] = filing
        return filing

    def filing_matches_form(self, filing: Filing, requested: str) -> bool:
        return (super().filing_matches_form(filing, requested)
                or requested.upper() == "QUARTERLY" and filing.filing_type_normalized == "INTERIM")

    def iter_filings(self, entity: Entity, *, form: str | None = None, start: date | None = None,
                     end: date | None = None, include_amendments: bool = True,
                     limit: int | None = None) -> Iterator[Filing]:
        if start or end or not include_amendments:
            raise UnsupportedCapabilityError("CMF reports have no filing-date or amendment classification")
        months = {None: (12, 9, 6, 3), "annual": (12,), "interim": (6,), "quarterly": (9, 6, 3)}
        requested = form.casefold() if form else None
        if requested not in months:
            raise UnsupportedCapabilityError("CMF supports annual, interim and quarterly IFRS reports")
        today = date.today()
        count = checked = 0
        for year in self._available_years(entity):
            for month in months[requested]:
                if date(year, month, calendar.monthrange(year, month)[1]) > today:
                    continue
                if checked >= self.max_periods:
                    raise UnsupportedCapabilityError("CMF report history reached max_periods; increase it or select a filing directly")
                checked += 1
                filing = self._report(entity, year, month, self.balance)
                if filing is None:
                    continue
                yield filing
                count += 1
                if limit is not None and count >= limit:
                    return

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        match = re.fullmatch(r"(\d{5,8}):(\d{4})(03|06|09|12):([CI])", filing_id)
        if match and match[1] == entity.entity_id and 2001 <= int(match[2]) <= date.today().year:
            filing = self._report(entity, int(match[2]), int(match[3]), match[4])
            if filing is not None:
                return filing
        raise FilingNotFoundError(f"CMF has no selected-issuer report {filing_id!r}")

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        documents = []
        for index, link in enumerate(filing.provider_metadata["source_links"]):
            url = _document_url(link["url"])
            key = f"{filing.filing_id}:{index}"
            documents.append(FilingDocument(
                key, filing.filing_id, key.replace(":", "-") + (".zip" if link["xbrl"] else ".pdf"), url,
                Provenance(self.name, self.regulator, "CL", url, key,
                           raw={"source_label": link["label"], "report_period": filing.provider_metadata["report_period"]}),
                media_type="application/zip" if link["xbrl"] else "application/pdf",
                document_type=link["label"], is_primary=link["primary"], language="es",
                role="data" if link["xbrl"] else "report" if link["primary"] else "exhibit", _provider=self,
            ))
        return documents

    def download_document(self, document: FilingDocument) -> bytes:
        return download(self.transport, _document_url(document.source_url), label="CMF original report")

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        return save(self.transport, _document_url(document.source_url), path, document.media_type, label="CMF original report")

    def raw_facts(self, filing: Filing):
        facts = []
        instances = 0
        for document in filing.documents:
            if document.media_type != "application/zip":
                continue
            for member in document.members:
                if member.entry_path.lower().endswith(".xbrl"):
                    instances += 1
                    with member._parse_content(max_bytes=50_000_000) as content:
                        facts.extend(parse_xbrl_instance(
                            content, document_url=document.source_url, entry_path=member.entry_path,
                            provider=self.name, regulator=self.regulator, jurisdiction="CL", filing_id=filing.filing_id))
        if not instances:
            raise UnsupportedCapabilityError("This CMF report has no original classic XBRL instance")
        return facts
