"""The same public path must work through every enabled source adapter."""

import hashlib
import pytest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from opencorpfilings import Company, search_companies
from opencorpfilings.models import FILING_CATEGORIES
from opencorpfilings.providers.companies_house import CompaniesHouseProvider
from opencorpfilings.providers.denmark_oam import DenmarkOAMProvider
from opencorpfilings.providers.esef import ESEFProvider
from opencorpfilings.providers.finland_oam import FinlandOAMProvider
from opencorpfilings.providers.france_oam import FranceOAMProvider
from opencorpfilings.providers.netherlands_oam import NetherlandsOAMProvider
from opencorpfilings.providers.poland_oam import PolandOAMProvider
from opencorpfilings.providers.sec import SECProvider
from opencorpfilings.providers.spain_cnmv import SpainCNMVProvider
from opencorpfilings.providers.sweden_oam import SwedenOAMProvider
from opencorpfilings.providers.brazil_cvm import BrazilCVMProvider
from opencorpfilings.providers.chile_cmf import ChileCMFProvider
from test_brazil_chile import BrazilTransport, ChileTransport

from test_companies_house_provider import _transport as uk_transport
from test_denmark_oam import DenmarkTransport
from test_esef_provider import FR_LEI, LEI, StubTransport, _row
from test_europe_oam import FR_LEI as NATIONAL_FR_LEI, FranceTransport, FinlandTransport, SpainTransport, SwedenTransport
from test_kr_jp_providers import _dart_provider, _edinet_provider
from test_netherlands_oam import AFMTransport
from test_poland_oam import PolandTransport, _NAME as PL_NAME
from test_sec_provider import _transport as sec_transport


def _html_zip() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("reports/annual.xhtml", "<html><body>Original annual report</body></html>")
    return buffer.getvalue()


class _ReadableFranceTransport(FranceTransport):
    def get(self, url: str, **_: object) -> bytes:
        return _html_zip()


class _ReadableFinlandTransport(FinlandTransport):
    def get(self, url: str, **kwargs: object) -> bytes:
        if "messageAttachmentId=" in url:
            return _html_zip()
        return super().get(url, **kwargs)

    def get_to_file(self, url: str, path: Path, **kwargs: object) -> Path:
        path.write_bytes(self.get(url))
        return path


class _ReadableSpainTransport(SpainTransport):
    def get(self, url: str, **kwargs: object) -> bytes:
        if "e=zip" in url:
            return _html_zip()
        return super().get(url, **kwargs)

    def get_to_file(self, url: str, path: Path, **kwargs: object) -> Path:
        path.write_bytes(self.get(url))
        return path


class _ReadableSwedenTransport(SwedenTransport):
    def get(self, url: str, **kwargs: object) -> bytes:
        if "fid=57992" in url:
            return _html_zip()
        return super().get(url, **kwargs)

    def get_to_file(self, url: str, path: Path, **kwargs: object) -> Path:
        path.write_bytes(self.get(url))
        return path


class _SavingESEFTransport(StubTransport):
    def get_to_file(self, url, path, *, expected_prefix=None, expected_sha256=None):
        content = self.get(url)
        assert expected_prefix is None or content.startswith(expected_prefix)
        assert expected_sha256 is None or hashlib.sha256(content).hexdigest() == expected_sha256
        path.write_bytes(content)
        return path


def _cases():
    transport, _ = sec_transport(instance=True)
    yield "US", "AAPL", SECProvider(user_agent="Example Contact contact@example.com", transport=transport), {"form": "annual", "start": "2024-01-01"}
    transport, _ = uk_transport()
    yield "UK", "00185647", CompaniesHouseProvider(api_key="fixture-key", transport=transport), {"form": "annual", "start": "2026-01-01"}
    provider, _ = _dart_provider()
    yield "KR", "060310", provider, {"form": "annual", "start": "2025-01-01", "end": "2025-12-31", "include_amendments": False}
    provider, _ = _edinet_provider()
    yield "JP", "7203", provider, {"form": "annual", "start": "2025-06-25", "end": "2025-06-26"}
    yield "FI", LEI, ESEFProvider(market="FI", transport=_SavingESEFTransport()), {}
    yield "FR", FR_LEI, ESEFProvider(market="FR", transport=_SavingESEFTransport(lei=FR_LEI, name="PUBLICIS GROUPE SA", rows=[_row(3750, lei=FR_LEI, country="FR")])), {}
    yield "FR", NATIONAL_FR_LEI, FranceOAMProvider(transport=_ReadableFranceTransport()), {"form": "annual"}
    yield "FI", "KONE Oyj", FinlandOAMProvider(transport=_ReadableFinlandTransport()), {"form": "annual", "limit": 1}
    yield "ES", "A-48010615", SpainCNMVProvider(transport=_ReadableSpainTransport()), {"form": "annual", "start": "2025-01-01", "end": "2025-12-31"}
    yield "SE", "502017-7753", SwedenOAMProvider(transport=_ReadableSwedenTransport()), {"form": "annual"}
    yield "PL", PL_NAME, PolandOAMProvider(transport=PolandTransport()), {"form": "annual", "limit": 1}
    yield "NL", "ASML Holding N.V.", NetherlandsOAMProvider(transport=AFMTransport()), {"form": "annual"}
    yield "DK", "DK-61056416", DenmarkOAMProvider(transport=DenmarkTransport()), {"form": "annual", "limit": 1}
    yield "BR", "9512", BrazilCVMProvider(transport=BrazilTransport()), {"form": "annual", "start": "2026-01-01", "end": "2026-12-31"}
    yield "CL", "90690000", ChileCMFProvider(transport=ChileTransport()), {"form": "annual"}


