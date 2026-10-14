from datetime import date, datetime
import os

import pytest

from opencorpfilings import (
    Company,
    Entity,
    Filing,
    FilingDocument,
    FilingFact,
    FilingNotFoundError,
    ProviderError,
    DownloadError,
    FilingProvider,
    FilingSection,
    Provenance,
    search_companies,
    UnsupportedCapabilityError,
)


class FakeProvider(FilingProvider):
    name = "fixture"
    market = "US"
    regulator = "Fixture Commission"
    capabilities = frozenset({"entity_lookup", "filing_discovery", "document_download"})

    def resolve_entity(self, identifier):
        return Entity(identifier, "Fixture Inc", "US", self.name, "https://example.test/company")

    def iter_filings(self, entity, *, form=None, start=None, end=None, include_amendments=True, limit=None):
        if form and form != "annual":
            return
        if end and end < date(2024, 1, 1):
            return
        provenance = Provenance(self.name, self.regulator, "US", "https://example.test/filing", "f1")
        yield Filing(
            "f1", entity.entity_id, "US", self.name, self.regulator,
            "https://example.test/filing", provenance,
            filing_type_raw="10-K", filing_type_normalized="ANNUAL",
            filing_date=date(2024, 2, 1),
        )

    def list_documents(self, filing):
        return [FilingDocument(
            "d1", filing.filing_id, "annual.htm", "https://example.test/annual.htm",
            Provenance(self.name, self.regulator, "US", "https://example.test/annual.htm", "d1"),
            media_type="text/html", is_primary=True,
        )]

    def download_document(self, document):
        return b"<h1>Fixture report</h1>"

    def extract_text(self, document):
        return "Fixture report"

    def raw_facts(self, filing) -> list[FilingFact]:
        raise UnsupportedCapabilityError("fixture has no structured facts")


def test_text_search_is_outside_the_public_filing_contract():
    import opencorpfilings

    assert not hasattr(Filing, "search_text")
    assert not hasattr(FilingDocument, "search_text")
    assert not hasattr(opencorpfilings, "TextMatch")


def test_company_to_one_source_document(tmp_path):
    company = Company("FIX", market="US", provider=FakeProvider())
    filings = company.filings(form="annual", start="2024-01-01")
    assert filings.order_basis == "filing_date"
    filing = filings.latest()
    assert filing.metadata["filing_type_raw"] == "10-K"
    assert filing.provenance.source_url == filing.source_url
    assert filing.primary_document.provenance.source_id == "d1"
    assert filing.text() == "Fixture report"
    assert filing.download() == b"<h1>Fixture report</h1>"
    assert filing.primary_document.download(tmp_path / "one.htm").read_bytes() == b"<h1>Fixture report</h1>"
    with pytest.raises(UnsupportedCapabilityError):
        _ = filing.facts


@pytest.mark.parametrize("filters,field,value", [
    ({"form": "interim"}, "filing_type_normalized", "ANNUAL"),
    ({"start": "2025-01-01"}, "filing_date", date(2024, 2, 1)),
    ({"end": "2023-12-31"}, "filing_date", date(2024, 2, 1)),
    ({"include_amendments": False}, "amendment", True),
])
def test_collection_rejects_provider_rows_outside_requested_filter(filters, field, value):
    class OverReturningProvider(FakeProvider):
        def iter_filings(self, entity, **kwargs):
            filing = next(super().iter_filings(entity))
            setattr(filing, field, value)
            yield filing

    company = Company("FIX", market="US", provider=OverReturningProvider())
    with pytest.raises(ProviderError, match="requested"):
        company.filings(**filters).latest()


def test_collection_rejects_unknown_filing_date_for_date_filter():
    class UndatedProvider(FakeProvider):
        def iter_filings(self, entity, **kwargs):
            filing = next(super().iter_filings(entity))
            filing.filing_date = None
            yield filing

    company = Company("FIX", market="US", provider=UndatedProvider())
    with pytest.raises(UnsupportedCapabilityError, match="filing date"):
        company.filings(start="2024-01-01").latest()


def test_collection_rejects_unknown_category_for_form_filter():
    class UnclassifiedProvider(FakeProvider):
        def iter_filings(self, entity, **kwargs):
            filing = next(super().iter_filings(entity))
            filing.filing_type_normalized = None
            filing.filing_type_raw = None
            yield filing

    company = Company("FIX", market="US", provider=UnclassifiedProvider())
    with pytest.raises(UnsupportedCapabilityError, match="filing type"):
        company.filings(form="annual").latest()


