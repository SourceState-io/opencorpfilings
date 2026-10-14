"""Issuer selectors support the same source-scoped search workflow as other markets."""

import pytest

from opencorpfilings import Company, search_companies
from opencorpfilings.providers.finland_oam import FinlandOAMProvider
from opencorpfilings.providers.spain_cnmv import SpainCNMVProvider
from test_europe_oam import FinlandTransport, SpainTransport


@pytest.mark.parametrize("market,query,source_id,provider", [
    ("FI", "kone", "552", FinlandOAMProvider(transport=FinlandTransport())),
])
def test_source_issuer_search_and_id_roundtrip(market, query, source_id, provider, monkeypatch):
    matches = search_companies(query, market=market, provider=provider, limit=1)
    assert len(matches) == 1
    assert matches[0].entity_id == source_id
    assert matches[0].provenance.provider == provider.name
    assert matches[0].source_url.startswith("https://")
    assert Company(source_id, market=market, provider=provider).entity.entity_id == source_id
    monkeypatch.setattr(provider, "resolve_entity", lambda *_: (_ for _ in ()).throw(
        AssertionError("source candidate must not be resolved again")))
    with Company(matches[0], provider=provider) as company:
        assert company.entity is matches[0]
        assert company.identifier == source_id
    assert provider.supports("entity_search")
    assert search_companies("no matching issuer", market=market, provider=provider) == []
    assert provider.transport.posts == []


def test_searched_finland_entity_runs_the_common_filing_workflow():
    provider = FinlandOAMProvider(transport=FinlandTransport())
    selected = search_companies("kone", market="FI", provider=provider, limit=1)[0]
    with Company(selected, provider=provider) as company:
        filing = company.filings(form="annual").latest()
        assert filing.entity_id == selected.entity_id
        assert filing.source_url.startswith("https://")
        assert filing.documents
        assert company.entity is selected


class SpainSearchTransport(SpainTransport):
    def __init__(self) -> None:
        self.gets: list[str] = []
        self.posts: list[dict[str, str]] = []

    def get(self, url: str, **kwargs: object) -> bytes:
        self.gets.append(url)
        if "busquedaporentidad" in url:
            return (b'<form><input type="hidden" name="__VIEWSTATE" value="state">'
                    b'<input type="hidden" name="__EVENTVALIDATION" value="validation">'
                    b'<input name="ctl00$ContentPrincipal$txtBusqueda" type="text">'
                    b'<input name="ctl00$ContentPrincipal$btnBuscar" type="submit" value="Search"></form>')
        return super().get(url, **kwargs)

    def post_form(self, url: str, *, data: dict[str, str], **kwargs: object) -> bytes:
        assert "busquedaporentidad" in url
        self.posts.append(data)
        if data["ctl00$ContentPrincipal$txtBusqueda"] == "Iberdrola":
            return (b'<select id="ctl00_ContentPrincipal_wuc_Entidades_lstSeleccion">'
                    b'<option value="A-48010615">IBERDROLA, S.A.</option>'
                    b'<option value="A95573283">IBERDROLA FINANCIACION, S.A.</option>'
                    b'</select>')
        return b'<form><input name="ctl00$ContentPrincipal$txtBusqueda"></form>'


def test_spain_source_issuer_search_returns_nif_candidates_without_profiles():
    transport = SpainSearchTransport()
    provider = SpainCNMVProvider(transport=transport)
    matches = search_companies("Iberdrola", market="ES", provider=provider, limit=1)
    assert [(entity.entity_id, entity.name) for entity in matches] == [
        ("A-48010615", "IBERDROLA, S.A.")]
    assert matches[0].source_url.startswith("https://www.cnmv.es/portal/consultas/busquedaporentidad")
    assert matches[0].provenance.source_id == "A-48010615"
    assert transport.gets == [matches[0].source_url]
    assert transport.posts[0]["__VIEWSTATE"] == "state"
    assert transport.posts[0]["__EVENTVALIDATION"] == "validation"
    assert Company(matches[0].entity_id, market="ES", provider=provider).entity.name == "IBERDROLA, S.A."
    assert Company(matches[0], provider=provider).filings(form="annual").latest().entity_id == matches[0].entity_id
    assert search_companies("zzzxqyfilingsnomatch", market="ES", provider=provider) == []


def test_spain_single_issuer_search_redirect_returns_source_nif() -> None:
    class SingleResultTransport(SpainSearchTransport):
        def post_form(self, url: str, *, data: dict[str, str], **kwargs: object) -> bytes:
            return (b'<html><head><title>CNMV - Entity Information - '
                    b'INDUSTRIA DE DISENO TEXTIL, S.A.</title></head>'
                    b'<body><form action="./DatosEntidad?nif=A-15075062"></form></body></html>')

    provider = SpainCNMVProvider(transport=SingleResultTransport())
    matches = search_companies("Inditex", market="ES", provider=provider)
    assert [(entity.entity_id, entity.name) for entity in matches] == [
        ("A-15075062", "INDUSTRIA DE DISENO TEXTIL, S.A.")]
    assert matches[0].source_url == "https://www.cnmv.es/portal/consultas/DatosEntidad?nif=A-15075062"
    assert matches[0].provenance.source_id == "A-15075062"
