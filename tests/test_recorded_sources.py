"""Discovery replayed against real recorded source responses, one issuer per supported route.

Hand-built fixtures hid real-source shapes (renamed issuers, nested packages,
fiscal-year period fields) behind idealised ones. These responses were recorded
from the live sources by benchmarks/record_fixtures.py and each expected.json
was checked against the source before it was frozen.
"""

import json
from pathlib import Path

import pytest

from benchmarks.recording import replay_client
from opencorpfilings import Company
from opencorpfilings.transport import HttpTransport

ROOT = Path(__file__).parent / "fixtures" / "recorded"


def _provider(route: str, transport: HttpTransport):
    from opencorpfilings.providers.companies_house import CompaniesHouseProvider
    from opencorpfilings.providers.edinet import EDINETProvider
    from opencorpfilings.providers.esef import ESEFProvider
    from opencorpfilings.providers.france_oam import FranceOAMProvider
    from opencorpfilings.providers.open_dart import OpenDARTProvider
    from opencorpfilings.providers.sec import SECProvider

    return {
        "US": lambda: SECProvider(user_agent="Replay Test replay@example.test", transport=transport),
        "UK": lambda: CompaniesHouseProvider(transport=transport),
        "JP": lambda: EDINETProvider(api_key="replay", transport=transport),
        "KR": lambda: OpenDARTProvider(api_key="replay", transport=transport),
        "FR": lambda: FranceOAMProvider(transport=transport),
        "ESEF-AT": lambda: ESEFProvider(market="AT", transport=transport),
    }[route]()


@pytest.mark.parametrize("route", sorted(path.name for path in ROOT.iterdir() if path.is_dir()))
def test_recorded_discovery_reproduces_the_checked_snapshot(route, monkeypatch):
    from benchmarks.record_fixtures import snapshot

    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    expected = json.loads((ROOT / route / "expected.json").read_text(encoding="utf-8"))
    transport = HttpTransport(client=replay_client(ROOT / route))
    with Company(expected["identifier"], market=expected["market"], provider=_provider(route, transport)) as company:
        actual = snapshot(company.filings(**expected["query"]).latest())
    assert actual == {key: value for key, value in expected.items() if key not in {"identifier", "market", "query"}}