def test_company_accepts_a_source_entity_without_resolving_it_again():
    class NoLookupProvider(FakeProvider):
        def resolve_entity(self, identifier):
            raise AssertionError("the source entity must be reused")

    provider = NoLookupProvider()
    provenance = Provenance(provider.name, provider.regulator, "US", "https://example.test/company", "FIX")
    entity = Entity("FIX", "Source name", "US", provider.name,
                    "https://example.test/company", provenance=provenance)
    with Company(entity, provider=provider) as company:
        assert company.identifier == "FIX"
        assert company.market == "US"
        assert company.entity is entity
        assert company.filings(form="annual").latest().entity_id == "FIX"
    assert company.entity.provenance is provenance


def test_search_result_limit_is_enforced_after_provider_returns():
    class OverReturningProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"entity_search"}

        def search_entities(self, query, *, limit=10):
            self.requested_limit = limit
            return [Entity(
                f"ID-{number}", f"Source issuer {number}", "US", self.name,
                f"https://example.test/company/{number}",
                provenance=Provenance(self.name, self.regulator, "US",
                                      "https://example.test/search", f"ID-{number}"),
            ) for number in range(3)]

    provider = OverReturningProvider()
    results = search_companies("Source", market="US", limit=1, provider=provider)
    assert [item.entity_id for item in results] == ["ID-0"]
    assert provider.requested_limit == 1


@pytest.mark.parametrize("field,value", [
    ("jurisdiction", "UK"), ("provider", "another_provider"),
    ("provenance_provider", "another_provider"),
    ("provenance_jurisdiction", "UK"),
])
def test_search_rejects_candidates_from_another_route(field, value):
    class WrongRouteProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"entity_search"}

        def search_entities(self, query, *, limit=10):
            entity = Entity(
                "ID-1", "Source issuer", "US", self.name,
                "https://example.test/company/1",
                provenance=Provenance(self.name, self.regulator, "US",
                                      "https://example.test/search", "ID-1"),
            )
            if field.startswith("provenance_"):
                entity.provenance = Provenance(
                    value if field == "provenance_provider" else self.name,
                    self.regulator, value if field == "provenance_jurisdiction" else "US",
                    "https://example.test/search", "ID-1",
                )
            else:
                setattr(entity, field, value)
            return [entity]

    with pytest.raises(ProviderError, match="does not match the selected market and provider"):
        search_companies("Source", market="US", provider=WrongRouteProvider())


def test_search_candidate_requires_source_provenance():
    class UnattributedProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"entity_search"}

        def search_entities(self, query, *, limit=10):
            return [Entity("ID-1", "Source issuer", "US", self.name,
                           "https://example.test/company/1")]

    with pytest.raises(ProviderError, match="lacks source provenance"):
        search_companies("Source", market="US", provider=UnattributedProvider())


def test_company_entity_preserves_source_route_and_rejects_mismatches(monkeypatch):
    class IndexProvider(FakeProvider):
        name = "esef_index"

    selected = IndexProvider()
    entity = Entity("FIX", "Index issuer", "US", "esef_index", "https://example.test/index")
    calls = []

    def make_provider(market, **options):
        calls.append((market, options))
        return selected

    monkeypatch.setattr("opencorpfilings.providers.provider_for_market", make_provider)
    assert Company(entity).entity is entity
    assert calls == [("US", {"source": "esef_index"})]
    with pytest.raises(ValueError, match="provider.*does not match entity"):
        Company(entity, provider=FakeProvider())
    with pytest.raises(ValueError, match="entity jurisdiction"):
        Company(entity, market="UK", provider=selected)
    with pytest.raises(ValueError, match="source route"):
        Company(entity, source="oam")


def test_unresolved_search_candidate_requires_matching_source_identity():
    class WrongLookupProvider(FakeProvider):
        def resolve_entity(self, identifier):
            return Entity("FIX", "Wrong route", "US", "another_provider", "https://example.test/wrong")

    candidate = Entity("candidate-id", "Candidate", "US", "fixture",
                       "https://example.test/search", requires_resolution=True)
    company = Company(candidate, provider=WrongLookupProvider())
    assert company.search_result is candidate
    with pytest.raises(ValueError, match="resolved entity does not match"):
        _ = company.entity


