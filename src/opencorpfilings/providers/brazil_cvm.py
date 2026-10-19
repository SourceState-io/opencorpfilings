"""Original IPE documents from Brazil's CVM open-data catalogue."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from datetime import date, datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zipfile import BadZipFile, ZipFile

from ..errors import EntityNotFoundError, FilingNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..transport import HttpTransport
from ._oam import download, require_https_host, save


_REGISTRY = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
_IPE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{year}.zip"
_ANNUAL = "Demonstrações Financeiras Anuais Completas"


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _rows(content: bytes, required: set[str]) -> list[dict[str, str]]:
    reader = csv.DictReader(StringIO(content.decode("latin-1")), delimiter=";")
    if not required <= set(reader.fieldnames or []):
        raise ParseError("CVM metadata lacks required columns")
    return list(reader)


def _document_url(url: str) -> str:
    require_https_host(url, "www.rad.cvm.gov.br", "CVM document link is outside the original source")
    if urlparse(url).path != "/ENET/frmDownloadDocumento.aspx":
        raise ProviderError("CVM document link has an unexpected path")
    return url


class BrazilCVMProvider(FilingProvider):
    name = "brazil_cvm"
    market = "BR"
    regulator = "Comissão de Valores Mobiliários (CVM)"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download",
                              "pdf", "text", "streamed_download", "direct_filing_lookup"})
    identifier_kinds = ("CVM code", "CNPJ", "exact company name")
    forms = ("annual", "current", "other")
    identifies_amendments = True
    coverage_note = "IPE original PDFs; excludes the separate structured DFP/ITR datasets. Defaults to five delivery years."

    def __init__(self, *, transport: HttpTransport | None = None, max_years: int = 5) -> None:
        if not 1 <= max_years <= 20:
            raise ValueError("max_years must be between 1 and 20")
        # The CVM data host publishes a ten-second crawl delay.
        self.transport = transport or HttpTransport(min_interval=10.0, timeout=60.0)
        self.max_years = max_years
        self._entities: list[Entity] | None = None
        self._years: dict[int, list[dict[str, str]]] = {}

    def _registry(self) -> list[Entity]:
        if self._entities is None:
            rows = _rows(self.transport.get(_REGISTRY), {"CNPJ_CIA", "DENOM_SOCIAL", "CD_CVM"})
            entities: dict[str, Entity] = {}
            for row in rows:
                code = row["CD_CVM"].strip().lstrip("0")
                cnpj, name = row["CNPJ_CIA"].strip(), row["DENOM_SOCIAL"].strip()
                if not code.isdecimal() or len(_digits(cnpj)) != 14 or not name:
                    raise ParseError("CVM registry contains an invalid issuer identity")
                if code in entities:
                    previous = entities[code]
                    if (previous.name != name
                            or _digits(previous.provider_metadata["CNPJ_CIA"]) != _digits(cnpj)):
                        raise ParseError("CVM registry repeats a code with conflicting issuer identities")
                    previous.provider_metadata["source_rows"].append(row)
                    continue
                raw = dict(row, source_rows=[row])
                entities[code] = Entity(
                    code, name, "BR", self.name, _REGISTRY,
                    identifiers=(Identifier("CVM code", code, _REGISTRY), Identifier("CNPJ", cnpj, _REGISTRY)),
                    provider_metadata=raw,
                    provenance=Provenance(self.name, self.regulator, "BR", _REGISTRY, code,
                                          datetime.now(timezone.utc), raw),
                )
            if not entities:
                raise ParseError("CVM registry has no issuer rows")
            self._entities = list(entities.values())
        return self._entities

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        query = query.strip().casefold()
        if not query or limit < 1:
            return []
        matches = [entity for entity in self._registry()
                   if query in entity.name.casefold() or query == entity.entity_id
                   or query in entity.provider_metadata.get("DENOM_COMERC", "").casefold()
                   or query == _digits(entity.provider_metadata["CNPJ_CIA"])]
        matches.sort(key=lambda entity: (
            entity.provider_metadata.get("SIT") != "ATIVO",
            query not in {entity.entity_id, entity.name.casefold(),
                          entity.provider_metadata.get("DENOM_COMERC", "").casefold()},
            len(entity.name),
        ))
        return matches[:limit]

    def resolve_entity(self, identifier: str) -> Entity:
        value = identifier.strip()
        numeric = bool(re.fullmatch(r"[\d./-]+", value))
        matches = [entity for entity in self._registry()
                   if value.casefold() == entity.name.casefold()
                   or (numeric and (_digits(value).lstrip("0") == entity.entity_id
                                    or _digits(value) == _digits(entity.provider_metadata["CNPJ_CIA"])))]
        if len(matches) != 1:
            raise EntityNotFoundError("CVM lookup needs one listed CVM code, CNPJ or exact company name")
        return matches[0]

    def _year(self, year: int) -> list[dict[str, str]]:
        if year not in self._years:
            try:
                with ZipFile(BytesIO(self.transport.get(_IPE.format(year=year)))) as archive:
                    members = [item for item in archive.infolist() if not item.is_dir()]
                    if (len(members) != 1 or not members[0].filename.lower().endswith(".csv")
                            or members[0].file_size > 150_000_000
                            or members[0].file_size > max(members[0].compress_size, 1) * 200):
                        raise ParseError("CVM IPE metadata ZIP exceeds its single-CSV bounds")
                    self._years[year] = _rows(archive.read(members[0]), {
                        "Codigo_CVM", "CNPJ_Companhia", "Data_Entrega", "Protocolo_Entrega", "Versao", "Link_Download"})
            except BadZipFile as exc:
                raise ParseError("CVM IPE metadata is not a valid ZIP") from exc
        return self._years[year]

    def _filing(self, entity: Entity, year: int, row: dict[str, str]) -> Filing:
        if _digits(row["CNPJ_Companhia"]) != _digits(entity.provider_metadata["CNPJ_CIA"]):
            raise ProviderError("CVM filing code and CNPJ identify different issuers")
        try:
            delivered = date.fromisoformat(row["Data_Entrega"])
            if delivered.year != year:
                raise ValueError("wrong delivery archive")
            period = date.fromisoformat(row["Data_Referencia"]) if row.get("Tipo") == _ANNUAL else None
        except ValueError as exc:
            raise ParseError("CVM filing has an invalid source date") from exc
        protocol, version = row["Protocolo_Entrega"], row["Versao"]
        source_id = protocol
        if not protocol:
            _document_url(row["Link_Download"])
            keys = parse_qs(urlparse(row["Link_Download"]).query).get("numProtocolo", [])
            if len(keys) != 1 or not keys[0].isdecimal():
                raise ParseError("CVM record lacks both delivery and RAD source protocols")
            source_id = keys[0]
            protocol = "rad-" + source_id
        if not re.fullmatch(r"[\w-]+", protocol) or not version.isdecimal():
            raise ParseError("CVM filing lacks its delivery protocol or version")
        kind = "ANNUAL" if row.get("Tipo") == _ANNUAL else "CURRENT" if row.get("Categoria") == "Fato Relevante" else "OTHER"
        presentation = row.get("Tipo_Apresentacao", "")
        amended = True if presentation.startswith("RA -") else False if presentation.startswith("AP -") else None
        key = f"{year}:{protocol}:{version}"
        return Filing(
            key, entity.entity_id, "BR", self.name, self.regulator, _IPE.format(year=year),
            Provenance(self.name, self.regulator, "BR", _IPE.format(year=year), source_id,
                       datetime.now(timezone.utc), row),
            filing_type_raw=row.get("Tipo") or row.get("Categoria"), filing_type_normalized=kind,
            title=row.get("Assunto") or row.get("Tipo") or row.get("Categoria"),
            filing_date=delivered, period_end=period, amendment=amended, language="pt",
            provider_metadata=row, _provider=self,
        )

    def filing_matches_form(self, filing: Filing, requested: str) -> bool:
        return (super().filing_matches_form(filing, requested)
                or filing.provider_metadata.get("Categoria", "").casefold() == requested.casefold())

    def iter_filings(self, entity: Entity, *, form: str | None = None, start: date | None = None,
                     end: date | None = None, include_amendments: bool = True,
                     limit: int | None = None) -> Iterator[Filing]:
        last = min((end or date.today()).year, date.today().year)
        first = max(2003, start.year if start else last - self.max_years + 1)
        if last - first + 1 > self.max_years:
            raise UnsupportedCapabilityError("CVM delivery range exceeds max_years; narrow dates or increase max_years")
        count = 0
        for year in range(last, first - 1, -1):
            rows = [row for row in self._year(year) if row["Codigo_CVM"].lstrip("0") == entity.entity_id]
            filings = [self._filing(entity, year, row) for row in rows]
            filings.sort(key=lambda filing: (filing.filing_date, int(filing.provider_metadata["Versao"])), reverse=True)
            for filing in filings:
                if (start and filing.filing_date < start) or (end and filing.filing_date > end):
                    continue
                if not include_amendments and filing.amendment is True:
                    continue
                if form and not self.filing_matches_form(filing, form):
                    continue
                yield filing
                count += 1
                if limit is not None and count >= limit:
                    return

    def get_filing(self, entity: Entity, filing_id: str) -> Filing:
        match = re.fullmatch(r"(\d{4}):([\w-]+):(\d+)", filing_id)
        if match and 2003 <= int(match[1]) <= date.today().year:
            for row in self._year(int(match[1])):
                if row["Codigo_CVM"].lstrip("0") == entity.entity_id and row["Versao"] == match[3]:
                    filing = self._filing(entity, int(match[1]), row)
                    if filing.filing_id == filing_id:
                        return filing
        raise FilingNotFoundError(f"CVM has no selected-issuer IPE record {filing_id!r}")

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        url = _document_url(filing.provider_metadata["Link_Download"])
        return [FilingDocument(
            filing.filing_id, filing.filing_id, filing.filing_id.replace(":", "-") + ".pdf", url,
            Provenance(self.name, self.regulator, "BR", url, filing.provenance.source_id,
                       raw=filing.provider_metadata), media_type="application/pdf", document_type="IPE",
            is_primary=True, role="report" if filing.filing_type_normalized == "ANNUAL" else "other",
            language="pt", _provider=self,
        )]

    def download_document(self, document: FilingDocument) -> bytes:
        return download(self.transport, _document_url(document.source_url), label="CVM IPE document")

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        return save(self.transport, _document_url(document.source_url), path, document.media_type, label="CVM IPE document")
