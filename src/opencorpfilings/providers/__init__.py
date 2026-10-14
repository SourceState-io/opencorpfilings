"""Market routing; adapter modules are loaded only when selected."""

from __future__ import annotations

from importlib import import_module

from ..errors import UnsupportedCapabilityError, UnsupportedMarketError
from ..provider import FilingProvider, ProviderInfo


_ORIGINAL = {
    "US": ("sec", "SECProvider"),
    "UK": ("companies_house", "CompaniesHouseProvider"),
    "KR": ("open_dart", "OpenDARTProvider"),
    "JP": ("edinet", "EDINETProvider"),
}
# Common codes that are not this library's market codes.
_ALIASES = {"GB": "UK", "USA": "US", "JA": "JP", "JPN": "JP", "KOR": "KR", "FRA": "FR"}
# Eleven small-market national routes were retired on 2026-10-09 (IS, LT, LV,
# HR, RO, SK, EE, MT, CY, HU, LI); git commit 66e33904 holds their code.
_NATIONAL = {
    "FR": ("france_oam", "FranceOAMProvider"),
    "FI": ("finland_oam", "FinlandOAMProvider"),
    "ES": ("spain_cnmv", "SpainCNMVProvider"),
    "SE": ("sweden_oam", "SwedenOAMProvider"),
    "PL": ("poland_oam", "PolandOAMProvider"),
    "NL": ("netherlands_oam", "NetherlandsOAMProvider"),
    "DK": ("denmark_oam", "DenmarkOAMProvider"),
}


def supported_markets() -> tuple[str, ...]:
    """Markets with at least one implemented source route, including ESEF-only routes."""
    from .esef import INDEX_COUNTRIES

    return tuple(sorted(_ORIGINAL.keys() | _NATIONAL.keys() | INDEX_COUNTRIES))


def _provider_type(market: str, source: str | None) -> type[FilingProvider]:
    from .esef import INDEX_COUNTRIES

    if source is not None and source not in {"oam", "esef_index"}:
        raise ValueError("source must be 'oam' or 'esef_index'")
    if source == "esef_index" and market not in INDEX_COUNTRIES:
        raise ValueError("source='esef_index' is available only for a verified ESEF index country")
    if source == "oam" and market not in _NATIONAL and market not in INDEX_COUNTRIES:
        raise ValueError("source='oam' is available only for a market with a national OAM route")
    if market in _ORIGINAL:
        module, name = _ORIGINAL[market]
    elif market in _NATIONAL and source != "esef_index":
        module, name = _NATIONAL[market]
    elif market in INDEX_COUNTRIES:
        if source == "oam":
            raise UnsupportedCapabilityError(f"this library has no national OAM route for {market}; use the ESEF index")
        module, name = "esef", "ESEFProvider"
    elif market == "HK":
        raise UnsupportedCapabilityError("HKEX automated access is pending an authorized source route")
    else:
        hint = f" (did you mean {_ALIASES[market]!r}?)" if market in _ALIASES else ""
        raise UnsupportedMarketError(
            f"unsupported market {market!r}{hint}; `ocf markets` or supported_markets() lists the routes"
        )
    return getattr(import_module(f".{module}", __name__), name)


def provider_info(market: str, *, source: str | None = None) -> ProviderInfo:
    """Inspect a route's declared capabilities without credentials or network access."""
    market = market.upper()
    return _provider_type(market, source).info(market)


def provider_for_market(market: str, **options: object) -> FilingProvider:
    market = market.upper()
    source = options.pop("source", None)
    provider_type = _provider_type(market, source)
    if provider_type.name == "esef_index":
        return provider_type(market=market, **options)
    return provider_type(**options)