def test_company_rejects_provider_for_a_different_market():
    provider = FakeProvider()
    with pytest.raises(ValueError, match="serves US, not UK"):
        Company("FIX", market="UK", provider=provider)


def test_company_context_only_closes_a_provider_it_created(monkeypatch):
    class ClosingProvider(FakeProvider):
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    external = ClosingProvider()
    with Company("FIX", market="US", provider=external) as company:
        assert company.filings().latest().filing_id == "f1"
    assert external.close_calls == 0
    with Company("FIX", market="US", provider=external) as company:
        assert company.entity.entity_id == "FIX"
    assert external.close_calls == 0

    owned = ClosingProvider()
    monkeypatch.setattr("opencorpfilings.providers.provider_for_market", lambda *_args, **_kwargs: owned)
    with Company("FIX", market="US") as company:
        assert company.entity.entity_id == "FIX"
    assert owned.close_calls == 1


def test_document_list_edits_do_not_change_cached_filing_documents():
    class CountingProvider(FakeProvider):
        calls = 0

        def list_documents(self, filing):
            self.calls += 1
            return super().list_documents(filing)

    provider = CountingProvider()
    filing = Company("FIX", market="US", provider=provider).filings().latest()
    first = filing.documents[0]
    filing.documents.clear()

    assert filing.documents == [first]
    assert filing.primary_document is first
    assert provider.calls == 1


@pytest.mark.parametrize("field,value", [
    ("filing_id", "another-filing"),
    ("provider", "another_provider"),
    ("jurisdiction", "UK"),
    ("source_url", "https://example.test/another-document"),
])
def test_document_list_rejects_wrong_filing_or_source(field, value):
    class WrongDocumentProvider(FakeProvider):
        def list_documents(self, filing):
            document = super().list_documents(filing)[0]
            if field == "filing_id":
                document.filing_id = value
            else:
                document.provenance = Provenance(
                    value if field == "provider" else self.name,
                    self.regulator, value if field == "jurisdiction" else "US",
                    value if field == "source_url" else document.source_url,
                    document.document_id,
                )
            return [document]

    filing = Company("FIX", market="US", provider=WrongDocumentProvider()).filings().latest()
    with pytest.raises(ProviderError, match="does not belong to this filing's source"):
        _ = filing.documents


def test_fast_primary_document_rejects_wrong_filing():
    class WrongPrimaryProvider(FakeProvider):
        def get_primary_document(self, filing):
            document = super().list_documents(filing)[0]
            document.filing_id = "another-filing"
            return document

    filing = Company("FIX", market="US", provider=WrongPrimaryProvider()).filings().latest()
    with pytest.raises(ProviderError, match="does not belong to this filing's source"):
        _ = filing.primary_document


def test_document_uses_the_selected_filing_provider():
    class ForeignProvider(FakeProvider):
        def download_document(self, document):
            raise AssertionError("a document must not use a foreign provider instance")

    class MisboundProvider(FakeProvider):
        def list_documents(self, filing):
            document = super().list_documents(filing)[0]
            document._provider = ForeignProvider()
            return [document]

    provider = MisboundProvider()
    filing = Company("FIX", market="US", provider=provider).filings().latest()
    assert filing.primary_document.download() == b"<h1>Fixture report</h1>"
    assert filing.primary_document._provider is provider


def test_invalid_fast_primary_is_not_cached():
    class CorrectingProvider(FakeProvider):
        calls = 0

        def get_primary_document(self, filing):
            self.calls += 1
            document = super().list_documents(filing)[0]
            if self.calls == 1:
                document.filing_id = "another-filing"
            return document

    provider = CorrectingProvider()
    filing = Company("FIX", market="US", provider=provider).filings().latest()
    with pytest.raises(ProviderError):
        _ = filing.primary_document
    assert filing.primary_document.filing_id == filing.filing_id
    assert provider.calls == 2


