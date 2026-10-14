"""Printing and exporting public objects must stay offline and keep source values as filed."""

from datetime import date
import json

import pytest

from opencorpfilings import Company, Filing, FilingFact, Provenance, UnsupportedCapabilityError

from test_core import FakeProvider


class CountingProvider(FakeProvider):
    def __init__(self):
        self.calls = 0

    def resolve_entity(self, identifier):
        self.calls += 1
        return super().resolve_entity(identifier)

    def iter_filings(self, *args, **kwargs):
        self.calls += 1
        yield from super().iter_filings(*args, **kwargs)

    def list_documents(self, filing):
        self.calls += 1
        return super().list_documents(filing)


def _fact(**overrides):
    values = dict(
        concept_raw="ifrs-full:Revenue", value="1,234", unit="iso4217:EUR",
        period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), context_id="c1",
        dimensions={"ifrs-full:SegmentsAxis": "Retail"}, taxonomy="ifrs-full",
        source_location="report.xhtml#f1",
        provenance=Provenance("fixture", "Fixture Commission", "US", "https://example.test/report.xhtml", "f1"),
    )
    values.update(overrides)
    return FilingFact(**values)


def test_reprs_are_one_line_and_hide_raw_source_records():
    provider = FakeProvider()
    company = Company("FIX", market="US", provider=provider)
    filing = company.filings().latest()
    filing.provider_metadata = {"huge_raw_record": "x" * 5000}
    document = filing.primary_document
    for obj in (company, company.entity, filing, document, _fact()):
        text = repr(obj)
        assert "\n" not in text and "huge_raw_record" not in text and len(text) < 300
    assert repr(filing) == "<Filing f1 10-K ANNUAL filed=2024-02-01 US/fixture>"
    assert repr(document) == "<FilingDocument annual.htm text/html primary>"
    assert repr(_fact()) == "<FilingFact ifrs-full:Revenue='1,234' iso4217:EUR 2025-01-01..2025-12-31 dims=1>"


def test_printing_never_contacts_the_source():
    provider = CountingProvider()
    company = Company("FIX", market="US", provider=provider)
    assert repr(company) == "<Company FIX US/fixture>"
    assert provider.calls == 0
    collection = company.filings(form="annual", start="2024-01-01")
    filing = collection.latest()
    calls = provider.calls
    for obj in (collection, filing):
        repr(obj)
        obj._repr_html_()
    assert provider.calls == calls
    assert repr(collection) == "<FilingCollection Fixture Inc US/fixture form=annual start=2024-01-01 order=filing_date>"


def test_notebook_html_escapes_source_values_and_links_the_source():
    filing = Company("FIX", market="US", provider=FakeProvider()).filings().latest()
    filing.title = "<script>alert(1)</script>"
    html = filing._repr_html_()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert '<a href="https://example.test/filing"' in html
    assert "10-K" in html


def test_filing_to_dict_is_json_safe_and_keeps_raw_values():
    filing = Company("FIX", market="US", provider=FakeProvider()).filings().latest()
    filing.provider_metadata = {"accepted": date(2024, 2, 1), "items": ("1", "7")}
    record = filing.to_dict()
    assert json.loads(json.dumps(record)) == record
    assert record["filing_date"] == "2024-02-01"
    assert record["filing_type_raw"] == "10-K"
    assert record["source_url"] == "https://example.test/filing"
    assert record["provenance_source_id"] == "f1"
    assert record["provider_metadata"] == {"accepted": "2024-02-01", "items": ["1", "7"]}


def test_fact_and_document_records_keep_filed_strings():
    record = _fact().to_dict()
    assert json.loads(json.dumps(record)) == record
    assert record["value"] == "1,234"
    assert record["dimensions"] == {"ifrs-full:SegmentsAxis": "Retail"}
    assert record["source_url"] == "https://example.test/report.xhtml"
    document = Company("FIX", market="US", provider=FakeProvider()).filings().latest().primary_document
    assert document.to_dict()["filename"] == "annual.htm"
    assert document.to_dict()["is_primary"] is True


def test_collection_to_pandas_is_bounded_and_carries_order_basis():
    pd = pytest.importorskip("pandas")
    provider = CountingProvider()
    collection = Company("FIX", market="US", provider=provider).filings()
    with pytest.raises(TypeError):
        collection.to_pandas()
    frame = collection.to_pandas(5)
    assert isinstance(frame, pd.DataFrame)
    assert list(frame["filing_id"]) == ["f1"]
    assert frame.attrs["order_basis"] == "filing_date"


def test_facts_to_pandas_keeps_values_as_strings():
    pytest.importorskip("pandas")

    class FactsProvider(FakeProvider):
        def raw_facts(self, filing):
            return [_fact(), _fact(value="(5)", dimensions={})]

    filing = Company("FIX", market="US", provider=FactsProvider()).filings().latest()
    frame = filing.facts_to_pandas()
    assert list(frame["value"]) == ["1,234", "(5)"]
    assert frame["value"].dtype == object


def test_pandas_helpers_explain_the_optional_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_pandas(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("no pandas")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pandas)
    filing = Company("FIX", market="US", provider=FakeProvider()).filings().latest()
    with pytest.raises(UnsupportedCapabilityError, match="'pandas' extra"):
        Filing.facts_to_pandas(filing)
