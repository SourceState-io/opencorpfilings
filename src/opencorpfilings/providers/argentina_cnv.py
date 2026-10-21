"""Financial-statement submissions and original PDF attachments from CNV/AIF."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date, datetime, timezone
from io import BytesIO
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from bs4 import BeautifulSoup

from ..errors import EntityNotFoundError, FilingNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..transport import HttpTransport
from ._oam import require_https_host


_BASE = "https://www.cnv.gov.ar/SitioWeb/"
_REGISTRY = _BASE + "Reportes/ListadoSociedadesEmisorasPorRegimen"
_VIEW = "https://aif2.cnv.gov.ar/presentations/publicview/"
_KEY = "https://aif2.cnv.gov.ar/api/ValetKeyProvider/GetPublicValetKey/"
_BLOB = "https://blob.cnv.gov.ar/BlobWebService.svc/DownloadBlob/"
_MONTHS = dict(zip(("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"), range(1, 13)))
_FORMS = {"1": "ANNUAL", "2": "INTERIM", "3": "QUARTERLY"}


def _uuid(value: str) -> str:
    try:
        parsed = str(UUID(value))
    except ValueError as exc:
        raise ParseError("CNV source identifier is not a UUID") from exc
    if value.casefold() != parsed:
        raise ParseError("CNV source identifier is not a canonical UUID")
    return parsed


def _xlsx_rows(content: bytes) -> list[list[str]]:
    """Read the small official roster without adding a spreadsheet dependency."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with ZipFile(BytesIO(content)) as archive:
            def read(name: str):
                if archive.getinfo(name).file_size > 8_000_000:
                    raise ParseError("CNV roster worksheet exceeds its metadata bound")
                return ET.fromstring(archive.read(name))
            strings = (["".join(node.itertext()) for node in read("xl/sharedStrings.xml")]
                       if "xl/sharedStrings.xml" in archive.namelist() else [])
            result = []
            for row in read("xl/worksheets/sheet1.xml").findall(".//m:row", ns):
                values = [""] * 4
                for cell in row:
                    column = re.match(r"([A-D])\d+$", cell.get("r", ""))
                    if not column:
                        continue
                    value = cell.find("m:v", ns)
                    text = value.text or "" if value is not None else ""
                    if cell.get("t") == "s":
                        text = strings[int(text)]
                    elif cell.get("t") == "inlineStr":
                        text = "".join(cell.find("m:is", ns).itertext())
                    values[ord(column[1]) - ord("A")] = text.strip()
                result.append(values)
            return result
    except (BadZipFile, KeyError, ValueError, IndexError, ET.ParseError) as exc:
        raise ParseError("CNV issuer roster is not a recognized XLSX worksheet") from exc


