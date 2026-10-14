"""A category request returns the original report, not a later amendment, unless asked."""

from datetime import date

import pytest

from opencorpfilings import Company, Entity, Filing, FilingProvider, Provenance
from opencorpfilings.providers.sec import _form_matches


class AmendingProvider(FilingProvider):
    """Source order: a Part III 10-K/A filed after its 10-K, as TSLA did on 2026-04-30."""

    name = "fixture"
    market = "US"
    regulator = "Fixture Commission"
    capabilities = frozenset({"entity_lookup", "filing_discovery"})
    identifies_amendments = True

    def __init__(self):
        self.requests = []

    def resolve_entity(self, identifier):
        return Entity(identifier, "Fixture Inc", "US", self.name, "https://example.test/company")

    def iter_filings(self, entity, *, form=None, start=None, end=None, include_amendments=True, limit=None):
        self.requests.append(include_amendments)
        rows = [("a2", "10-K/A", True, date(2026, 4, 30)), ("o1", "10-K", False, date(2026, 1, 29))]
        for filing_id, raw, amended, filed in rows:
            if amended and not include_amendments:
                continue
            url = f"https://example.test/{filing_id}"
            yield Filing(filing_id, entity.entity_id, "US", self.name, self.regulator, url,
                         Provenance(self.name, self.regulator, "US", url, filing_id),
                         filing_type_raw=raw, filing_type_normalized="ANNUAL", filing_date=filed,
                         amendment=amended)

    def list_documents(self, filing):
        return []

    def download_document(self, document):
        return b""


class OpaqueProvider(AmendingProvider):
    """A source that cannot tell amendments apart rejects an explicit exclusion."""

    identifies_amendments = False

    def iter_filings(self, entity, *, include_amendments=True, **kwargs):
        if not include_amendments:
            raise AssertionError("must not ask an opaque source to exclude amendments")
        yield from super().iter_filings(entity, include_amendments=True, **kwargs)


def test_category_form_selects_the_original_by_default():
    company = Company("FIX", market="US", provider=AmendingProvider())
    assert company.filings(form="annual").latest().filing_id == "o1"
    assert company.filings(form="annual", include_amendments=True).latest().filing_id == "a2"


def test_unfiltered_listing_and_explicit_choice_keep_every_record():
    company = Company("FIX", market="US", provider=AmendingProvider())
    assert [f.filing_id for f in company.filings()] == ["a2", "o1"]
    assert [f.filing_id for f in company.filings(form="annual", include_amendments=True)] == ["a2", "o1"]


def test_source_that_cannot_identify_amendments_is_not_asked_to_exclude_them():
    company = Company("FIX", market="US", provider=OpaqueProvider())
    assert company.filings(form="annual").latest().filing_id == "a2"


def test_collection_shows_that_amendments_were_excluded():
    company = Company("FIX", market="US", provider=AmendingProvider())
    assert "include_amendments=False" in repr(company.filings(form="annual"))


@pytest.mark.parametrize(("raw", "requested", "expected"), [
    ("10-K", "10-K", True),
    ("10-K/A", "10-K", False),
    ("10-K/A", "10-K/A", True),
    ("10-K/A", "annual", True),
])
def test_sec_exact_form_means_exactly_that_form(raw, requested, expected):
    assert _form_matches(raw, requested) is expected