@pytest.mark.parametrize("market,identifier,provider,filters", list(_cases()))
def test_company_to_original_document_across_sources(market, identifier, provider, filters):
    company = Company(identifier, market=market, provider=provider)
    filing = company.filings(**filters).latest()
    assert company.entity.entity_id == filing.entity_id
    assert filing.jurisdiction == market
    assert filing.provider == provider.name
    assert filing.provenance.jurisdiction == market
    assert filing.filing_id
    assert filing.source_url.startswith("https://")
    if provider.name == "sweden_oam":
        # The source exposes a file ID, while the filing key combines issuer,
        # report class and a period label that has no exact filing date.
        assert filing.provenance.source_id == filing.primary_document.document_id
    elif provider.name == "brazil_cvm":
        assert filing.provenance.source_id == filing.provider_metadata["Protocolo_Entrega"]
    else:
        assert filing.provenance.source_id == filing.filing_id
    assert filing.provenance.provider == provider.name
    assert filing.documents
    for original in filing.documents:
        assert original.filing_id == filing.filing_id
        assert original.provenance.provider == provider.name
        assert original.provenance.jurisdiction == market
        assert original._provider is provider
    document = filing.primary_document
    assert document.source_url.startswith("https://")
    assert document.provenance.source_url == document.source_url
    assert document.download()
    assert filing.metadata["filing_type_raw"] == filing.filing_type_raw
    assert filing.filing_type_normalized is None or filing.filing_type_normalized in FILING_CATEGORIES
    assert filing.text()


@pytest.mark.parametrize("market,identifier,provider,filters", list(_cases()))
def test_selected_original_save_across_sources(market, identifier, provider, filters, tmp_path):
    company = Company(identifier, market=market, provider=provider)
    document = company.filings(**filters).latest().primary_document
    destination = tmp_path / "selected-original"

    assert document.download(destination) == destination
    content = destination.read_bytes()
    assert content
    assert document.sha256() == hashlib.sha256(content).hexdigest()
    assert document.provenance.source_url == document.source_url


@pytest.mark.parametrize("market,identifier,provider,filters", list(_cases()))
def test_collection_limit_returns_one_record_across_sources(market, identifier, provider, filters):
    company = Company(identifier, market=market, provider=provider)
    filings = list(company.filings(**{**filters, "limit": 1}))
    assert len(filings) == 1
    assert filings[0].entity_id == company.entity.entity_id


_SEARCH_FIXTURE_LIMITS = {"esef_index", "open_dart", "france_oam", "spain_cnmv"}


@pytest.mark.parametrize(
    "market,identifier,provider,filters",
    [case for case in _cases() if case[2].name not in _SEARCH_FIXTURE_LIMITS],
)
def test_source_search_candidate_to_filing_across_markets(market, identifier, provider, filters):
    resolved = Company(identifier, market=market, provider=provider).entity
    candidates = search_companies(resolved.name, market=market, provider=provider)
    assert len(candidates) <= 10
    assert all(candidate.jurisdiction == market and candidate.provider == provider.name
               and candidate.provenance is not None
               and candidate.provenance.provider == provider.name
               and candidate.provenance.jurisdiction == market
               for candidate in candidates)
    selected = next((item for item in candidates
                     if item.entity_id == resolved.entity_id or item.name == resolved.name), None)
    assert selected is not None, f"{provider.name} search omitted its source issuer"
    company = Company(selected, provider=provider)
    filing = company.filings(**filters).latest()
    assert company.search_result is selected
    assert filing.entity_id == company.entity.entity_id
    assert selected.provenance.provider == provider.name
    assert filing.provenance.provider == provider.name
