"""Official issuer pools reach both company searches with source terms intact."""

import json

import pytest

from opencorpfilings import directory
from opencorpfilings.directory import build_rows, find_company, search_rows
from opencorpfilings.providers.brazil_cvm import BrazilCVMProvider
from opencorpfilings.providers.chile_cmf import ChileCMFProvider
from scripts import build_find_index
from test_brazil_chile import BrazilTransport, ChileTransport


def country_rows():
    return build_rows(brazil=BrazilCVMProvider(transport=BrazilTransport())._registry(),
                      chile=ChileCMFProvider(transport=ChileTransport())._registry())


@pytest.mark.parametrize('query,market,identifier', [
    ('Petrobras', 'BR', '9512'), ('33.000.167/0001-01', 'BR', '9512'),
    ('33000167000101', 'BR', '9512'), ('9512', 'BR', '9512'),
    ('Copec', 'CL', '90690000'), ('90690000-9', 'CL', '90690000'),
])
def test_search_from_official_pools(query, market, identifier):
    match = search_rows(country_rows(), query, markets=[market])[0]
    assert (match.market, match.identifier, match.tier) == (market, identifier, 'experimental')
    with match.company() as company:
        assert company.provider.name == ('brazil_cvm' if market == 'BR' else 'chile_cmf')


def test_inactive_brazil_issuers_stay_out_and_contact_fields_are_not_republished():
    entities = BrazilCVMProvider(transport=BrazilTransport())._registry()
    entities[0].provider_metadata['SIT'] = 'CANCELADA'
    entities[0].provider_metadata['source_rows'][0]['SIT'] = 'CANCELADA'
    entities[1].provider_metadata['EMAIL'] = 'private-fixture@example.test'
    rows = build_rows(brazil=entities)
    assert [row['identifier'] for row in rows] == ['4170']
    assert 'private-fixture' not in json.dumps(rows)


def test_registry_fetches_are_used_without_any_per_company_requests(monkeypatch):
    from opencorpfilings.providers import edinet, esef
    monkeypatch.delenv('OPENCORPFILINGS_SEC_USER_AGENT', raising=False)
    monkeypatch.setattr(edinet, '_registry_rows', lambda content: [])
    monkeypatch.setattr(esef, 'INDEX_COUNTRIES', set())
    class Pools:
        def __init__(self):
            self.urls = []
        def get(self, url, **kwargs):
            self.urls.append(url)
            if 'cvm.gov.br' in url:
                return BrazilTransport().get(url)
            if 'cmfchile.cl' in url:
                return ChileTransport().get(url)
            return b''
        def get_json(self, url, **kwargs):
            return []
    transport = Pools()
    rows, status = directory._fetch_rows(transport)
    assert {row['market'] for row in rows} == {'BR', 'CL'}
    assert status['brazil']['ok'] and status['chile']['ok']
    assert status['brazil']['license_url'].endswith('/odbl/1-0/')
    assert not any('entidad.php' in url or 'ipe_cia_aberta' in url for url in transport.urls)


def test_old_fresh_cache_rebuilds_to_include_new_countries(tmp_path, monkeypatch):
    path = tmp_path / directory.INDEX_FILE
    path.write_text(json.dumps({'version': 1, 'built_at': directory.datetime.now(directory.timezone.utc).isoformat(),
                                'sources': {}, 'rows': []}), encoding='utf-8')
    monkeypatch.setattr(directory, '_fetch_rows', lambda transport: (country_rows(), {}))
    assert find_company('Copec', live=False, cache_dir=tmp_path)[0].market == 'CL'
    assert json.loads(path.read_text())['version'] == directory.INDEX_VERSION != 1


def test_brazil_subset_is_downloadable_with_its_own_database_license(tmp_path, monkeypatch):
    monkeypatch.setattr(build_find_index, '_fetch_rows', lambda transport: (country_rows(), {}))
    build_find_index.main(str(tmp_path / 'companies.json'))
    main = json.loads((tmp_path / 'companies.json').read_text(encoding='utf-8'))
    cvm = json.loads((tmp_path / 'cvm-companies.json').read_text(encoding='utf-8'))
    assert main['related_datasets'] == ['cvm-companies.json']
    assert {dict(zip(main['fields'], row))['market'] for row in main['rows']} == {'CL'}
    assert {dict(zip(cvm['fields'], row))['market'] for row in cvm['rows']} == {'BR'}
    assert cvm['license']['url'] == 'https://opendatacommons.org/licenses/odbl/1-0/'
    assert 'CVM' in cvm['sources'][0]['name']


def test_fetch_failure_keeps_previous_brazil_and_chile_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(directory, '_fetch_rows', lambda transport: (country_rows(), {}))
    find_company('Copec', live=False, cache_dir=tmp_path)
    monkeypatch.setattr(directory, '_fetch_rows', lambda transport: (
        [], {'brazil': {'ok': False, 'error': 'offline'}, 'chile': {'ok': False, 'error': 'offline'}}))
    with pytest.warns(UserWarning, match='could not be refreshed'):
        assert find_company('Copec', live=False, refresh=True, cache_dir=tmp_path)[0].market == 'CL'
    with pytest.warns(UserWarning, match='could not be refreshed'):
        assert find_company('Petrobras', live=False, cache_dir=tmp_path)[0].market == 'BR'
