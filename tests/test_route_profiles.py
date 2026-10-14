"""Each route declares what it accepts, and a request it cannot serve fails before any source call."""

import json

import pytest

from opencorpfilings import (
    Company, OpenCorpFilingsError, UnsupportedCapabilityError, UnsupportedMarketError, provider_info,
)
from opencorpfilings.transport import HttpTransport


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("validation must happen before any source request")

    for method in ("get", "get_json", "get_to_file", "post_form", "post_json"):
        monkeypatch.setattr(HttpTransport, method, refuse)
    monkeypatch.setenv("OPENCORPFILINGS_SEC_USER_AGENT", "Example Contact contact@example.com")
    monkeypatch.setenv("OPENCORPFILINGS_EDINET_API_KEY", "test-key")
    monkeypatch.setenv("OPENCORPFILINGS_DART_API_KEY", "test-key")


def test_supported_routes_declare_tier_identifiers_forms_and_filters():
    us = provider_info("US")
    assert us.tier == "supported"
    assert "ticker" in us.identifiers and "annual" in us.forms and us.date_filters
    assert {provider_info(market).tier for market in ("US", "UK", "JP", "FR")} == {"supported"}
    esef = provider_info("IT", source="esef_index")
    assert esef.tier == "limited" and esef.forms == ("annual",)
    assert not esef.date_filters and not esef.native_forms
    assert "FY2025" in esef.coverage_note
    assert provider_info("JP").auth and provider_info("UK").auth.startswith("optional")


@pytest.mark.parametrize(("market", "identifier", "kwargs", "message"), [
    ("UK", "00502851", {"form": "interim"}, "annual"),
    ("UK", "00502851", {"form": "anual"}, "annual"),
    ("JP", "7203", {"form": "120"}, "native"),
    ("KR", "005930", {"form": "current"}, "annual"),
    ("FR", "969500XXRPGD7HCAFA90", {"form": "current"}, "interim"),
    ("IT", "WOCMU6HCI0OJWNPRZS33", {"start": "2025-01-01"}, "without start"),
    ("IT", "WOCMU6HCI0OJWNPRZS33", {"include_amendments": False}, "amendment"),
])
def test_unservable_request_fails_before_the_source_is_called(no_network, market, identifier, kwargs, message):
    options = {"source": "esef_index"} if market == "IT" else {}
    company = Company(identifier, market=market, **options)
    with pytest.raises(UnsupportedCapabilityError, match=message):
        company.filings(**kwargs)


def test_category_and_native_form_typos_name_the_allowed_values(no_network):
    with pytest.raises(UnsupportedCapabilityError) as error:
        Company("7203", market="JP").filings(form="anual")
    assert "annual" in str(error.value) and "interim" in str(error.value)


def test_unknown_market_is_a_library_error_with_a_hint():
    with pytest.raises(UnsupportedMarketError, match="UK") as error:
        provider_info("GB")
    assert isinstance(error.value, OpenCorpFilingsError) and isinstance(error.value, ValueError)


def test_cli_lists_every_route_with_its_profile(capsys):
    from opencorpfilings import cli

    assert cli.main(["markets"]) == 0
    routes = json.loads(capsys.readouterr().out)["routes"]
    us = next(route for route in routes if route["market"] == "US")
    assert us["tier"] == "supported" and "CIK" in us["identifiers"]
    assert any(route["source"] == "esef_index" and route["tier"] == "limited" for route in routes)
    keys = [(route["market"], route["source"]) for route in routes]
    assert len(keys) == len(set(keys))
    assert ("IT", None) not in keys and ("IT", "esef_index") in keys


def test_opening_an_experimental_route_warns_once_and_supported_routes_stay_quiet(monkeypatch):
    import warnings

    from opencorpfilings import ExperimentalRouteWarning
    from opencorpfilings import company as company_module

    monkeypatch.setattr(company_module, "_WARNED_ROUTES", set())
    monkeypatch.setenv("OPENCORPFILINGS_SEC_USER_AGENT", "Example Contact contact@example.com")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Company("A28157360", market="ES").close()
        Company("A08663619", market="ES").close()
        Company("AAPL", market="US").close()
        Company("WOCMU6HCI0OJWNPRZS33", market="IT", source="esef_index").close()
    experimental = [w for w in caught if issubclass(w.category, ExperimentalRouteWarning)]
    assert len(experimental) == 1 and "ES/spain_cnmv" in str(experimental[0].message)
