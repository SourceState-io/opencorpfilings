"""National Nasdaq report categories merge without hiding their raw meaning."""

import json

import pytest

from opencorpfilings import Company
from opencorpfilings.providers.finland_oam import FinlandOAMProvider


class InterimTransport:
    def __init__(self, market: str, name: str, issuer_id: str, categories: list[tuple[str, str, str]]) -> None:
        self.market, self.name, self.issuer_id = market, name, issuer_id
        self.categories = categories
        self.posts: list[dict] = []

    def get(self, url: str, **kwargs: object) -> bytes:
        assert url == f"https://oam.{self.market.lower()}/"
        options = json.dumps([{"value": self.issuer_id, "label": self.name}])
        return (f"<input name='_csrf' value='token'><nef-form-select name='company' "
                f"options='{options}'></nef-form-select>").encode()

    def post_form(self, url: str, *, data: dict) -> bytes:
        assert url == f"https://oam.{self.market.lower()}/"
        assert data["company"] == self.issuer_id
        self.posts.append(data)
        if not data["category"] and data["pageSize"] == "1":
            options = json.dumps([{"value": id_, "label": label} for id_, label, _ in self.categories])
            return f"<nef-form-select name='category' options='{options}'></nef-form-select>".encode()
        id_ = data["category"] or self.categories[0][0]
        label, timestamp = next((label, timestamp) for value, label, timestamp in self.categories if value == id_)
        return (f"<nef-table><nef-table-row class='message-row'>"
                f"<nef-table-cell>{timestamp}</nef-table-cell>"
                f"<nef-table-cell>{self.name}</nef-table-cell>"
                f"<nef-table-cell><nef-link href='/view/{id_}?lang={self.market.lower()}'>"
                f"Source report</nef-link></nef-table-cell>"
                f"<nef-table-cell>{label}</nef-table-cell>"
                f"</nef-table-row></nef-table>").encode()


@pytest.mark.parametrize("market,name,issuer_id,provider_type,categories,latest_id", [
    ("FI", "KONE Oyj", "552", FinlandOAMProvider,
     [("78", "Half year financial report", "2026-07-22 08:30:18 EEST"),
      ("153", "Interim report (Q1, Q3 and Q4) and Financial Statement Release", "2026-04-29 08:30:19 EEST")], "78"),
])
def test_interim_categories_merge_in_publication_order_and_stop_after_first_page(
    market, name, issuer_id, provider_type, categories, latest_id,
):
    transport = InterimTransport(market, name, issuer_id, categories)
    company = Company(issuer_id, market=market, provider=provider_type(transport=transport))
    filing = company.filings(form="interim").latest()
    assert filing.filing_id == latest_id
    assert filing.filing_type_normalized == "INTERIM"
    assert filing.filing_type_raw == next(label for id_, label, _ in categories if id_ == latest_id)
    assert filing.provider_metadata["category_id"] == latest_id
    assert [post["category"] for post in transport.posts if post["category"]] == [id_ for id_, _, _ in categories]
    assert all(post["page"] == "1" for post in transport.posts)


def test_latest_interim_can_come_from_second_source_category():
    transport = InterimTransport("FI", "KONE Oyj", "552", [
        ("78", "Half year financial report", "2026-07-22 08:30:18 EEST"),
        ("153", "Interim report (Q1, Q3 and Q4) and Financial Statement Release",
         "2026-10-20 08:30:19 EEST"),
    ])
    company = Company("552", market="FI", provider=FinlandOAMProvider(transport=transport))
    filings = company.filings(form="interim").head(2)
    assert [filing.filing_id for filing in filings] == ["153", "78"]


def test_unfiltered_nasdaq_listing_preserves_interim_category():
    transport = InterimTransport("FI", "KONE Oyj", "552", [
        ("78", "Half year financial report", "2026-07-22 08:30:18 EEST")])
    company = Company("552", market="FI", provider=FinlandOAMProvider(transport=transport))
    filing = company.filings().latest()
    assert filing.filing_type_raw == "Half year financial report"
    assert filing.filing_type_normalized == "INTERIM"
