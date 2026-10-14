"""Market-scoped issuer discovery returns source-linked candidates cheaply."""

from __future__ import annotations

import pytest
import httpx

from opencorpfilings import ProviderError, UnsupportedCapabilityError, search_companies
from opencorpfilings.providers.companies_house import CompaniesHouseProvider
from opencorpfilings.providers.sec import SECProvider
from test_companies_house_provider import _public_transport, _transport as uk_transport
from test_sec_provider import _transport as sec_transport
from opencorpfilings.transport import HttpTransport


def test_sec_search_uses_ticker_listing_without_profile_fetch(tmp_path) -> None:
    transport, requests = sec_transport()
    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=transport)
    matches = search_companies("apple", market="US", provider=provider, cache_dir=tmp_path)

    assert len(matches) == 1
    assert matches[0].entity_id == "0000320193"
    assert matches[0].name == "Apple Inc."
    assert matches[0].tickers == ("AAPL",)
    assert matches[0].provenance.source_url.endswith("company_tickers_exchange.json")
    assert [request.url.path for request in requests] == ["/files/company_tickers_exchange.json"]
    assert provider.supports("entity_search")
    assert len(list(tmp_path.glob("*.body"))) == 1


def test_sec_search_ranks_exact_ticker_and_deduplicates_cik() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [1, "Apple Services", "APLS", "NYSE"],
                [2, "Apple Inc.", "AAPL", "Nasdaq"],
                [2, "Apple Inc.", "AAPL", "Nasdaq"],
                [3, "Pineapple Corp", "PAPL", "NYSE"],
            ],
        })

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=transport)
    assert [entity.entity_id for entity in search_companies("apple", market="US", provider=provider)] == [
        "0000000002", "0000000001", "0000000003",
    ]
    assert [entity.entity_id for entity in search_companies("aapl", market="US", provider=provider, limit=1)] == [
        "0000000002",
    ]


def test_uk_search_with_api_key_uses_source_results_without_profiles() -> None:
    transport, requests = uk_transport()
    provider = CompaniesHouseProvider(api_key="fixture-key", transport=transport)
    matches = search_companies("sainsbury", market="UK", provider=provider, limit=3)

    assert len(matches) == 1
    assert matches[0].entity_id == "00185647"
    assert matches[0].name == "J SAINSBURY PLC"
    assert matches[0].identifiers[0].kind == "company_number"
    assert matches[0].provenance.source_url.endswith("/search/companies?q=sainsbury&items_per_page=3")
    assert [request.url.path for request in requests] == ["/search/companies"]


def test_uk_keyless_search_returns_source_linked_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    transport, requests = _public_transport()
    provider = CompaniesHouseProvider(transport=transport)
    matches = search_companies("sainsbury", market="UK", provider=provider)

    assert len(matches) == 1
    assert matches[0].entity_id == "00185647"
    assert matches[0].source_url.endswith("/company/00185647")
    assert matches[0].provenance.source_url.endswith("/search?q=sainsbury")
    assert [request.url.path for request in requests] == ["/search"]


def test_uk_keyless_search_pages_until_unique_limit_and_keeps_page_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("page") == "2":
            return httpx.Response(200, headers={"Cache-Control": "no-store"}, text='''
                <a href="/company/00000002">Second Duplicate</a>
                <a href="/company/00000003">Third Company</a>
                <a href="/company/00000004">Fourth Company</a>
            ''')
        return httpx.Response(200, headers={"Cache-Control": "no-store"}, text='''
            <a href="/company/00000001">First Company</a>
            <a href="/company/00000002">Second Company</a>
            <a href="/search?q=holdings&amp;page=2">Next page</a>
        ''')

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = CompaniesHouseProvider(transport=transport)
    matches = search_companies("holdings", market="UK", provider=provider, limit=3)
    assert [entity.entity_id for entity in matches] == ["00000001", "00000002", "00000003"]
    assert matches[2].provenance.source_url.endswith("/search?q=holdings&page=2")
    assert [request.url.params.get("page") for request in requests] == [None, "2"]
    requests.clear()
    assert [entity.entity_id for entity in search_companies("holdings", market="UK", provider=provider, limit=1)] == ["00000001"]
    assert len(requests) == 1


def test_uk_keyless_search_rejects_offsite_next_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, text='''
            <a href="/company/00000001">First Company</a>
            <a href="https://example.org/search?q=holdings&page=2">Next page</a>
        '''),
    )))
    provider = CompaniesHouseProvider(transport=transport)
    with pytest.raises(ProviderError, match="search page"):
        search_companies("holdings", market="UK", provider=provider, limit=3)


def test_uk_keyless_search_rejects_repeated_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, text='''
            <a href="/company/00000001">First Company</a>
            <a href="/search?q=holdings">Next page</a>
        '''),
    )))
    with pytest.raises(ProviderError, match="repeated a search page"):
        search_companies("holdings", market="UK", provider=CompaniesHouseProvider(transport=transport), limit=3)


def test_search_validates_query_and_limit_before_network() -> None:
    transport, requests = sec_transport()
    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=transport)
    with pytest.raises(ValueError, match="query"):
        search_companies("   ", market="US", provider=provider)
    with pytest.raises(ValueError, match="limit"):
        search_companies("Apple", market="US", provider=provider, limit=0)
    with pytest.raises(ValueError, match="limit"):
        search_companies("Apple", market="US", provider=provider, limit=101)
    assert requests == []


def test_unsupported_provider_reports_search_capability() -> None:
    transport, _ = sec_transport()
    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=transport)
    provider.capabilities = frozenset({"entity_lookup"})
    with pytest.raises(UnsupportedCapabilityError, match="entity search"):
        search_companies("Apple", market="US", provider=provider)
