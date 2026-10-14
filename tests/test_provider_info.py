"""Market capability discovery has no source or credential side effects."""

import pytest

from opencorpfilings import provider_info, supported_markets
from opencorpfilings.errors import UnsupportedCapabilityError
from opencorpfilings.providers.esef import INDEX_COUNTRIES


def test_provider_info_uses_the_same_native_and_index_routes_without_auth(monkeypatch):
    monkeypatch.delenv("OPENCORPFILINGS_SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("OPENCORPFILINGS_DART_API_KEY", raising=False)
    assert provider_info("us").provider == "sec"
    assert "entity_search" in provider_info("US").capabilities
    assert provider_info("SE").provider == "sweden_oam"
    assert provider_info("SE", source="esef_index").provider == "esef_index"
    assert provider_info("NO").provider == "esef_index"
    assert provider_info("KR").provider == "open_dart"


def test_supported_markets_and_unsupported_source_are_honest():
    markets = supported_markets()
    assert markets == tuple(sorted(set(markets)))
    assert {"US", "UK", "KR", "JP", "SE", "NO"} <= set(markets)
    assert "HK" not in markets
    with pytest.raises(UnsupportedCapabilityError):
        provider_info("NO", source="oam")
    with pytest.raises(UnsupportedCapabilityError):
        provider_info("HK")
    with pytest.raises(ValueError, match="source"):
        provider_info("SE", source="unknown")


def test_every_advertised_route_has_a_loadable_provider_contract():
    for market in supported_markets():
        info = provider_info(market)
        assert info.market == market
        assert info.provider and info.regulator
        assert {"entity_lookup", "filing_discovery", "document_download"} <= info.capabilities
    for market in INDEX_COUNTRIES:
        assert provider_info(market, source="esef_index").provider == "esef_index"
