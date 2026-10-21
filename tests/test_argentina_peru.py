"""Original-document and source-identity contracts for CNV and SMV."""

from datetime import date
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from opencorpfilings import Company, EntityNotFoundError, FilingNotFoundError, ProviderError, UnsupportedCapabilityError, provider_info
from opencorpfilings.providers.argentina_cnv import ArgentinaCNVProvider
from opencorpfilings.providers.peru_smv import PeruSMVProvider


PDF = (Path(__file__).parent / 'fixtures/two_page_report.pdf').read_bytes()
UUID = '11111111-2222-3333-4444-555555555555'
BLOB = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
AR_VIEW = 'https://aif2.cnv.gov.ar/presentations/publicview/' + UUID


def roster():
    data = BytesIO()
    with ZipFile(data, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml', '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
        <row><c r="A1" t="inlineStr"><is><t>CUIT</t></is></c><c r="B1" t="inlineStr"><is><t>Sociedad</t></is></c></row>
        <row><c r="A2" t="inlineStr"><is><t>33650305499</t></is></c><c r="B2" t="inlineStr"><is><t>Central Puerto</t></is></c>
        <c r="C2" t="inlineStr"><is><t>Régimen General</t></is></c><c r="D2" t="inlineStr"><is><t>En Oferta Pública</t></is></c></row>
        <row><c r="A3" t="inlineStr"><is><t>33650305499</t></is></c><c r="B3" t="inlineStr"><is><t>Central Puerto</t></is></c>
        <c r="C3" t="inlineStr"><is><t>Other regime</t></is></c><c r="D3" t="inlineStr"><is><t>En Oferta Pública</t></is></c></row>
        </sheetData></worksheet>''')
    return data.getvalue()


def ar_row(description='NORMA CONTABLE: NIIF - TIPO BALANCE: INDIVIDUAL - PERIODICIDAD: 1 - FECHA CIERRE: 2025-12-31', key=UUID):
    return f'<tr><td>6 mar. 2026</td><td>15:01</td><td>{description}</td><td>3491457</td><td><a href="https://aif2.cnv.gov.ar/presentations/publicview/{key}">view</a></td></tr>'


class ArgentinaTransport:
    def __init__(self, wrong_issuer=False, wrong_period=False, foreign_blob=False):
        self.calls = []
        self.wrong_issuer = wrong_issuer
        self.wrong_period = wrong_period
        self.foreign_blob = foreign_blob

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if 'ListadoSociedades' in url:
            return roster()
        if '/Empresa/' in url:
            return (f'<div id="container-res"><h1>CUIT: 33-65030549-9</h1><div class="panel"><h4>Estados Contables</h4><table><tbody>'
                    + ar_row() + ar_row('RELAC.: VINCULADA - CUIT: 30500001735 - PERIODICIDAD: 1 - FECHA CIERRE: 2025-12-31', BLOB)
                    + '</tbody></table></div></div>').encode()
        assert url == AR_VIEW
        cuit = '30500001735' if self.wrong_issuer else '33650305499'
        period = '2024-12-31' if self.wrong_period else '2025-12-31'
        guid = 'https://other.example/file.pdf' if self.foreign_blob else BLOB
        return f'''<title>Presentación #3491457 - Central Puerto | {cuit} - Comisión Nacional de Valores</title>
        <script>var presentation ='<modeloDatos><entidad clave="IdentificacionBalance">
        <propiedad id="PeriodoBalance">1</propiedad><propiedad id="FechaCierre">{period}T03:00:00.000Z</propiedad>
        <propiedad id="TipoBalance">Individual</propiedad></entidad><entidad clave="Adjuntos Balance">
        <propiedad id="ABEstadoContable">[{{"nombreArchivo":"Issuer\\'s report.pdf","guid":"{guid}","hash":"opaque-source-hash"}}]</propiedad>
        </entidad></modeloDatos>';</script>'''.encode()

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert '/GetPublicValetKey/' + BLOB in url
        return {'valetKeyData': 'temporary-public-grant'}

    def post_form(self, url, *, data, **kwargs):
        self.calls.append((url, data))
        assert url == 'https://blob.cnv.gov.ar/BlobWebService.svc/DownloadBlob/' + BLOB
        assert data == {'ValetKey': 'temporary-public-grant'}
        return PDF


def test_argentina_roster_search_financial_scope_and_public_original(tmp_path):
    transport = ArgentinaTransport()
    provider = ArgentinaCNVProvider(transport=transport)
    assert len(provider.search_entities('Puerto')) == 1
    company = Company('33-65030549-9', market='AR', provider=provider)
    filing = company.filings(form='annual', start='2026-01-01').latest()
    assert filing.filing_id == UUID
    assert filing.provenance.source_id == '3491457'
    assert filing.filing_date == date(2026, 3, 6)
    assert filing.period_end == date(2025, 12, 31)
    assert filing.published_at is None and filing.amendment is None
    document = filing.primary_document
    assert document.filename == "Issuer's report.pdf"
    assert document.download(tmp_path / 'ar.pdf').read_bytes() == PDF
    assert document.provenance.raw['source_hash'] == 'opaque-source-hash'
    assert 'temporary-public-grant' not in repr(document.provenance)
    assert len(company.filings(form='annual').head(2)) == 1
    assert company.get_filing(UUID).filing_id == UUID


@pytest.mark.parametrize('option', ['wrong_issuer', 'wrong_period', 'foreign_blob'])
def test_argentina_rejects_cross_issuer_period_and_attachment_identifiers(option):
    company = Company('33650305499', market='AR', provider=ArgentinaCNVProvider(
        transport=ArgentinaTransport(**{option: True})))
    with pytest.raises(ProviderError):
        company.filings(form='annual').latest().documents


def test_argentina_direct_lookup_verifies_issuer_and_does_not_invent_filing_date():
    company = Company('33650305499', market='AR', provider=ArgentinaCNVProvider(transport=ArgentinaTransport()))
    filing = company.get_filing(UUID)
    assert filing.filing_date is None and filing.period_end == date(2025, 12, 31)
    with pytest.raises(FilingNotFoundError):
        company.get_filing('../../other')
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(include_amendments=False)


PE_BASE = 'https://www.smv.gob.pe/SIMV/'
PREFIX = 'ctl00$MainContent$'
XBRL = b'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:e="urn:example">
<xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="SMV">B30006</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
<e:Assets contextRef="c">100</e:Assets></xbrli:xbrl>'''


def pe_controls(company='73', year='2025', kind='A', balance='C'):
    return f'''<input type="hidden" name="__VIEWSTATE" value="synthetic-state">
    <select id="MainContent_cboDenominacionSocial"><option value="73" {'selected' if company == '73' else ''}>ALICORP S.A.A.</option><option value="50" {'selected' if company == '50' else ''}>OTHER ISSUER</option></select>
    <select id="MainContent_cboAnio"><option value="2026" {'selected' if year == '2026' else ''}>2026</option><option value="2025" {'selected' if year == '2025' else ''}>2025</option></select>
    <input type="radio" name="{PREFIX}cboTipo" value="{balance}" checked>
    <input type="radio" name="{PREFIX}cboPeriodo" value="{kind}" checked>'''


class PeruTransport:
    def __init__(self, wrong_issuer=False, wrong_year=False, foreign_link=False, paging=False, broken=False, generic_label=False):
        self.calls = []
        self.wrong_issuer, self.wrong_year = wrong_issuer, wrong_year
        self.foreign_link, self.paging, self.broken = foreign_link, paging, broken
        self.generic_label = generic_label

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url == PE_BASE + 'Default.aspx':
            return b'<a href="Frm_InformacionFinanciera?data=public-category">Emisores</a>'
        if 'Frm_InformacionFinanciera?' in url:
            return pe_controls().encode()
        assert '/ConsultasP8/documento.aspx?' in url
        return XBRL if BLOB in url else PDF

    def post_form(self, url, *, data, **kwargs):
        self.calls.append(data)
        assert data['__VIEWSTATE'] == 'synthetic-state'
        assert data[PREFIX+'TextBox1'] == 'ALICORP S.A.A.'
        year, kind = data[PREFIX+'cboAnio'], data[PREFIX+'cboPeriodo']
        text = pe_controls('50' if self.wrong_issuer else '73', '2024' if self.wrong_year else year, kind).replace('synthetic-state', 'result-state')
        if self.broken:
            return text.encode()
        if year == '2026':
            return (text + '<table id="MainContent_grdInfoFinanciera"><tr><td>No se encontraron registros.</td></tr></table>').encode()
        host = 'https://other.example' if self.foreign_link else 'https://www.smv.gob.pe'
        text += '<table id="MainContent_grdInfoFinanciera">'
        for label, guid in [('Archivo Estructurado XBRL de Información Financiera', BLOB), ('Estados Financieros y Dictamen', UUID)]:
            if self.generic_label:
                if guid == BLOB:
                    continue
                label = 'Informacion Financiera'
            period = '<td>II</td>' if kind == 'T' else ''
            if kind == 'T' and guid == UUID:
                label = 'Notas a los Estados Financieros'
            text += f'<tr>{period}<td>ALICORP S.A.A.</td><td>{label}</td><td>2026015256</td><td>31/03/2026 12:53:16 p.m.</td><td><a href="{host}/ConsultasP8/documento.aspx?vidDoc={{{guid}}}   ">original</a></td></tr>'
        if self.paging:
            text += '<tr><td><a href="javascript:__doPostBack(\'grid\',\'Page$2\')">2</a></td></tr>'
        return (text + '</table>').encode()

    def get_to_file(self, url, path, **kwargs):
        path.write_bytes(self.get(url))
        return path


def test_peru_search_case_grouping_originals_raw_facts_and_direct_lookup(tmp_path):
    transport = PeruTransport()
    provider = PeruSMVProvider(transport=transport)
    company = Company(provider.search_entities('Alicorp')[0], provider=provider)
    filing = company.filings(form='annual', limit=1).latest()
    assert filing.filing_id == '73:2025:A:C:2026015256'
    assert filing.provenance.source_id == '2026015256'
    assert filing.filing_date == date(2026, 3, 31)
    assert filing.period_end is None and filing.published_at is None
    assert company.filings().order_basis == 'report_year'
    assert len(filing.documents) == 2
    assert filing.primary_document.download(tmp_path / 'pe.pdf').read_bytes() == PDF
    assert [fact.value for fact in filing.facts] == ['100']
    assert filing.facts[0].provenance.raw['entry_path'] == ''  # direct XML, no archive member
    assert all(fact.provenance.jurisdiction == 'PE' for fact in filing.facts)
    assert company.get_filing(filing.filing_id).filing_id == filing.filing_id
    assert len([call for call in transport.calls if isinstance(call, dict)]) == 2
    with pytest.raises(EntityNotFoundError):
        provider.resolve_entity('20100055237')  # RUC is not the source selector ID


@pytest.mark.parametrize('option', ['wrong_issuer', 'wrong_year', 'foreign_link', 'paging', 'broken'])
def test_peru_rejects_wrong_selection_links_truncation_and_missing_results(option):
    company = Company('73', market='PE', provider=PeruSMVProvider(transport=PeruTransport(**{option: True})))
    with pytest.raises(ProviderError):
        company.filings(form='annual').latest()


def test_peru_limits_and_unsupported_filters_are_explicit():
    company = Company('73', market='PE', provider=PeruSMVProvider(transport=PeruTransport(), max_years=1))
    with pytest.raises(UnsupportedCapabilityError, match='max_years'):
        company.filings(form='annual').latest()
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(start='2026-01-01')
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(include_amendments=False)
    with pytest.raises(FilingNotFoundError):
        company.get_filing('50:2025:A:C:2026015256')


def test_peru_interim_keeps_source_quarter_and_does_not_call_notes_the_full_report():
    company = Company('73', market='PE', provider=PeruSMVProvider(transport=PeruTransport()))
    filing = company.filings(form='quarterly', limit=1).latest()
    assert filing.provider_metadata['source_quarter'] == 'II'
    assert filing.primary_document.media_type == 'application/xml'
    assert len(filing.documents) == 2
    assert filing.documents[1].role == 'exhibit' and not filing.documents[1].is_primary
    assert len(filing.facts) == 1


def test_peru_misdeclared_utf8_keeps_original_bytes_and_records_parser_encoding(monkeypatch):
    original = b'<?xml version="1.0" encoding="UTF-8"?>' + XBRL.replace(b'>100<', '>COMPAÑÍA<'.encode('cp1252'))
    monkeypatch.setitem(globals(), 'XBRL', original)
    company = Company('73', market='PE', provider=PeruSMVProvider(transport=PeruTransport()))
    filing = company.filings(form='annual', limit=1).latest()
    fact = filing.facts[0]
    assert fact.value == 'COMPAÑÍA'
    assert fact.provenance.raw['parser_encoding'] == 'windows-1252'
    assert next(d for d in filing.documents if d.role == 'data').download() == original


def test_peru_generic_financial_information_label_keeps_the_uploaded_pdf():
    company = Company('73', market='PE', provider=PeruSMVProvider(transport=PeruTransport(generic_label=True)))
    filing = company.filings(form='annual', limit=1).latest()
    assert filing.primary_document.document_type == 'Informacion Financiera'
    assert filing.primary_document.download() == PDF
    with pytest.raises(UnsupportedCapabilityError):
        _ = filing.facts


def test_new_routes_describe_their_actual_formats_without_network():
    assert provider_info('AR').tier == provider_info('PE').tier == 'experimental'
    assert 'pdf' in provider_info('AR').capabilities and 'raw_facts' not in provider_info('AR').capabilities
    assert {'xbrl', 'raw_facts'} <= provider_info('PE').capabilities
