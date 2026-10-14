"""Offline contract checks for Companies House API and public-page access."""

from __future__ import annotations

import base64
from io import BytesIO
import zipfile

import httpx
import pytest

from opencorpfilings import Company, DownloadError, EntityNotFoundError, FilingNotFoundError, ProviderError, UnsupportedCapabilityError
from opencorpfilings.errors import ParseError
from opencorpfilings.providers.companies_house import CompaniesHouseProvider
from opencorpfilings.transport import HttpTransport
from test_ixbrl import XHTML


def _transport(*, inline_xhtml: bytes | None = None) -> tuple[HttpTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/search/companies":
            return httpx.Response(200, json={"items": [{"title": "J SAINSBURY PLC", "company_number": "00185647"}]})
        if path == "/company/00185647":
            return httpx.Response(200, json={"company_number": "00185647", "company_name": "J SAINSBURY PLC"})
        if path == "/company/00185647/filing-history":
            if request.url.params["start_index"] == "0":
                return httpx.Response(200, json={
                    "items": [
                        {"transaction_id": "TX101", "type": "AA01", "category": "accounts", "date": "2026-08-01",
                         "description": "change-accounting-reference-date", "links": {}},
                        {"transaction_id": "TX100", "type": "AA", "category": "accounts", "date": "2026-07-21",
                         "description": "group-accounts", "links": {"self": "/company/00185647/filing-history/TX100", "document_metadata": "/document/DOC100"}},
                        {"transaction_id": "TX099", "type": "CS01", "category": "confirmation-statement", "date": "2026-07-01",
                         "description": "confirmation-statement", "links": {}},
                    ], "total_count": 4,
                })
            return httpx.Response(200, json={
                "items": [{"transaction_id": "TX050", "type": "AAMD", "category": "accounts", "date": "2025-07-15",
                           "description": "amended-accounts", "links": {"document_metadata": "/document/DOC050"}}],
                "total_count": 4,
            })
        if path == "/company/00185647/filing-history/TX100":
            return httpx.Response(200, json={
                "transaction_id": "TX100", "type": "AA", "category": "accounts",
                "date": "2026-07-21", "description": "group-accounts",
                "links": {"self": "/company/00185647/filing-history/TX100",
                          "document_metadata": "/document/DOC100"},
            })
        if path == "/company/00185647/filing-history/TX404":
            return httpx.Response(404)
        if path == "/document/DOC100":
            return httpx.Response(200, json={
                "id": "DOC100", "resources": {
                    "application/pdf": {"content_length": 300},
                    "application/xhtml+xml": {"content_length": 100},
                },
            })
        if path == "/document/DOC100/content":
            if request.headers.get("accept") == "application/xhtml+xml":
                return httpx.Response(200, content=inline_xhtml or b"<html><body><h1>Accounts</h1><p>Original source.</p></body></html>")
            if request.headers.get("accept") == "application/pdf":
                return httpx.Response(200, content=b"%PDF-1.7")
            return httpx.Response(406)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return HttpTransport(client=client), requests


def test_uk_company_to_individual_source_formats() -> None:
    transport, requests = _transport()
    company = Company("00185647", market="UK", provider=CompaniesHouseProvider(api_key="fixture-key", transport=transport))
    filing = company.filings(form="annual", start="2026-01-01").latest()
    assert company.entity.name == "J SAINSBURY PLC"
    assert filing.filing_id == "TX100"
    assert filing.filing_type_raw == "AA"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.filing_date.isoformat() == "2026-07-21"
    assert filing.source_url.endswith("/company/00185647/filing-history/TX100")
    assert len(filing.documents) == 2
    assert {document.media_type for document in filing.documents} == {"application/pdf", "application/xhtml+xml"}
    assert filing.primary_document.media_type == "application/xhtml+xml"
    assert filing.text() == "Accounts\nOriginal source."
    assert next(doc for doc in filing.documents if doc.media_type == "application/pdf").download() == b"%PDF-1.7"
    assert all(request.headers["authorization"] == "Basic " + base64.b64encode(b"fixture-key:").decode() for request in requests)
    with pytest.raises(UnsupportedCapabilityError):
        _ = filing.facts


def test_uk_name_resolution_and_page_filtering() -> None:
    transport, requests = _transport()
    company = Company("J Sainsbury PLC", market="UK", provider=CompaniesHouseProvider(api_key="fixture-key", transport=transport))
    assert [filing.filing_id for filing in company.filings(form="annual", include_amendments=True)] == ["TX100", "TX050"]
    assert [filing.filing_id for filing in company.filings(form="annual")] == ["TX100"]
    assert [filing.filing_id for filing in company.filings(form="annual", include_amendments=False)] == ["TX100"]
    assert any(request.url.path == "/search/companies" for request in requests)


def test_uk_api_direct_filing_lookup_skips_history_pages() -> None:
    transport, requests = _transport()
    provider = CompaniesHouseProvider(api_key="fixture-key", transport=transport)
    company = Company("00185647", market="UK", provider=provider)
    filing = company.get_filing("TX100")
    assert filing.filing_id == "TX100"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.filing_date.isoformat() == "2026-07-21"
    assert [request.url.path for request in requests] == [
        "/company/00185647", "/company/00185647/filing-history/TX100",
    ]
    assert [document.media_type for document in filing.documents] == [
        "application/pdf", "application/xhtml+xml",
    ]
    with pytest.raises(FilingNotFoundError):
        company.get_filing("TX404")


def test_uk_api_direct_filing_rejects_mismatched_source_record() -> None:
    transport, _ = _transport()
    provider = CompaniesHouseProvider(api_key="fixture-key", transport=transport)
    company = Company("00185647", market="UK", provider=provider)
    original = transport.client._transport.handler

    def mismatched(request: httpx.Request) -> httpx.Response:
        response = original(request)
        if request.url.path.endswith("/filing-history/TX100"):
            data = response.json()
            data["transaction_id"] = "TX999"
            return httpx.Response(200, json=data)
        return response

    transport.client._transport.handler = mismatched
    with pytest.raises(ParseError, match="transaction"):
        company.get_filing("TX100")


@pytest.mark.parametrize("bad_link", [
    "/company/99999999/filing-history/TX100",
    "https://example.org/company/00185647/filing-history/TX100",
])
def test_uk_api_direct_filing_rejects_cross_company_self_link(bad_link: str) -> None:
    transport, _ = _transport()
    company = Company("00185647", market="UK", provider=CompaniesHouseProvider(
        api_key="fixture-key", transport=transport,
    ))
    original = transport.client._transport.handler

    def mismatched(request: httpx.Request) -> httpx.Response:
        response = original(request)
        if request.url.path.endswith("/filing-history/TX100"):
            data = response.json()
            data["links"]["self"] = bad_link
            return httpx.Response(200, json=data)
        return response

    transport.client._transport.handler = mismatched
    with pytest.raises(ParseError, match="company or transaction link"):
        company.get_filing("TX100")


def test_uk_inline_xbrl_facts_keep_source_attributes() -> None:
    transport, _ = _transport(inline_xhtml=XHTML)
    company = Company("00185647", market="UK", provider=CompaniesHouseProvider(api_key="fixture-key", transport=transport))
    filing = company.filings(form="annual").latest()
    facts = filing.facts
    assert len(facts) == 3
    assert facts[0].concept_raw == "ex:Assets"
    assert facts[0].value == "1,234"
    assert facts[0].provider_metadata["attributes"]["scale"] == "3"
    assert facts[0].provenance.source_url == filing.primary_document.source_url


def test_uk_document_saves_selected_representation_with_api_headers(tmp_path) -> None:
    transport, requests = _transport()
    filing = Company("00185647", market="UK", provider=CompaniesHouseProvider(
        api_key="fixture-key", transport=transport,
    )).filings(form="annual").latest()
    pdf = next(doc for doc in filing.documents if doc.media_type == "application/pdf")
    target = tmp_path / "accounts.pdf"
    assert pdf.download(target) == target
    assert target.read_bytes() == b"%PDF-1.7"
    assert pdf._cached_bytes is None
    assert requests[-1].headers["accept"] == "application/pdf"
    assert "authorization" in requests[-1].headers


def test_uk_pdf_rejects_html_error_body_with_http_200(tmp_path) -> None:
    transport, _ = _transport()
    original = transport.client._transport.handler

    def bad_pdf(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/document/DOC100/content":
            return httpx.Response(200, content=b"<html>Document unavailable</html>")
        return original(request)

    transport.client._transport.handler = bad_pdf
    filing = Company("00185647", market="UK", provider=CompaniesHouseProvider(
        api_key="fixture-key", transport=transport,
    )).filings(form="annual").latest()
    pdf = filing.select_document(media_type="application/pdf")
    with pytest.raises(DownloadError, match="application/pdf"):
        pdf.download()
    target = tmp_path / "accounts.pdf"
    target.write_bytes(b"existing")
    with pytest.raises(ProviderError, match="unexpected document format"):
        pdf.download(target)
    assert target.read_bytes() == b"existing"


def test_uk_reference_date_change_remains_visible_but_is_not_annual() -> None:
    transport, _ = _transport()
    company = Company("00185647", market="UK", provider=CompaniesHouseProvider(api_key="fixture-key", transport=transport))
    filing = company.filings(form="AA01").latest()
    assert filing.filing_id == "TX101"
    assert filing.filing_type_raw == "AA01"
    assert filing.filing_type_normalized == "OTHER"
    assert filing.raw["description"] == "change-accounting-reference-date"
    assert company.filings(form="annual").latest().filing_id == "TX100"


def test_uk_unknown_name_is_explicit() -> None:
    transport, _ = _transport()
    company = Company("Missing plc", market="UK", provider=CompaniesHouseProvider(api_key="fixture-key", transport=transport))
    with pytest.raises(EntityNotFoundError, match="exact match"):
        _ = company.entity


def _public_transport() -> tuple[HttpTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("report/reports/report.xhtml", XHTML)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/search":
            return httpx.Response(200, text='<a href="/company/00185647">J SAINSBURY PLC</a>')
        if path == "/company/00185647":
            return httpx.Response(200, text='<h1 class="heading-xlarge">J SAINSBURY PLC</h1>')
        if path == "/company/00185647/filing-history":
            if request.url.params.get("page") == "2":
                return httpx.Response(200, text='''
                    <table id="fhTable"><tr><th>Date</th></tr><tr>
                    <td>21 Jul 2026</td><td>AA</td><td>Group accounts</td><td>
                    <a href="/company/00185647/filing-history/TX100/document?format=zip&amp;download=1">Download ZIP</a>
                    </td></tr></table>
                ''')
            return httpx.Response(200, text='''
                <table id="fhTable"><tr><th>Date</th></tr><tr>
                <td>01 Aug 2026</td><td>AA01</td><td>Reference date change</td><td>
                <a href="/company/00185647/filing-history/TX101/document?format=pdf&amp;download=0">View PDF</a>
                </td></tr></table>
                <a href="/company/00185647/filing-history?page=2">Next page</a>
            ''')
        if path == "/company/00185647/filing-history/TX100/document":
            return httpx.Response(200, content=archive_bytes.getvalue())
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return HttpTransport(client=client), requests


def test_uk_public_pages_need_no_api_key_for_common_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    transport, requests = _public_transport()
    company = Company("J Sainsbury PLC", market="UK", provider=CompaniesHouseProvider(transport=transport))
    filing = company.filings(form="annual", start="2026-01-01", limit=1).latest()
    assert company.entity.entity_id == "00185647"
    assert filing.filing_id == "TX100"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.filing_date.isoformat() == "2026-07-21"
    assert filing.provenance.source_id == "TX100"
    assert filing.raw["source"] == "public_website"
    assert filing.primary_document.media_type == "application/zip"
    assert len(filing.primary_document.members) == 1
    assert "1,234" in filing.text()
    assert len(filing.facts) == 3
    assert filing.facts[0].source_location.startswith(filing.primary_document.source_url + "::")
    assert all("authorization" not in request.headers for request in requests)
    assert any(request.url.path == "/search" and request.url.params["q"] == "J Sainsbury PLC" for request in requests)


def test_uk_saved_accounts_zip_facts_do_not_buffer_report_member(tmp_path, monkeypatch) -> None:
    from opencorpfilings import models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    transport, _ = _public_transport()
    filing = Company("00185647", market="UK", provider=CompaniesHouseProvider(
        transport=transport,
    )).filings(form="annual", limit=1).latest()
    package = filing.primary_document
    package.download(tmp_path / "accounts.zip")
    member = package.members[0]

    assert len(filing.facts) == 3
    assert package._cached_bytes is None
    assert member._cached_bytes is None


def test_uk_public_search_keeps_matches_at_page_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params.get("page", "1"))
        result = '<a href="/company/07524813">ROLLS-ROYCE HOLDINGS PLC</a>' if page == 1 else ""
        return httpx.Response(200, text=(
            result + f'<a href="/search?q=ROLLS-ROYCE+HOLDINGS+PLC&amp;page={page + 1}">Next page</a>'
        ))

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = CompaniesHouseProvider(transport=transport)
    matches = provider.search_entities("ROLLS-ROYCE HOLDINGS PLC", limit=3)
    assert [(match.entity_id, match.name) for match in matches] == [
        ("07524813", "ROLLS-ROYCE HOLDINGS PLC")
    ]
    assert len(requests) == 20


def test_uk_public_zip_rejects_html_error_body_with_http_200(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    transport, _ = _public_transport()
    original = transport.client._transport.handler

    def bad_zip(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/TX100/document"):
            return httpx.Response(200, content=b"<html>Document unavailable</html>")
        return original(request)

    transport.client._transport.handler = bad_zip
    filing = Company("00185647", market="UK", provider=CompaniesHouseProvider(
        transport=transport,
    )).filings(form="annual").latest()
    with pytest.raises(DownloadError, match="application/zip"):
        filing.download()
    target = tmp_path / "accounts.zip"
    target.write_bytes(b"existing")
    with pytest.raises(ProviderError, match="unexpected document format"):
        filing.download(target)
    assert target.read_bytes() == b"existing"


def test_uk_keyless_get_filing_uses_bounded_history_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    transport, requests = _public_transport()
    company = Company("00185647", market="UK", provider=CompaniesHouseProvider(transport=transport))
    assert company.get_filing("TX100").filing_id == "TX100"
    assert not company.provider.supports("direct_filing_lookup")
    assert sum(request.url.path == "/company/00185647/filing-history" for request in requests) == 2


def test_uk_api_history_stops_at_start_and_asks_for_the_accounts_category() -> None:
    # The history is newest first: TX099 (2026-07-01) predates start, so the
    # 2025 page is never requested.
    transport, requests = _transport()
    company = Company("00185647", market="UK", provider=CompaniesHouseProvider(api_key="fixture-key", transport=transport))
    assert [filing.filing_id for filing in company.filings(form="annual", start="2026-07-10")] == ["TX100"]
    history = [request for request in requests if request.url.path == "/company/00185647/filing-history"]
    assert [request.url.params["start_index"] for request in history] == ["0"]
    assert history[0].url.params["category"] == "accounts"


def test_uk_api_history_sends_no_category_for_a_form_spanning_categories() -> None:
    transport, requests = _transport()
    company = Company("00185647", market="UK", provider=CompaniesHouseProvider(api_key="fixture-key", transport=transport))
    assert company.filings(form="CS01").latest().filing_id == "TX099"
    assert all("category" not in request.url.params for request in requests)


def test_uk_public_history_stops_at_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    transport, requests = _public_transport()
    company = Company("00185647", market="UK", provider=CompaniesHouseProvider(transport=transport))
    assert list(company.filings(form="annual", start="2026-08-02")) == []
    assert sum(request.url.path == "/company/00185647/filing-history" for request in requests) == 1


@pytest.mark.parametrize("api_key", [None, "fixture-key"])
def test_uk_short_numeric_company_number_is_zero_padded(api_key, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCORPFILINGS_COMPANIES_HOUSE_API_KEY", raising=False)
    transport, requests = _transport() if api_key else _public_transport()
    company = Company("185647", market="UK", provider=CompaniesHouseProvider(api_key=api_key, transport=transport))
    assert company.entity.entity_id == "00185647"
    assert not any("search" in request.url.path for request in requests)
