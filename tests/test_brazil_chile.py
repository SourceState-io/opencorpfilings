"""Source contracts for Brazilian IPE documents and Chilean IFRS reports."""

from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import csv

import pytest

from opencorpfilings import Company, DownloadError, EntityNotFoundError, FilingNotFoundError, ProviderError, UnsupportedCapabilityError, provider_info
from opencorpfilings.providers.brazil_cvm import BrazilCVMProvider
from opencorpfilings.providers.chile_cmf import ChileCMFProvider


PDF = (Path(__file__).parent / 'fixtures/two_page_report.pdf').read_bytes()


@pytest.fixture(autouse=True)
def fixed_source_clock(monkeypatch):
    class SourceDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 19)
    monkeypatch.setattr('opencorpfilings.providers.brazil_cvm.date', SourceDate)
    monkeypatch.setattr('opencorpfilings.providers.chile_cmf.date', SourceDate)


def zipped(name, data):
    out = BytesIO()
    with ZipFile(out, 'w') as archive:
        archive.writestr(name, data)
    return out.getvalue()


BR_REGISTRY = ('CNPJ_CIA;DENOM_SOCIAL;CD_CVM;SIT\n'
               '33.000.167/0001-01;PETROLEO BRASILEIRO S.A. - PETROBRAS;9512;ATIVO\n'
               '33.592.510/0001-54;VALE S.A.;4170;ATIVO\n').encode('latin-1')
BR_URL = ('https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?'
          'Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=100&numSequencia=200&numVersao=1')


def br_row(**changes):
    row = {'CNPJ_Companhia': '33.000.167/0001-01', 'Nome_Companhia': 'PETROBRAS', 'Codigo_CVM': '9512',
           'Data_Referencia': '2025-12-31', 'Data_Entrega': '2026-03-05', 'Categoria': 'Dados Econômico-Financeiros',
           'Tipo': 'Demonstrações Financeiras Anuais Completas', 'Especie': '', 'Assunto': 'Annual statements',
           'Tipo_Apresentacao': 'AP - Apresentação', 'Protocolo_Entrega': '009512IPE2025-1',
           'Versao': '1', 'Link_Download': BR_URL}
    return row | changes


class BrazilTransport:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [br_row()]
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith('cad_cia_aberta.csv'):
            return BR_REGISTRY
        if 'ipe_cia_aberta_' in url:
            text = __import__('io').StringIO()
            writer = csv.DictWriter(text, list(br_row()), delimiter=';')
            writer.writeheader()
            writer.writerows(self.rows)
            return zipped('index.csv', text.getvalue().encode('latin-1'))
        assert url == BR_URL
        return PDF

    def get_to_file(self, url, path, **kwargs):
        path.write_bytes(self.get(url))
        return path


def test_brazil_search_annual_source_identity_and_streamed_original(tmp_path):
    transport = BrazilTransport()
    provider = BrazilCVMProvider(transport=transport)
    assert provider.search_entities('Petrobras')[0].entity_id == '9512'
    company = Company('33.000.167/0001-01', market='BR', provider=provider)
    filing = company.filings(form='annual', start='2026-01-01', end='2026-12-31').latest()
    assert filing.entity_id == '9512'
    assert filing.filing_id == '2026:009512IPE2025-1:1'
    assert filing.filing_date == date(2026, 3, 5)
    assert filing.period_end == date(2025, 12, 31)
    assert filing.amendment is False
    assert filing.provenance.raw['Protocolo_Entrega'] == '009512IPE2025-1'
    assert filing.primary_document.download() == PDF
    target = filing.primary_document.download(tmp_path / 'annual.pdf')
    assert target.read_bytes() == PDF
    assert company.get_filing(filing.filing_id).filing_id == filing.filing_id


def test_brazil_filters_issuer_and_restatements_and_orders_by_delivery():
    rows = [br_row(), br_row(Versao='2', Tipo_Apresentacao='RA - Reapresentação', Data_Entrega='2026-04-01'),
            br_row(Codigo_CVM='4170', CNPJ_Companhia='33.592.510/0001-54', Data_Entrega='2026-05-01')]
    company = Company('9512', market='BR', provider=BrazilCVMProvider(transport=BrazilTransport(rows)))
    assert company.filings(form='annual', start='2026-01-01').latest().filing_id.endswith(':1')
    assert company.filings(form='annual', start='2026-01-01', include_amendments=True).latest().filing_id.endswith(':2')
    with pytest.raises(FilingNotFoundError):
        company.get_filing('2026:foreign:1')


def test_brazil_limit_stops_before_fetching_an_older_year():
    transport = BrazilTransport()
    company = Company('9512', market='BR', provider=BrazilCVMProvider(transport=transport))
    assert len(company.filings(start='2026-01-01', end='2026-12-31', limit=1).head(1)) == 1
    assert not any('2025.zip' in url for url in transport.calls)