def test_document_selection_uses_exact_source_id_language_and_description() -> None:
    filing = Company("FIX", market="US", provider=FakeProvider()).filings().latest()
    primary = filing.primary_document
    english = FilingDocument(
        "source:en", filing.filing_id, "report-en.xhtml", "https://example.test/report-en.xhtml",
        Provenance("fixture", "Fixture Commission", "US", "https://example.test/report-en.xhtml", "source:en"),
        media_type="application/xhtml+xml", document_type="original", language="en",
        description="English annual report", _provider=filing._provider,
    )
    japanese = FilingDocument(
        "source:ja", filing.filing_id, "report-ja.xhtml", "https://example.test/report-ja.xhtml",
        Provenance("fixture", "Fixture Commission", "US", "https://example.test/report-ja.xhtml", "source:ja"),
        media_type="application/xhtml+xml", document_type="original", language="ja",
        description="Japanese annual report", _provider=filing._provider,
    )
    filing._documents = [primary, english, japanese]

    assert filing.select_document() is primary
    assert filing.select_document(document_id="source:en") is english
    assert filing.select_document(language="ja", document_type="original") is japanese
    assert filing.select_document(description="English annual report") is english
    with pytest.raises(ValueError, match="refine the selection"):
        filing.select_document(document_type="original")
    with pytest.raises(UnsupportedCapabilityError, match="no document matching"):
        filing.select_document(language="JA")


def test_direct_filing_lookup_binds_provider_for_the_same_document_workflow():
    class DirectProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"direct_filing_lookup"}

        def get_filing(self, entity, filing_id):
            assert filing_id == "f1"
            return next(self.iter_filings(entity))

    company = Company("FIX", market="US", provider=DirectProvider())
    filing = company.get_filing("f1")
    assert filing.text() == "Fixture report"
    assert filing.primary_document.download() == b"<h1>Fixture report</h1>"


def test_empty_and_bad_filters():
    company = Company("F", market="US", provider=FakeProvider())
    with pytest.raises(FilingNotFoundError):
        company.filings(form="interim").latest()
    with pytest.raises(ValueError):
        company.filings(start="2025-01-01", end="2024-01-01")
    with pytest.raises(ValueError):
        company.filings(limit=0)


def test_collection_head_passes_its_bound_to_provider():
    class BoundedProvider(FakeProvider):
        def __init__(self):
            self.limits = []

        def iter_filings(self, entity, **kwargs):
            self.limits.append(kwargs["limit"])
            yield from super().iter_filings(entity, **kwargs)

    provider = BoundedProvider()
    filings = Company("FIX", market="US", provider=provider).filings()
    assert filings.head(2)[0].filing_id == "f1"
    assert filings.latest().filing_id == "f1"
    assert provider.limits == [2, 1]


def test_collection_index_and_slice_read_only_the_pages_they_need():
    class ThreeFilingProvider(FakeProvider):
        def __init__(self):
            self.limits = []

        def iter_filings(self, entity, **kwargs):
            self.limits.append(kwargs["limit"])
            for number in range(3):
                filing = next(super().iter_filings(entity))
                filing.filing_id = f"f{number + 1}"
                yield filing

    provider = ThreeFilingProvider()
    filings = Company("FIX", market="US", provider=provider).filings()
    assert filings[0].filing_id == "f1"
    assert filings[2].filing_id == "f3"
    assert [filing.filing_id for filing in filings[1:3]] == ["f2", "f3"]
    assert [filing.filing_id for filing in filings[:5]] == ["f1", "f2", "f3"]
    assert provider.limits == [1, 3, 3, 5]
    with pytest.raises(IndexError):
        filings[3]
    with pytest.raises(IndexError, match="latest"):
        filings[-1]
    with pytest.raises(IndexError, match="latest"):
        filings[1:]
    bounded = Company("FIX", market="US", provider=ThreeFilingProvider()).filings(limit=2)
    assert bounded[-1].filing_id == "f2"
    assert [filing.filing_id for filing in bounded[1:]] == ["f2"]


def test_collection_limit_bounds_results_even_if_provider_over_returns():
    class OverReturningProvider(FakeProvider):
        def __init__(self):
            self.limits = []

        def iter_filings(self, entity, **kwargs):
            self.limits.append(kwargs["limit"])
            for number in range(3):
                filing = next(super().iter_filings(entity))
                filing.filing_id = f"f{number + 1}"
                yield filing

    provider = OverReturningProvider()
    filings = list(Company("FIX", market="US", provider=provider).filings(limit=1))
    assert [filing.filing_id for filing in filings] == ["f1"]
    assert provider.limits == [1]


