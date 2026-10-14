"""CNMV interim reports keep their native category, dates and originals."""

from datetime import date

import pytest

from opencorpfilings import Company
from opencorpfilings.errors import ProviderError
from opencorpfilings.providers.spain_cnmv import SpainCNMVProvider
from test_europe_oam import SpainTransport
from test_raw_xbrl import INSTANCE


_LIST = b'''<html><span id="ctl00_ContentPrincipal_lblSubtitulo">IBERDROLA, S.A.</span>
<table id="ctl00_ContentPrincipal_gridEntidades">
<tr><th>Date</th><th>Type</th></tr>
<tr><td><a href="../../aldia/detalleifialdia.aspx?nreg=2026103709">24/07/2026</a></td>
<td>I semestre de 2026 individual y consolidado</td></tr>
<tr><td><a href="../../aldia/detalleifialdia.aspx?nreg=2025031737">28/02/2025</a></td>
<td>II semestre de 2024 individual y consolidado</td></tr>
</table></html>'''

_DETAIL = b'''<html>
<span id="ctl00_ContentPrincipal_lblNombreEntidad">IBERDROLA, S.A.</span>
<span id="ctl00_ContentPrincipal_ctl10_GridInformacionFinancieraIntermedia_ctl06_lblInicioPeriodo">01/01/2026</span>
<span id="ctl00_ContentPrincipal_ctl10_GridInformacionFinancieraIntermedia_ctl06_lblFinPeriodo">30/06/2026</span>
<span id="ctl00_ContentPrincipal_ctl10_GridInformacionFinancieraIntermedia_ctl06_lblNIF">A-48010615</span>
<span id="ctl00_ContentPrincipal_ctl10_GridInformacionFinancieraIntermedia_ctl06_lblPublicacion">24/07/2026</span>
<a id="ctl00_ContentPrincipal_hlInforme" href="https://www.cnmv.es/webservices/verdocumento/ver?e=pdf" lang="es"></a>
<a id="ctl00_ContentPrincipal_ctl11_hlDescargaInforme" href="../consultas/wuc/descargaxbrlipp.ashx?t=source"></a>
</html>'''


class SpainInterimTransport(SpainTransport):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: object) -> bytes:
        self.calls.append(url)
        if "/IFI/ListaIFI?" in url:
            return _LIST
        if "detalleifialdia.aspx?nreg=2026103709" in url:
            return _DETAIL
        if "descargaxbrlipp.ashx" in url:
            return INSTANCE
        return super().get(url, **kwargs)


def test_cnmv_interim_list_detail_documents_and_raw_facts():
    transport = SpainInterimTransport()
    company = Company("A-48010615", market="ES", provider=SpainCNMVProvider(transport=transport))
    assert company.provider.supports("xbrl")
    filing = company.filings(form="interim", start="2026-01-01").latest()
    assert filing.filing_id == "2026103709"
    assert filing.filing_type_normalized == "INTERIM"
    assert filing.filing_type_raw == "I semestre de 2026 individual y consolidado"
    assert filing.filing_date == date(2026, 7, 24)
    assert filing.period_end is None  # Exact boundaries require the selected detail page.
    assert "detalleifialdia.aspx?nreg=2026103709" in filing.source_url
    assert len([url for url in transport.calls if "detalleifialdia.aspx" in url]) == 0

    documents = filing.documents
    assert [(document.document_type, document.media_type) for document in documents] == [
        ("interim_report", "application/pdf"), ("xbrl_instance", "application/xml")]
    assert filing.period_start == date(2026, 1, 1)
    assert filing.period_end == date(2026, 6, 30)
    assert filing.primary_document is documents[0]
    assert all(document.source_url.startswith("https://www.cnmv.es/") for document in documents)
    assert len([url for url in transport.calls if "detalleifialdia.aspx" in url]) == 1
    assert [(fact.concept_raw, fact.value) for fact in filing.facts] == [
        ("ex:Sales", "123"), ("ex:Sales", "124")]
    assert filing.facts[0].provenance.source_url == documents[1].source_url
    assert len([url for url in transport.calls if "descargaxbrlipp.ashx" in url]) == 1


def test_cnmv_unfiltered_filings_include_latest_interim_and_annual():
    company = Company("A-48010615", market="ES", provider=SpainCNMVProvider(transport=SpainInterimTransport()))
    filings = company.filings(start="2025-01-01").head(3)
    assert [filing.filing_type_normalized for filing in filings] == ["INTERIM", "INTERIM", "ANNUAL"]


def test_cnmv_interim_detail_rejects_another_issuer():
    class WrongIssuerTransport(SpainInterimTransport):
        def get(self, url: str, **kwargs: object) -> bytes:
            content = super().get(url, **kwargs)
            return content.replace(b"A-48010615", b"A-99999999") if "detalleifialdia.aspx" in url else content

    company = Company("A-48010615", market="ES", provider=SpainCNMVProvider(transport=WrongIssuerTransport()))
    filing = company.filings(form="interim", start="2026-01-01").latest()
    with pytest.raises(ProviderError, match="different NIF"):
        _ = filing.documents
