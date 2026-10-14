from opencorpfilings.provider import CAPABILITY_NAMES
from opencorpfilings.providers.companies_house import CompaniesHouseProvider
from opencorpfilings.providers.edinet import EDINETProvider
from opencorpfilings.providers.esef import ESEFProvider
from opencorpfilings.providers.open_dart import OpenDARTProvider
from opencorpfilings.providers.sec import SECProvider


def test_all_adapters_use_one_capability_vocabulary():
    common = {"entity_lookup", "filing_discovery", "document_download"}
    for provider in (SECProvider, CompaniesHouseProvider, OpenDARTProvider, EDINETProvider, ESEFProvider):
        assert provider.capabilities <= CAPABILITY_NAMES
        assert common <= provider.capabilities
        assert "text" in provider.capabilities


def test_raw_fact_support_is_explicit():
    for provider in (SECProvider, CompaniesHouseProvider, OpenDARTProvider, EDINETProvider, ESEFProvider):
        assert "raw_facts" in provider.capabilities
    for provider in (SECProvider, CompaniesHouseProvider, EDINETProvider, ESEFProvider):
        assert "ixbrl" in provider.capabilities