def test_brazil_registry_multiple_market_rows_are_one_issuer(monkeypatch):
    monkeypatch.setitem(globals(), 'BR_REGISTRY', BR_REGISTRY + BR_REGISTRY.splitlines(keepends=True)[1])
    provider = BrazilCVMProvider(transport=BrazilTransport())
    assert provider.resolve_entity('9512').entity_id == '9512'
    assert len(provider.search_entities('Petrobras')) == 1


def test_brazil_name_search_ranks_the_active_issuer_before_historical_matches(monkeypatch):
    historical = '00.000.000/0001-00;PETROBRAS OLD SUBSIDIARY;9999;CANCELADO\n'.encode('latin-1')
    header, rows = BR_REGISTRY.split(b'\n', 1)
    monkeypatch.setitem(globals(), 'BR_REGISTRY', header + b'\n' + historical + rows)
    assert BrazilCVMProvider(transport=BrazilTransport()).search_entities('Petrobras', limit=1)[0].entity_id == '9512'


def test_brazil_missing_delivery_protocol_preserves_the_rad_source_key():
    company = Company('9512', market='BR', provider=BrazilCVMProvider(
        transport=BrazilTransport([br_row(Protocolo_Entrega='')])))
    filing = company.filings(start='2026-01-01').latest()
    assert filing.filing_id == '2026:rad-100:1'
    assert filing.provenance.source_id == '100'
    assert filing.provenance.raw['Protocolo_Entrega'] == ''
    assert company.get_filing(filing.filing_id).filing_id == filing.filing_id


def test_brazil_rejects_download_outside_cvm_and_identity_conflicts():
    company = Company('9512', market='BR', provider=BrazilCVMProvider(
        transport=BrazilTransport([br_row(Link_Download='https://other.example/document.pdf')])))
    with pytest.raises((DownloadError, ProviderError)):
        company.filings(start='2026-01-01').latest().primary_document.download()
    company = Company('9512', market='BR', provider=BrazilCVMProvider(
        transport=BrazilTransport([br_row(CNPJ_Companhia='33.592.510/0001-54')])))
    with pytest.raises(ProviderError):
        company.filings(start='2026-01-01').latest()