@pytest.mark.parametrize("field,value", [
    ("entity_id", "OTHER"), ("jurisdiction", "UK"), ("provider", "another_provider"),
])
def test_collection_rejects_filings_outside_selected_source(field, value):
    class WrongSourceProvider(FakeProvider):
        def iter_filings(self, entity, **kwargs):
            filing = next(super().iter_filings(entity, **kwargs))
            setattr(filing, field, value)
            yield filing

    company = Company("FIX", market="US", provider=WrongSourceProvider())
    with pytest.raises(ProviderError, match="does not match the selected entity and provider"):
        company.filings().latest()


def test_direct_filing_lookup_rejects_another_source_provider():
    class WrongSourceProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"direct_filing_lookup"}

        def get_filing(self, entity, filing_id):
            filing = next(self.iter_filings(entity))
            filing.provider = "another_provider"
            return filing

    company = Company("FIX", market="US", provider=WrongSourceProvider())
    with pytest.raises(ProviderError, match="does not match the selected entity and provider"):
        company.get_filing("f1")
    with pytest.raises(ProviderError, match="does not match the selected entity and provider"):
        company.filings().get("f1")


@pytest.mark.parametrize("field,value", [
    ("provider", "another_provider"), ("jurisdiction", "UK"),
])
def test_collection_rejects_mismatched_filing_provenance(field, value):
    class WrongProvenanceProvider(FakeProvider):
        def iter_filings(self, entity, **kwargs):
            filing = next(super().iter_filings(entity, **kwargs))
            values = {name: getattr(filing.provenance, name)
                      for name in filing.provenance.__dataclass_fields__}
            values[field] = value
            filing.provenance = Provenance(**values)
            yield filing

    company = Company("FIX", market="US", provider=WrongProvenanceProvider())
    with pytest.raises(ProviderError, match="has inconsistent source provenance"):
        company.filings().latest()


def test_filing_id_scan_passes_max_scan_to_provider_before_iteration():
    class ScanProvider(FakeProvider):
        def __init__(self):
            self.limits = []

        def iter_filings(self, entity, **kwargs):
            limit = kwargs["limit"]
            self.limits.append(limit)
            assert limit is not None, "one-filing lookup must not start an unbounded provider scan"
            for number in range(limit):
                filing = next(super().iter_filings(entity))
                filing.filing_id = f"f{number + 1}"
                yield filing

    provider = ScanProvider()
    company = Company("FIX", market="US", provider=provider)
    assert company.filings().get("f2", max_scan=3).filing_id == "f2"
    assert company.get_filing("f2", max_scan=3).filing_id == "f2"
    with pytest.raises(FilingNotFoundError):
        company.filings(limit=1).get("f2", max_scan=3)
    assert provider.limits == [3, 3, 1]


def test_unfiltered_collection_get_uses_verified_direct_lookup():
    class DirectProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"direct_filing_lookup"}

        def __init__(self):
            self.direct_calls = 0
            self.list_calls = 0

        def get_filing(self, entity, filing_id):
            self.direct_calls += 1
            filing = next(super().iter_filings(entity))
            filing.filing_id = filing_id
            return filing

        def iter_filings(self, entity, **kwargs):
            self.list_calls += 1
            yield from super().iter_filings(entity, **kwargs)

    provider = DirectProvider()
    company = Company("FIX", market="US", provider=provider)
    filing = company.filings().get("source-id", max_scan=1)
    assert filing.filing_id == "source-id"
    assert filing.text() == "Fixture report"
    assert (provider.direct_calls, provider.list_calls) == (1, 0)

    company.filings(form="annual").get("f1")
    company.filings(limit=1).get("f1")
    assert (provider.direct_calls, provider.list_calls) == (2, 1)


