"""Individual annual financial reports from Spain's CNMV register."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

from ..errors import DownloadError, EntityNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from ..models import Entity, Filing, FilingDocument, Identifier, Provenance
from ..provider import FilingProvider
from ..packages import package_facts, package_text
from ..raw_xbrl import parse_xbrl_instance
from ..transport import HttpTransport
from . import _oam


_BASE = "https://www.cnmv.es"
_PATH = "/portal/Consultas/IFA/ListadoIFA"
_SEARCH = f"{_BASE}/portal/consultas/busquedaporentidad?idPerfil=2&lang=en"
_INTERIM_PATH = "/portal/Consultas/IFI/ListaIFI"
_NIF = re.compile(r"[A-Z0-9-]{5,20}\Z")
_ISSUER_NAME = re.compile(r"Informes financieros anuales\s*-\s*(.+)", re.IGNORECASE)


def _spanish_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError as exc:
        raise ParseError(f"CNMV returned an invalid annual-report date {value!r}") from exc


def _url(nif: str, start: date, end: date) -> str:
    query = urlencode({"id": "0", "fechaDesde": start.strftime("%d/%m/%Y"),
                       "fechaHasta": end.strftime("%d/%m/%Y"), "nif": nif})
    return f"{_BASE}{_PATH}?{query}"


class SpainCNMVProvider(FilingProvider):
    name = "spain_cnmv"
    market = "ES"
    regulator = "CNMV annual financial report register"
    capabilities = frozenset({"entity_lookup", "entity_search", "filing_discovery", "document_download",
                              "streamed_download", "source_package", "pdf", "html", "text",
                              "raw_facts", "ixbrl", "xbrl"})
    identifier_kinds = ("issuer NIF",)
    forms = ("annual", "interim")
    native_forms = False
    order_basis = "filing_date"

    def __init__(self, *, transport: HttpTransport | None = None) -> None:
        self.transport = transport or HttpTransport(min_interval=0.5)

    @staticmethod
    def _nif(identifier: str) -> str:
        nif = identifier.strip().upper()
        if not _NIF.fullmatch(nif):
            raise EntityNotFoundError("CNMV annual-report lookup requires an issuer NIF")
        return nif

    def _page(self, nif: str, start: date, end: date) -> tuple[str, list[dict], str]:
        url = _url(nif, start, end)
        soup = BeautifulSoup(self.transport.get(url), "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        match = _ISSUER_NAME.search(title)
        if match is None:
            raise ParseError("CNMV annual-report response lacks an issuer title")
        name = match.group(1).strip()
        table = soup.select_one("table[id=ctl00_ContentPrincipal_gridInformes]")
        if table is None:
            raise ParseError("CNMV annual-report response lacks its results table")
        rows: list[dict] = []
        for tr in table.select("tr"):
            cells = tr.select("td")
            if len(cells) < 8:
                continue
            period = _spanish_date(cells[1].get_text(" ", strip=True))
            published = _spanish_date(cells[2].get_text(" ", strip=True))
            documents: list[dict[str, str]] = []
            for index, role in ((4, "financial_report"), (5, "esef_package")):
                for number, link in enumerate(cells[index].select("a[href]"), 1):
                    href = urljoin(url, str(link["href"]))
                    parsed = urlparse(href)
                    if parsed.scheme != "https" or parsed.hostname != "www.cnmv.es":
                        raise ProviderError("CNMV returned a document outside its HTTPS host")
                    documents.append({"url": href, "role": role, "number": str(number)})
            additional = cells[7].select_one("a[href]")
            additional_url = urljoin(url, str(additional["href"])) if additional else None
            report_id = None
            if additional_url:
                report_id = parse_qs(urlparse(additional_url).query).get("nreg", [None])[0]
            registry_number = cells[0].get_text(" ", strip=True)
            if not report_id:
                report_id = f"{nif}:{period.isoformat()}:{published.isoformat()}:{registry_number}"
            rows.append({"report_id": report_id, "registry_number": registry_number,
                         "period_end": period, "published_date": published,
                         "auditor": cells[3].get_text(" ", strip=True),
                         "report_type": cells[4].get_text(" ", strip=True),
                         "additional_url": additional_url, "documents": documents})
        return name, rows, url

    def resolve_entity(self, identifier: str) -> Entity:
        nif = self._nif(identifier)
        today = datetime.now(timezone.utc).date()
        name, rows, url = self._page(nif, date(today.year - 5, 1, 1), today)
        if not rows:
            raise EntityNotFoundError(
                f"CNMV has no annual report for NIF {nif} in the default five-year lookup window"
            )
        return Entity(
            entity_id=nif, name=name, jurisdiction="ES", provider=self.name,
            source_url=url, identifiers=(Identifier("NIF", nif, url),),
            provider_metadata={"lookup_window": "five calendar years", "report_count": len(rows)},
            provenance=Provenance(self.name, self.regulator, "ES", url, nif,
                                  datetime.now(timezone.utc), {"issuer_name": name}),
        )

    def search_entities(self, query: str, *, limit: int = 10) -> list[Entity]:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        soup = BeautifulSoup(self.transport.get(_SEARCH), "html.parser")
        field = soup.select_one('input[name="ctl00$ContentPrincipal$txtBusqueda"]')
        submit = soup.select_one('input[name="ctl00$ContentPrincipal$btnBuscar"]')
        if field is None or submit is None:
            raise ParseError("CNMV issuer-name search form is missing")
        data = {str(item["name"]): str(item.get("value", ""))
                for item in soup.select('input[type="hidden"][name]')}
        if not {"__VIEWSTATE", "__EVENTVALIDATION"} <= data.keys():
            raise ParseError("CNMV issuer-name search form lacks state fields")
        data[str(field["name"])] = query
        data[str(submit["name"])] = str(submit.get("value", ""))
        results = BeautifulSoup(self.transport.post_form(_SEARCH, data=data), "html.parser")
        selector = results.select_one("#ctl00_ContentPrincipal_wuc_Entidades_lstSeleccion")
        if selector is None:
            title = results.title.get_text(" ", strip=True) if results.title else ""
            single = re.fullmatch(r"CNMV\s*-\s*Entity Information\s*-\s*(.+)", title, re.IGNORECASE)
            detail_form = results.select_one("form[action]")
            detail_url = urljoin(_SEARCH, str(detail_form["action"])) if detail_form else ""
            parsed = urlparse(detail_url)
            nifs = parse_qs(parsed.query).get("nif", [])
            if (single and parsed.scheme == "https" and parsed.hostname == "www.cnmv.es"
                    and parsed.path.lower() == "/portal/consultas/datosentidad"
                    and len(nifs) == 1 and _NIF.fullmatch(nifs[0].upper())):
                nif, name = nifs[0].upper(), single.group(1).strip()
                raw = {"search_query": query, "source_nif": nif, "source_name": name,
                       "identity_basis": "CNMV single-issuer search result"}
                return [Entity(
                    entity_id=nif, name=name, jurisdiction="ES", provider=self.name,
                    source_url=detail_url, identifiers=(Identifier("NIF", nif, detail_url),),
                    provider_metadata=raw,
                    provenance=Provenance(self.name, self.regulator, "ES", detail_url, nif,
                                          datetime.now(timezone.utc), raw),
                )]
            if results.select_one('input[name="ctl00$ContentPrincipal$txtBusqueda"]') is None:
                raise ParseError("CNMV issuer-name search response is unrecognized")
            return []
        entities = []
        for option in selector.select("option[value]"):
            nif, name = str(option["value"]).strip().upper(), option.get_text(" ", strip=True)
            if not _NIF.fullmatch(nif) or not name:
                continue
            raw = {"search_query": query, "source_nif": nif, "source_name": name,
                   "identity_basis": "CNMV issuer-name search"}
            entities.append(Entity(
                entity_id=nif, name=name, jurisdiction="ES", provider=self.name,
                source_url=_SEARCH, identifiers=(Identifier("NIF", nif, _SEARCH),),
                provider_metadata=raw,
                provenance=Provenance(self.name, self.regulator, "ES", _SEARCH, nif,
                                      datetime.now(timezone.utc), raw),
            ))
            if len(entities) >= limit:
                break
        return entities

    def _interim_page(self, nif: str) -> tuple[str, list[dict], str]:
        url = f"{_BASE}{_INTERIM_PATH}?{urlencode({'nif': nif})}"
        soup = BeautifulSoup(self.transport.get(url), "html.parser")
        label = soup.select_one("#ctl00_ContentPrincipal_lblSubtitulo")
        table = soup.select_one("#ctl00_ContentPrincipal_gridEntidades")
        if label is None or table is None:
            raise ParseError("CNMV interim-report response lacks its issuer or results table")
        name = label.get_text(" ", strip=True)
        rows = []
        for tr in table.select("tr"):
            cells = tr.select("td")
            if len(cells) != 2:
                continue
            link = cells[0].select_one("a[href]")
            if link is None:
                raise ParseError("CNMV interim-report row lacks a detail link")
            detail_url = urljoin(url, str(link["href"]))
            parsed = urlparse(detail_url)
            report_id = parse_qs(parsed.query).get("nreg", [None])[0]
            if (parsed.scheme != "https" or parsed.hostname != "www.cnmv.es"
                    or not parsed.path.lower().endswith("/aldia/detalleifialdia.aspx")
                    or not report_id or not report_id.isdecimal()):
                raise ProviderError("CNMV returned an invalid interim-report detail link")
            rows.append({"report_id": report_id, "published_date": _spanish_date(cells[0].get_text(" ", strip=True)),
                         "report_type": cells[1].get_text(" ", strip=True), "detail_url": detail_url})
        return name, rows, url

    def iter_filings(
        self, entity: Entity, *, form: str | None = None, start: date | None = None,
        end: date | None = None, include_amendments: bool = True,
        limit: int | None = None,
    ) -> Iterator[Filing]:
        if form is not None and form.lower() not in {"annual", "interim"}:
            raise UnsupportedCapabilityError("CNMV national route supports annual and interim financial reports")
        if not include_amendments:
            raise UnsupportedCapabilityError("CNMV substitution history requires report-level interpretation")
        nif = self._nif(entity.entity_id)
        today = datetime.now(timezone.utc).date()
        start_date = start or date(today.year - 5, 1, 1)
        end_date = end or today
        filings: list[Filing] = []
        if form is None or form.lower() == "annual":
            name, rows, url = self._page(nif, start_date, end_date)
            if name.casefold() != entity.name.casefold():
                raise ProviderError("CNMV issuer name changed between lookup and filing search")
            for row in rows:
                report_id = row["report_id"]
                raw = {**row, "period_end": row["period_end"].isoformat(),
                       "published_date": row["published_date"].isoformat(),
                       "nif": nif, "search_url": url}
                source_url = row["additional_url"] or url
                filings.append(Filing(
                    filing_id=report_id, entity_id=nif, jurisdiction="ES", provider=self.name,
                    regulator=self.regulator, source_url=source_url,
                    provenance=Provenance(self.name, self.regulator, "ES", source_url,
                                          report_id, datetime.now(timezone.utc), raw),
                    filing_type_raw="IFA", filing_type_normalized="ANNUAL",
                    title=f"Annual financial report — {row['period_end'].isoformat()}",
                    filing_date=row["published_date"], period_end=row["period_end"],
                    amendment=None, provider_metadata=raw, _provider=self,
                ))
        if form is None or form.lower() == "interim":
            name, rows, url = self._interim_page(nif)
            if name.casefold() != entity.name.casefold():
                raise ProviderError("CNMV interim register returned another issuer")
            for row in rows:
                when = row["published_date"]
                if when < start_date or when > end_date:
                    continue
                report_id, source_url = row["report_id"], row["detail_url"]
                raw = {**row, "published_date": when.isoformat(), "nif": nif,
                       "issuer_name": name,
                       "search_url": url}
                filings.append(Filing(
                    filing_id=report_id, entity_id=nif, jurisdiction="ES", provider=self.name,
                    regulator=self.regulator, source_url=source_url,
                    provenance=Provenance(self.name, self.regulator, "ES", source_url,
                                          report_id, datetime.now(timezone.utc), raw),
                    filing_type_raw=row["report_type"], filing_type_normalized="INTERIM",
                    title=row["report_type"], filing_date=when,
                    amendment=None, provider_metadata=raw, _provider=self,
                ))
        filings.sort(key=lambda filing: (filing.filing_date or date.min, filing.filing_id), reverse=True)
        yield from filings[:limit]

    def list_documents(self, filing: Filing) -> list[FilingDocument]:
        if filing.filing_type_normalized == "INTERIM":
            return self._interim_documents(filing)
        documents = []
        for raw in filing.provider_metadata.get("documents", []):
            url = raw["url"]
            role = raw["role"]
            suffix = "zip" if role == "esef_package" else "pdf"
            document_id = f"{filing.filing_id}:{role}:{raw['number']}"
            filename = f"CNMV-{filing.filing_id}-{role}-{raw['number']}.{suffix}"
            documents.append(FilingDocument(
                document_id=document_id, filing_id=filing.filing_id,
                filename=filename, source_url=url,
                provenance=Provenance(self.name, self.regulator, "ES", url, document_id,
                                      raw={"report_id": filing.filing_id, "role": role}),
                media_type="application/zip" if role == "esef_package" else "application/pdf",
                document_type=role, is_primary=role == "esef_package",
                provider_metadata={"report_url": filing.source_url, "registry_number": filing.provider_metadata.get("registry_number")},
                _provider=self,
            ))
        if documents and not any(document.is_primary for document in documents):
            documents[0].is_primary = True
        return documents

    def _interim_documents(self, filing: Filing) -> list[FilingDocument]:
        soup = BeautifulSoup(self.transport.get(filing.source_url), "html.parser")
        name = soup.select_one("#ctl00_ContentPrincipal_lblNombreEntidad")
        source_id = soup.select_one('[id$="_lblNIF"]')
        start = soup.select_one('[id$="_lblInicioPeriodo"]')
        end = soup.select_one('[id$="_lblFinPeriodo"]')
        published = soup.select_one('[id$="_lblPublicacion"]')
        if any(item is None for item in (name, source_id, start, end, published)):
            raise ParseError("CNMV interim-report detail lacks source identity or period")
        if name.get_text(" ", strip=True).casefold() != filing.provider_metadata["issuer_name"].casefold():
            raise ProviderError("CNMV interim-report detail belongs to another issuer")
        if source_id.get_text(" ", strip=True).upper() != filing.entity_id:
            raise ProviderError("CNMV interim-report detail has a different NIF")
        if _spanish_date(published.get_text(" ", strip=True)) != filing.filing_date:
            raise ProviderError("CNMV interim-report detail has a different publication date")
        filing.period_start = _spanish_date(start.get_text(" ", strip=True))
        filing.period_end = _spanish_date(end.get_text(" ", strip=True))
        documents = []
        for link in soup.select('a[id^="ctl00_ContentPrincipal_"][href]'):
            link_id, href = str(link["id"]), str(link["href"])
            if "verdocumento/ver" in href.lower():
                if link_id.endswith("_hlInforme"):
                    role = "interim_report"
                elif link_id.endswith("_hlInformeIngles"):
                    role = "interim_report_english"
                elif "_hlAnexos" in link_id:
                    role = "annex"
                else:
                    continue
                media_type, suffix = "application/pdf", "pdf"
            elif "descargaxbrlipp.ashx" in href.lower():
                role, media_type, suffix = "xbrl_instance", "application/xml", "xml"
            else:
                continue
            url = urljoin(filing.source_url, href)
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != "www.cnmv.es":
                raise ProviderError("CNMV interim report links outside its HTTPS host")
            document_id = f"{filing.filing_id}:{role}:{len(documents) + 1}"
            raw = {"report_id": filing.filing_id, "role": role, "source_link_id": link_id}
            documents.append(FilingDocument(
                document_id=document_id, filing_id=filing.filing_id,
                filename=f"CNMV-{filing.filing_id}-{role}.{suffix}", source_url=url,
                provenance=Provenance(self.name, self.regulator, "ES", url, document_id,
                                      datetime.now(timezone.utc), raw),
                media_type=media_type, document_type=role, language=link.get("lang"),
                is_primary=role == "interim_report", provider_metadata=raw,
                _provider=self,
            ))
        if not documents:
            raise ParseError("CNMV interim-report detail has no original documents")
        if not any(document.is_primary for document in documents):
            documents[0].is_primary = True
        return documents

    def download_document(self, document: FilingDocument) -> bytes:
        _oam.require_https_host(document.source_url, "www.cnmv.es", "CNMV document URL is outside its HTTPS host")
        content = _oam.download(self.transport, document.source_url, label="CNMV document")
        prefix = content[:1024].lstrip().lower()
        if (document.media_type == "application/pdf" and b"<html" in prefix
                and b"www.w3.org/1999/xhtml" in prefix):
            document.provider_metadata = {
                **document.provider_metadata,
                "listed_media_type": document.media_type,
                "observed_media_type": "application/xhtml+xml",
            }
            document.media_type = "application/xhtml+xml"
            document.filename = str(Path(document.filename).with_suffix(".xhtml"))
        return content

    def save_document(self, document: FilingDocument, path: Path) -> Path:
        _oam.require_https_host(document.source_url, "www.cnmv.es", "CNMV document URL is outside its HTTPS host")
        target = Path(path)
        fd, staged_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".stage", dir=target.parent)
        os.close(fd)
        staged = Path(staged_name)
        try:
            try:
                self.transport.get_to_file(
                    document.source_url, staged,
                    expected_prefix=b"PK\x03\x04" if document.media_type == "application/zip" else None,
                )
            except ProviderError as exc:
                raise DownloadError(f"CNMV document failed: {exc}") from exc
            with staged.open("rb") as saved:
                prefix = saved.read(1024)
            markup = prefix.lstrip().lower()
            discovered_xhtml = (document.media_type == "application/pdf"
                                and b"<html" in markup
                                and b"www.w3.org/1999/xhtml" in markup)
            if document.media_type == "application/pdf" and not discovered_xhtml and not prefix.startswith(b"%PDF-"):
                raise DownloadError(f"CNMV returned an unexpected PDF document for {document.source_url}")
            os.replace(staged, target)
            if discovered_xhtml:
                document.provider_metadata = {
                    **document.provider_metadata,
                    "listed_media_type": document.media_type,
                    "observed_media_type": "application/xhtml+xml",
                }
                document.media_type = "application/xhtml+xml"
                document.filename = str(Path(document.filename).with_suffix(".xhtml"))
            return target
        finally:
            staged.unlink(missing_ok=True)

    def extract_text(self, document: FilingDocument) -> str:
        return package_text(document, label="CNMV")

    def raw_facts(self, filing: Filing):
        if filing.filing_type_normalized == "INTERIM":
            document = next((item for item in filing.documents
                             if item.document_type == "xbrl_instance"), None)
            if document is None:
                raise UnsupportedCapabilityError(f"CNMV interim report {filing.filing_id} has no XBRL instance")
            return parse_xbrl_instance(
                document.download(), document_url=document.source_url,
                entry_path=document.filename, provider=self.name,
                regulator=self.regulator, jurisdiction="ES", filing_id=filing.filing_id,
            )
        return package_facts(filing, name=self.name, regulator=self.regulator, jurisdiction="ES", label="CNMV")