def _js_string(value: str) -> str:
    """Decode one quoted JavaScript data literal; never evaluate source scripts."""
    def replace(match):
        escape = match[0][1:]
        if escape.startswith(("u", "x")):
            return chr(int(escape[1:], 16))
        translations = {"'": "'", '"': '"', "\\": "\\", "/": "/", "n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
        if escape not in translations:
            raise ParseError("CNV presentation has an unsupported string escape")
        return translations[escape]
    return re.sub(r"\\(?:u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", replace, value)


class ArgentinaCNVProvider(FilingProvider):
    name = "argentina_cnv"
    market = "AR"
    regulator = "Comisión Nacional de Valores (CNV)"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download",
                              "pdf", "text", "direct_filing_lookup"})
    identifier_kinds = ("CUIT", "exact company name")
    forms = ("annual", "interim", "quarterly")
    native_forms = False
    date_filters = True
    order_basis = "filing_date"
    coverage_note = "CNV financial-statement submissions and original PDF attachments; related-company rows excluded. No amendment classification."

    def __init__(self, *, transport: HttpTransport | None = None, max_years: int = 5) -> None:
        if not 1 <= max_years <= 30:
            raise ValueError("max_years must be between 1 and 30")
        self.transport = transport or HttpTransport(min_interval=1.0, timeout=90.0)
        self.max_years = max_years
        self._entities: list[Entity] | None = None
        self._presentations: dict[str, tuple[dict, list[dict]]] = {}
        self._filings: dict[str, Filing] = {}

    def _registry(self) -> list[Entity]:
        if self._entities is None:
            entities = {}
            for cuit, name, category, status in _xlsx_rows(self.transport.get(_REGISTRY)):
                if not re.fullmatch(r"\d{11}", cuit) or not name:
                    continue
                if cuit not in entities:
                    url = _BASE + "Empresas/Empresa/" + cuit
                    raw = {"CUIT": cuit, "source_rows": []}
                    entities[cuit] = Entity(cuit, name, "AR", self.name, url,
                        identifiers=(Identifier("CUIT", cuit, _REGISTRY),), provider_metadata=raw,
                        provenance=Provenance(self.name, self.regulator, "AR", _REGISTRY, cuit,
                                              datetime.now(timezone.utc), raw))
                entities[cuit].provider_metadata["source_rows"].append({"category": category, "status": status})
            if not entities:
                raise ParseError("CNV roster has no recognized CUIT/company rows")
            self._entities = list(entities.values())
        return self._entities

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        value = query.strip().casefold()
        if not value or limit < 1:
            return []
        digits = re.sub(r"[-\s]", "", value)
        return [entity for entity in self._registry()
                if value in entity.name.casefold() or digits == entity.entity_id][:limit]

    def resolve_entity(self, identifier: str) -> Entity:
        value = re.sub(r"[-\s]", "", identifier)
        matches = [entity for entity in self._registry() if entity.entity_id == value
                   or entity.name.casefold() == identifier.strip().casefold()]
        if len(matches) != 1:
            raise EntityNotFoundError("CNV lookup needs one listed CUIT or exact company name")
        return matches[0]

    def iter_filings(self, entity: Entity, *, form: str | None = None, start: date | None = None,
                     end: date | None = None, include_amendments: bool = True,
                     limit: int | None = None) -> Iterator[Filing]:
        if not include_amendments:
            raise UnsupportedCapabilityError("CNV submissions have no verified amendment classification")
        if form and form.casefold() not in self.forms:
            raise UnsupportedCapabilityError("CNV supports annual, interim and quarterly financial statements")
        end = end or date.today()
        start = start or date(end.year - self.max_years + 1, 1, 1)
        if end.year - start.year >= self.max_years:
            raise UnsupportedCapabilityError("CNV filing-date window exceeds max_years; increase it for older submissions")
        params = {"formType": "INFOFI", "fdesde": f"{start.day}/{start.month}/{start.year}",
                  "fhasta": f"{end.day}/{end.month}/{end.year}"}
        page = BeautifulSoup(self.transport.get(entity.source_url, params=params).decode("utf-8-sig"), "html.parser")
        content = page.select_one("#container-res")
        identity = content.find_all("h1") if content else []
        if not any(re.search(r"CUIT\s*:\s*" + entity.entity_id[:2] + r"-?" + entity.entity_id[2:10] + r"-?" + entity.entity_id[10], h.get_text(" ", strip=True)) for h in identity):
            raise ProviderError("CNV company response does not identify the selected CUIT")
        heading = next((h for h in content.find_all("h4") if h.get_text(" ", strip=True).casefold() == "estados contables"), None)
        if heading is None:
            raise ParseError("CNV response lacks the financial-statements section")
        panel = heading.find_parent(class_="panel")
        filings = {}
        for row in panel.select("tbody tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 5:
                continue
            description = cells[2].get_text(" ", strip=True)
            if re.search(r"RELAC\s*\.:|CONTROLADAS Y VINCULADAS", description, re.I):
                continue
            periodicity = re.search(r"PERIODICIDAD:\s*([123])\b", description)
            close = re.search(r"FECHA CIERRE:\s*(\d{4}-\d{2}-\d{2})", description)
            anchor = row.select_one('a[href*="/presentations/publicview/"]')
            if not periodicity or not close or anchor is None:
                continue
            url = str(anchor["href"]).strip()
            require_https_host(url, "aif2.cnv.gov.ar", "CNV presentation link is outside AIF")
            key = _uuid(url.removeprefix(_VIEW))
            printed = re.fullmatch(r"(\d{1,2})\s+([a-z]{3})\.?\s+(\d{4})", cells[0].get_text(" ", strip=True).casefold())
            if not printed or printed[2] not in _MONTHS:
                raise ParseError("CNV financial row has an unrecognized filing date")
            filed = date(int(printed[3]), _MONTHS[printed[2]], int(printed[1]))
            raw = {"CUIT": entity.entity_id, "presentation_id": cells[3].get_text(strip=True),
                   "source_description": description, "periodicity": periodicity[1],
                   "source_time": cells[1].get_text(strip=True)}
            filing = Filing(key, entity.entity_id, "AR", self.name, self.regulator, url,
                Provenance(self.name, self.regulator, "AR", url, raw["presentation_id"], datetime.now(timezone.utc), raw),
                filing_type_raw=description, filing_type_normalized=_FORMS[periodicity[1]],
                title=description, filing_date=filed, period_end=date.fromisoformat(close[1]),
                language="es", provider_metadata=raw, _provider=self)
            if start <= filed <= end and (not form or self.filing_matches_form(filing, form)):
                filings[key] = filing
                self._filings[key] = filing
        ordered = sorted(filings.values(), key=lambda f: (f.filing_date, f.provider_metadata["source_time"], f.filing_id), reverse=True)
        yield from ordered[:limit] if limit is not None else ordered

    def _presentation(self, entity_id: str, key: str) -> tuple[dict, list[dict]]:
        key = _uuid(key)
        if key not in self._presentations:
            page = BeautifulSoup(self.transport.get(_VIEW + key).decode("utf-8-sig"), "html.parser")
            title = page.title.get_text(" ", strip=True) if page.title else ""
            identity = re.search(r"Presentaci[oó]n\s*#(\d+)\s*-.*\|\s*(\d{11})\s*-", title)
            if identity is None or identity[2] != entity_id:
                raise ProviderError("AIF presentation does not identify the selected issuer CUIT")
            match = next((m for script in page.select("script:not([src])")
                          if (m := re.search(r"var\s+presentation\s*=\s*'((?:\\.|[^'\\])*)'\s*;", script.get_text(), re.S))), None)
            if match is None:
                raise ParseError("AIF presentation lacks its public financial metadata")
            try:
                root = ET.fromstring(_js_string(match[1]))
                identification = root.find("entidad[@clave='IdentificacionBalance']")
                if identification is None:
                    raise ParseError("AIF presentation is not a recognized financial-statement submission")
                fields = {p.get("id"): p.text or "" for p in identification.findall("propiedad")}
                period = date.fromisoformat(fields["FechaCierre"][:10])
                normalized = _FORMS[fields["PeriodoBalance"]]
                links = []
                for prop in root.findall("entidad[@clave='Adjuntos Balance']/propiedad"):
                    if not (prop.text or "").strip().startswith("["):
                        continue
                    for attachment in json.loads(prop.text):
                        filename = attachment["nombreArchivo"]
                        if not filename.lower().endswith(".pdf"):
                            continue
                        links.append({"guid": _uuid(attachment["guid"]), "filename": filename,
                                      "source_hash": attachment.get("hash"), "source_property": prop.get("id"),
                                      "primary": prop.get("id") == "ABEstadoContable"})
            except (ET.ParseError, ValueError, KeyError, TypeError) as exc:
                raise ParseError("AIF financial metadata is not recognized") from exc
            if not any(link["primary"] for link in links):
                raise ParseError("AIF presentation has no original financial-statements PDF attachment")
            raw = {"CUIT": entity_id, "presentation_id": identity[1], "source_fields": fields,
                   "period_end": period, "normalized": normalized}
            self._presentations[key] = raw, links
        result = self._presentations[key]
        if result[0]["CUIT"] != entity_id:
            raise ProviderError("AIF presentation belongs to another issuer")
        return result

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        try:
            _uuid(filing_id)
        except ParseError as exc:
            raise FilingNotFoundError("CNV direct lookup needs an AIF public presentation UUID") from exc
        if filing_id in self._filings and self._filings[filing_id].entity_id == entity.entity_id:
            return self._filings[filing_id]
        raw, _ = self._presentation(entity.entity_id, filing_id)
        url = _VIEW + filing_id
        return Filing(filing_id, entity.entity_id, "AR", self.name, self.regulator, url,
            Provenance(self.name, self.regulator, "AR", url, raw["presentation_id"], datetime.now(timezone.utc), raw),
            filing_type_raw="Estados Contables " + raw["source_fields"].get("TipoBalance", ""),
            filing_type_normalized=raw["normalized"], period_end=raw["period_end"],
            language="es", provider_metadata=raw, _provider=self)

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        raw, links = self._presentation(filing.entity_id, filing.filing_id)
        if (raw["presentation_id"] != filing.provenance.source_id or raw["period_end"] != filing.period_end
                or raw["normalized"] != filing.filing_type_normalized):
            raise ProviderError("AIF presentation metadata disagrees with the selected financial row")
        return [FilingDocument(link["guid"], filing.filing_id, link["filename"], _BLOB + link["guid"],
                    Provenance(self.name, self.regulator, "AR", _BLOB + link["guid"], link["guid"], raw=link),
                    media_type="application/pdf", document_type=link["source_property"], language="es",
                    is_primary=link["primary"], role="report" if link["primary"] else "exhibit", _provider=self)
                for link in links]

    def download_document(self, document: FilingDocument) -> bytes:
        require_https_host(document.source_url, "blob.cnv.gov.ar", "CNV original link is outside its blob service")
        key = _uuid(document.source_url.removeprefix(_BLOB))
        grant = self.transport.get_json(_KEY + key, params={"operation": "DownloadBlob"}, cache=False)
        token = grant.get("valetKeyData") if isinstance(grant, dict) else None
        if not isinstance(token, str) or not token:
            raise ProviderError("CNV public attachment service did not issue a download grant")
        # The public site's own download protocol: grant stays in the POST body,
        # never in a persistent source URL, cache key or provenance record.
        return self.transport.post_form(_BLOB + key, data={"ValetKey": token})