def test_filtered_collection_get_uses_direct_lookup_and_source_filter_semantics():
    class DirectProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"direct_filing_lookup"}

        def __init__(self):
            self.direct_calls = 0

        def get_filing(self, entity, filing_id):
            self.direct_calls += 1
            filing = next(super().iter_filings(entity))
            filing.filing_id = filing_id
            filing.provider_metadata = {"source_file_date": "2024-02-02"}
            return filing

        def filing_date_for_filter(self, filing):
            return date.fromisoformat(filing.provider_metadata["source_file_date"])

        def iter_filings(self, entity, **kwargs):
            raise AssertionError("direct lookup must not scan an unbounded listing")

    provider = DirectProvider()
    company = Company("FIX", market="US", provider=provider)
    collection = company.filings(
        form="annual", start="2024-02-02", end="2024-02-02",
        include_amendments=False,
    )
    assert collection.get("source-id", max_scan=1).filing_id == "source-id"
    assert provider.direct_calls == 1
    with pytest.raises(FilingNotFoundError, match="outside the selected filters"):
        company.filings(form="interim").get("source-id")
    with pytest.raises(FilingNotFoundError, match="outside the selected filters"):
        company.filings(end="2024-02-01").get("source-id")


def test_direct_collection_get_rejects_amendment_and_unknown_filter_fields():
    class DirectProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"direct_filing_lookup"}

        def get_filing(self, entity, filing_id):
            return next(super().iter_filings(entity))

    provider = DirectProvider()
    company = Company("FIX", market="US", provider=provider)
    filing = company.filings(include_amendments=False).get("f1")
    assert filing.amendment is None

    class ChangedProvider(DirectProvider):
        def __init__(self, **changes):
            self.changes = changes

        def get_filing(self, entity, filing_id):
            filing = super().get_filing(entity, filing_id)
            for key, value in self.changes.items():
                setattr(filing, key, value)
            return filing

    with pytest.raises(FilingNotFoundError, match="outside the selected filters"):
        Company("FIX", market="US", provider=ChangedProvider(amendment=True)).filings(
            include_amendments=False,
        ).get("f1")
    with pytest.raises(UnsupportedCapabilityError, match="filing type"):
        Company("FIX", market="US", provider=ChangedProvider(
            filing_type_raw=None, filing_type_normalized=None,
        )).filings(form="annual").get("f1")
    with pytest.raises(UnsupportedCapabilityError, match="filing date"):
        Company("FIX", market="US", provider=ChangedProvider(filing_date=None)).filings(
            start="2024-01-01",
        ).get("f1")


def test_direct_lookup_uses_provider_source_date_for_bounds():
    class SourceDateProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"direct_filing_lookup"}

        def get_filing(self, entity, filing_id):
            filing = next(super().iter_filings(entity))
            filing.provider_metadata = {"source_file_date": "2024-02-02"}
            return filing

        def filing_date_for_filter(self, filing):
            return date.fromisoformat(filing.provider_metadata["source_file_date"])

    company = Company("FIX", market="US", provider=SourceDateProvider())
    selected = company.get_filing("f1", start="2024-02-02", end="2024-02-02")
    assert selected.filing_date == date(2024, 2, 1)
    assert company.get_filing("f1", start=datetime(2024, 2, 2)).filing_id == "f1"
    with pytest.raises(FilingNotFoundError, match="outside the selected date range"):
        company.get_filing("f1", end="2024-02-01")


def test_calendar_date_filters_accept_datetime_inputs():
    company = Company("FIX", market="US", provider=FakeProvider())
    assert company.filings(start=datetime(2024, 2, 1)).latest().filing_id == "f1"
    assert company.filings(end=datetime(2024, 2, 1)).latest().filing_id == "f1"


def test_unfiltered_collection_direct_lookup_checks_issuer_and_source_id():
    class WrongProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"direct_filing_lookup"}

        def get_filing(self, entity, filing_id):
            filing = next(self.iter_filings(entity))
            filing.entity_id = "someone-else"
            return filing

    company = Company("FIX", market="US", provider=WrongProvider())
    with pytest.raises(FilingNotFoundError):
        company.filings().get("f1")


def test_company_can_enable_one_local_cache_without_changing_provider_defaults(tmp_path):
    from opencorpfilings.providers.companies_house import CompaniesHouseProvider

    provider = CompaniesHouseProvider()
    try:
        company = Company("00185647", market="UK", provider=provider, cache_dir=tmp_path)
        assert company.provider.transport.cache_dir == tmp_path
        assert company.provider.transport.min_interval == 0.51
    finally:
        provider.close()


def test_normalized_category_rejects_provider_specific_spelling():
    provenance = Provenance("fixture", "Fixture Commission", "US", "https://example.test/f", "f")
    with pytest.raises(ValueError, match="filing_type_normalized"):
        Filing("f", "e", "US", "fixture", "Fixture Commission", "https://example.test/f", provenance,
               filing_type_raw="10-K", filing_type_normalized="annual")