CL_REGISTRY = b'''<table><tr><th>RUT</th><th>Nombre</th></tr>
<tr><td><a href="entidad.php?rut=90690000&amp;tipoentidad=RVEMI&amp;pestania=1">90690000-9</a></td>
<td><a href="entidad.php?rut=90690000&amp;tipoentidad=RVEMI&amp;pestania=1">EMPRESAS COPEC S.A.</a></td></tr></table>'''
CL_SELECTOR = b'''<div id="contenido"><dl id="datos_ent"><dt>RUT</dt><dd>90690000-9</dd></dl>
<form id="fm"><select name="aa"><option value="2026">2026</option><option value="2025">2025</option></select></form></div>'''
CL_XBRL = b'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ifrs-full="http://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full" xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
<xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="CMF">90690000</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="u"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit><ifrs-full:Assets contextRef="c" unitRef="u" decimals="-3">100000</ifrs-full:Assets></xbrli:xbrl>'''


class ChileTransport:
    def __init__(self, wrong_issuer=False, wrong_period=False):
        self.calls = []
        self.wrong_issuer = wrong_issuer
        self.wrong_period = wrong_period

    def get(self, url, **kwargs):
        self.calls.append(url)
        if 'consulta.php' in url:
            return CL_REGISTRY
        if 'entidad.php' in url:
            return CL_SELECTOR
        if 'send=pdf' in url:
            return PDF
        if 'send=xbrl' in url:
            return zipped('90690000_202512_C.xbrl', CL_XBRL)
        raise AssertionError(url)

    def post_form(self, url, *, data, **kwargs):
        self.calls.append((url, data))
        year, month = data['aa'], data['mm']
        if year == '2026' and month == '09':
            return ('<div id="contenido"><dl id="datos_ent"><dt>RUT</dt><dd>90690000-9</dd></dl>'
                    'No existe información de la entidad para el periodo señalado. '
                    'Verifique que los parámetros de búsqueda son los que solicitó.</div>').encode()
        rut = '11111111-1' if self.wrong_issuer else '90690000-9'
        period = '12 / 2024' if self.wrong_period else f'{month} / {year}'
        return f'''<div id="contenido"><dl id="datos_ent"><dt>RUT</dt><dd>{rut}</dd></dl>
        <p>Fecha de consulta: <strong>19/10/2026 12:00</strong> Periodo: <strong>{period}</strong>
        Tipo de Balance: <strong>CONSOLIDADO</strong></p>
        <a href="/institucional/inc/inf_financiera/ifrs/safec_ifrs_verarchivo.php?auth=fixture&amp;send=pdf">Estados financieros (PDF)</a>
        <a href="/institucional/inc/inf_financiera/ifrs/safec_ifrs_verarchivo.php?auth=fixture&amp;send=xbrl">Estados financieros (XBRL)</a></div>'''.encode()

    def get_to_file(self, url, path, **kwargs):
        path.write_bytes(self.get(url))
        return path


def test_chile_report_period_is_not_a_filing_date_and_originals_are_preserved(tmp_path):
    provider = ChileCMFProvider(transport=ChileTransport())
    company = Company('90690000-9', market='CL', provider=provider)
    filing = company.filings(form='annual').latest()
    assert filing.filing_id == '90690000:202512:C'
    assert filing.period_end == date(2025, 12, 31)
    assert filing.filing_date is None and filing.published_at is None
    assert company.filings().order_basis == 'report_period'
    assert len(filing.documents) == 2
    assert filing.primary_document.download() == PDF
    assert filing.primary_document.download(tmp_path / 'copec.pdf').read_bytes() == PDF
    facts = filing.facts
    assert len(facts) == 1 and facts[0].value == '100000'
    assert facts[0].provenance.jurisdiction == 'CL'
    assert company.get_filing(filing.filing_id).period_end == filing.period_end


def test_chile_skips_an_unfiled_quarter_and_stops_at_the_requested_bound():
    transport = ChileTransport()
    company = Company('90690000', market='CL', provider=ChileCMFProvider(transport=transport))
    filing = company.filings(form='quarterly', limit=1).latest()
    assert filing.period_end == date(2026, 6, 30)
    assert len([x for x in transport.calls if isinstance(x, tuple)]) == 2


@pytest.mark.parametrize('option', ['wrong_issuer', 'wrong_period'])
def test_chile_rejects_a_response_for_another_issuer_or_period(option):
    company = Company('90690000', market='CL', provider=ChileCMFProvider(transport=ChileTransport(**{option: True})))
    with pytest.raises(ProviderError):
        company.filings(form='annual').latest()


def test_country_profiles_and_lookup_errors():
    for market in ['BR', 'CL']:
        assert provider_info(market).auth is None
        assert 'annual' in provider_info(market).forms
    assert not provider_info('CL').date_filters
    with pytest.raises(EntityNotFoundError):
        BrazilCVMProvider(transport=BrazilTransport()).resolve_entity('not a company')
    with pytest.raises(EntityNotFoundError):
        ChileCMFProvider(transport=ChileTransport()).resolve_entity('12345678-0')


def test_request_bounds_and_unsupported_chile_filters():
    provider = BrazilCVMProvider(transport=BrazilTransport(), max_years=1)
    with pytest.raises(UnsupportedCapabilityError, match='max_years'):
        Company('9512', market='BR', provider=provider).filings(start='2024-01-01').latest()
    transport = ChileTransport()
    company = Company('90690000', market='CL', provider=ChileCMFProvider(transport=transport))
    for filters in [{'start': '2025-01-01'}, {'include_amendments': False}, {'form': 'current'}]:
        with pytest.raises(UnsupportedCapabilityError):
            company.filings(**filters)
    assert not transport.calls
    with pytest.raises(FilingNotFoundError):
        company.get_filing('11111111:202512:C')


def test_chile_bound_is_explicit_and_individual_balance_is_verified():
    company = Company('90690000', market='CL', provider=ChileCMFProvider(transport=ChileTransport(), max_periods=1))
    with pytest.raises(UnsupportedCapabilityError, match='max_periods'):
        company.filings(form='quarterly').latest()
    company = Company('90690000', market='CL', provider=ChileCMFProvider(transport=ChileTransport(), consolidated=False))
    with pytest.raises(ProviderError, match='balance'):
        company.filings(form='annual').latest()


@pytest.mark.parametrize('market', ['BR', 'CL'])
def test_wrong_original_format_fails_before_being_returned(market):
    transport = BrazilTransport() if market == 'BR' else ChileTransport()
    original_get = transport.get
    def get(url, **kwargs):
        if 'frmDownloadDocumento.aspx' in url or 'send=pdf' in url:
            return b'<html>Source error, not a PDF</html>'
        return original_get(url, **kwargs)
    transport.get = get
    provider = BrazilCVMProvider(transport=transport) if market == 'BR' else ChileCMFProvider(transport=transport)
    company = Company('9512' if market == 'BR' else '90690000', market=market, provider=provider)
    with pytest.raises(DownloadError):
        company.filings(form='annual').latest().primary_document.download()