def test_document_text_and_filing_facts_parse_once_per_object():
    class CountingProvider(FakeProvider):
        def __init__(self):
            self.text_calls = 0
            self.fact_calls = 0

        def extract_text(self, document):
            self.text_calls += 1
            return "Fixture report"

        def raw_facts(self, filing):
            self.fact_calls += 1
            return [FilingFact(
                concept_raw="ex:Revenue", value="123", unit="USD",
                period_start=None, period_end=date(2024, 12, 31), context_id="c1",
                dimensions={}, taxonomy="https://example.test/taxonomy",
                source_location="https://example.test/annual.htm#fact-1",
                provenance=filing.provenance,
            )]

    provider = CountingProvider()
    filing = Company("FIX", market="US", provider=provider).filings().latest()
    document = filing.primary_document
    assert document.text() == "Fixture report"
    assert document.text() == "Fixture report"
    assert provider.text_calls == 1
    first = filing.facts
    first.clear()
    assert filing.facts[0].concept_raw == "ex:Revenue"
    assert filing.find_facts(concept_raw="ex:Revenue")[0].value == "123"
    assert provider.fact_calls == 1


def test_raw_fact_filters_are_exact_bounded_and_preserve_cached_occurrences():
    class FactProvider(FakeProvider):
        def __init__(self):
            self.calls = 0

        def raw_facts(self, filing):
            self.calls += 1
            return [FilingFact(
                concept_raw="ex:Revenue", value=str(number), unit=unit,
                period_start=date(2023 if number == 1 else 2024, 1, 1),
                period_end=date(2025 if number == 4 else 2024, 12, 31),
                context_id=context, dimensions={
                    "ex:Segment": segment, **({"ex:Region": "EU"} if number == 4 else {}),
                },
                taxonomy=f"urn:example:{2023 if number == 1 else 2024}",
                source_location=f"https://example.test/f#{number}",
                provenance=filing.provenance,
            ) for number, unit, context, segment in (
                (1, "USD", "c1", "Retail"), (2, "EUR", "c2", "Retail"),
                (3, "USD", "c3", "Retail"), (4, "USD", "c4", "Wholesale"),
            )]

    provider = FactProvider()
    filing = Company("FIX", market="US", provider=provider).filings().latest()
    with pytest.raises(ValueError, match="limit must be positive"):
        filing.find_facts(limit=0)
    assert provider.calls == 0
    selected = filing.find_facts(
        concept_raw="ex:Revenue", period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31), unit="USD", context_id="c3",
        dimensions={"ex:Segment": "Retail"}, taxonomy="urn:example:2024", limit=1,
    )
    assert [fact.value for fact in selected] == ["3"]
    assert [fact.value for fact in filing.find_facts(period_start=date(2023, 1, 1))] == ["1"]
    assert [fact.value for fact in filing.find_facts(period_end=date(2025, 12, 31))] == ["4"]
    assert [fact.value for fact in filing.find_facts(unit="EUR")] == ["2"]
    assert [fact.value for fact in filing.find_facts(taxonomy="urn:example:2023")] == ["1"]
    assert [fact.value for fact in filing.find_facts(dimensions={"ex:Segment": "Wholesale"})] == ["4"]
    assert [fact.value for fact in filing.find_facts(unit="USD", limit=1)] == ["1"]
    assert filing.find_facts(concept_raw="ex:Absent") == []
    assert [fact.value for fact in filing.find_facts(context_id="c3")] == ["3"]
    selected.clear()
    assert len(filing.facts) == 4
    assert provider.calls == 1


@pytest.mark.parametrize("field,value", [
    ("provider", "another_provider"), ("jurisdiction", "UK"),
])
def test_filing_rejects_raw_facts_from_another_source(field, value):
    class CorrectingProvider(FakeProvider):
        fact_calls = 0

        def raw_facts(self, filing):
            self.fact_calls += 1
            document = filing.primary_document
            provenance = Provenance(
                value if field == "provider" and self.fact_calls == 1 else self.name,
                self.regulator,
                value if field == "jurisdiction" and self.fact_calls == 1 else "US",
                document.source_url, document.document_id,
            )
            return [FilingFact(
                concept_raw="ex:Revenue", value="123", unit="USD",
                period_start=None, period_end=date(2024, 12, 31), context_id="c1",
                dimensions={}, taxonomy=None, source_location=document.source_url,
                provenance=provenance,
            )]

    provider = CorrectingProvider()
    filing = Company("FIX", market="US", provider=provider).filings().latest()
    with pytest.raises(ProviderError, match="raw fact.*does not match this filing's source"):
        _ = filing.facts
    assert filing.facts[0].concept_raw == "ex:Revenue"
    assert provider.fact_calls == 2


@pytest.mark.parametrize("changed_object", ["filing", "document"])
def test_cached_filing_facts_and_sections_reject_changed_source(changed_object):
    class ContentProvider(FakeProvider):
        def raw_facts(self, filing):
            return [FilingFact(
                concept_raw="ex:Revenue", value="123", unit="USD",
                period_start=None, period_end=date(2024, 12, 31), context_id="c1",
                dimensions={}, taxonomy=None, source_location=filing.primary_document.source_url,
                provenance=filing.primary_document.provenance,
            )]

        def extract_sections(self, filing):
            document = filing.primary_document
            return [FilingSection(
                item="1", title="Fixture report", text="Fixture report",
                document_id=document.document_id, source_url=document.source_url,
                start_line=1, end_line=1, provenance=document.provenance,
            )]

    filing = Company("FIX", market="US", provider=ContentProvider()).filings().latest()
    document = filing.primary_document
    assert filing.facts[0].value == "123"
    assert filing.sections()[0].item == "1"
    if changed_object == "filing":
        filing.source_url = "https://example.test/another-filing"
    else:
        document.source_url = "https://example.test/another-document"

    with pytest.raises(DownloadError, match="source URL changed"):
        _ = filing.facts
    with pytest.raises(DownloadError, match="source URL changed"):
        filing.sections()


def test_cached_document_save_preserves_existing_target_if_replace_fails(tmp_path, monkeypatch):
    filing = Company("FIX", market="US", provider=FakeProvider()).filings().latest()
    document = filing.primary_document
    assert document.download() == b"<h1>Fixture report</h1>"
    target = tmp_path / "annual.htm"
    target.write_bytes(b"old document")

    def fail_replace(*_args):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        document.download(target)
    assert target.read_bytes() == b"old document"
    assert list(tmp_path.iterdir()) == [target]


def test_cached_document_cannot_be_reused_under_another_source_url(tmp_path):
    filing = Company("FIX", market="US", provider=FakeProvider()).filings().latest()
    document = filing.primary_document
    assert document.download() == b"<h1>Fixture report</h1>"
    assert document.text() == "Fixture report"
    document.source_url = "https://example.test/another-original.htm"

    with pytest.raises(DownloadError, match="source URL changed"):
        document.download(tmp_path / "wrong-source.htm")
    with pytest.raises(DownloadError, match="source URL changed"):
        document.sha256()
    with pytest.raises(DownloadError, match="source URL changed"):
        document.text()
    assert not (tmp_path / "wrong-source.htm").exists()


def test_uncached_document_cannot_change_its_provenance_source_before_download(tmp_path):
    filing = Company("FIX", market="US", provider=FakeProvider()).filings().latest()
    document = filing.primary_document
    document.source_url = "https://example.test/another-original.htm"
    target = tmp_path / "wrong-source.htm"
    with pytest.raises(DownloadError, match="source URL changed"):
        document.download(target)
    assert not target.exists()


def test_streamed_document_cannot_be_copied_under_another_source_url(tmp_path):
    class StreamingProvider(FakeProvider):
        capabilities = FakeProvider.capabilities | {"streamed_download"}

        def save_document(self, document, path):
            path.write_bytes(b"<h1>Fixture report</h1>")
            return path

    filing = Company("FIX", market="US", provider=StreamingProvider()).filings().latest()
    document = filing.primary_document
    saved = tmp_path / "original.htm"
    assert document.download(saved) == saved
    document.source_url = "https://example.test/another-original.htm"

    with pytest.raises(DownloadError, match="source URL changed"):
        document.download(tmp_path / "copy.htm")
    assert saved.read_bytes() == b"<h1>Fixture report</h1>"
    assert not (tmp_path / "copy.htm").exists()
