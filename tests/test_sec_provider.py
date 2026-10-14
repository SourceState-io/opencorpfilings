"""Offline contract checks for the direct EDGAR adapter."""

from __future__ import annotations

import os
import httpx
import pytest

from opencorpfilings import AmbiguousEntityError, Company, DownloadError, EntityNotFoundError, FilingDocument, FilingNotFoundError, FilingSectionReference, ParseError, ProviderError, Provenance, UnsupportedCapabilityError, search_companies
from opencorpfilings.providers.sec import SECProvider, _media_type
from opencorpfilings.html_text import html_to_text
from opencorpfilings.transport import HttpTransport
from test_ixbrl import XHTML


_INSTANCE = b'''<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <context id="FY24"><entity><identifier scheme="http://www.sec.gov/CIK">0000320193</identifier>
    <segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:ConsolidatedEntitiesMember</xbrldi:explicitMember></segment>
  </entity><period><startDate>2023-10-01</startDate><endDate>2024-09-28</endDate></period></context>
  <unit id="usd"><measure>iso4217:USD</measure></unit>
  <us-gaap:Revenues contextRef="FY24" unitRef="usd" decimals="0">100</us-gaap:Revenues>
</xbrl>'''

_DIRECT_ACCESSION = "0000320193-22-000001"
_AGENT_ACCESSION = "0001193125-26-323660"
_RECENT_INDEX = b'''<table class="tableFile"><tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>Annual report</td><td><a href="aapl-20240928.htm">aapl-20240928.htm</a></td><td>10-K</td><td>3</td></tr>
<tr><td>2</td><td>Subsidiaries of Apple Inc.</td><td><a href="aapl-ex21.htm">aapl-ex21.htm</a></td><td>EX-21.1</td><td>4</td></tr></table>'''
_DIRECT_INDEX = b'''<div id="formHeader">Form 10-K: SEC Accession No. 0000320193-22-000001</div>
<div id="formName"><strong>Form 10-K</strong> - Annual report</div>
<div class="companyInfo"><span class="companyName">Apple Inc. (Filer)
<acronym title="Central Index Key">CIK</acronym>:
<a href="/cgi-bin/browse-edgar?CIK=0000320193&action=getcompany">0000320193</a></span></div>
<div class="formGrouping"><div class="infoHead">Filing Date</div><div class="info">2022-10-28</div>
<div class="infoHead">Accepted</div><div class="info">2022-10-28 06:00:00</div></div>
<div class="formGrouping"><div class="infoHead">Period of Report</div><div class="info">2022-09-24</div></div>
<table class="tableFile"><tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
<tr><td>1</td><td>Annual report</td><td><a href="/Archives/edgar/data/320193/000032019322000001/annual.htm">annual.htm</a></td><td>10-K</td></tr>
<tr><td>2</td><td>Material agreement</td><td><a href="/Archives/edgar/data/320193/000032019322000001/ex-10.htm">ex-10.htm</a></td><td>EX-10.1</td></tr></table>'''


def _transport(*, instance: bool = False, inline_xhtml: bytes | None = None,
               quarterly_html: bytes | None = None) -> tuple[HttpTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    recent = {
        "accessionNumber": ["0000320193-24-000123", "0000320193-24-000099", "0000320193-23-000106"],
        "filingDate": ["2024-11-01", "2024-08-02", "2023-11-03"],
        "reportDate": ["2024-09-28", "2024-06-29", "2023-09-30"],
        "form": ["10-K", "10-Q", "10-K/A"],
        "primaryDocument": ["aapl-20240928.htm", "aapl-20240629.htm", "aapl-20230930.htm"],
        "acceptanceDateTime": ["2024-11-01T06:01:36.000Z", None, None],
    }
    routes = {
        "/files/company_tickers_exchange.json": {"fields": ["cik", "name", "ticker", "exchange"], "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]]},
        "/submissions/CIK0000320193.json": {
            "cik": "0000320193", "name": "Apple Inc.", "tickers": ["AAPL"], "exchanges": ["Nasdaq"],
            "filings": {"recent": recent, "files": []},
        },
        "/Archives/edgar/data/320193/000032019324000123/index.json": {
            "directory": {"item": [
                {"name": "aapl-20240928.htm", "type": "text/html", "size": "3"},
                {"name": "aapl-ex21.htm", "type": "text/html", "size": "4"},
                {"name": "aapl-20240928.xsd", "type": "application/xml", "size": "2"},
            ] + ([{"name": "aapl-20240928_htm.xml", "type": "application/xml", "size": "4"}] if instance else [])}
        },
        "/Archives/edgar/data/320193/000032019322000001/index.json": {
            "directory": {"item": [{"name": "annual.htm", "type": "text/html", "size": "13"},
                                   {"name": "ex-10.htm", "type": "text/html", "size": "14"}]}
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/aapl-20240928.htm"):
            return httpx.Response(200, content=inline_xhtml or b"<html><body><h1>Annual report</h1><p>Revenue grew.</p><script>skip</script></body></html>")
        if request.url.path.endswith("/aapl-20240629.htm"):
            return httpx.Response(200, content=quarterly_html or b"<html><body><p>Quarterly report</p></body></html>")
        if request.url.path.endswith("/aapl-ex21.htm"):
            return httpx.Response(200, content=b"<p>Apple subsidiaries</p>")
        if request.url.path.endswith("/aapl-20240928.xsd"):
            return httpx.Response(200, content=b"<schema/>")
        if request.url.path.endswith("/aapl-20240928_htm.xml"):
            return httpx.Response(200, content=_INSTANCE)
        if request.url.path.endswith(f"/{_DIRECT_ACCESSION}-index.htm"):
            return httpx.Response(200, content=_DIRECT_INDEX)
        if request.url.path.endswith(f"/{_AGENT_ACCESSION}-index.htm"):
            return httpx.Response(200, content=_DIRECT_INDEX.replace(
                _DIRECT_ACCESSION.encode(), _AGENT_ACCESSION.encode()))
        if request.url.path.endswith("/0000320193-24-000123-index.htm"):
            return httpx.Response(200, content=_RECENT_INDEX)
        if request.url.path.endswith("/annual.htm"):
            return httpx.Response(200, content=b"<h1>Annual report</h1>")
        if request.url.path in routes:
            return httpx.Response(200, json=routes[request.url.path])
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpTransport(client=client, user_agent="Example Contact contact@example.com"), requests


def test_sec_search_result_can_list_filings_without_resolving_ticker_again() -> None:
    transport, requests = _transport()
    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=transport)
    selected = search_companies("AAPL", market="US", provider=provider)[0]
    with Company(selected, provider=provider) as company:
        filing = company.filings(form="annual", include_amendments=False).latest()
        assert filing.filing_id == "0000320193-24-000123"
        assert company.filings(form="annual", include_amendments=False).latest().filing_id == filing.filing_id
        assert company.entity is selected
        assert selected.provenance.source_url.endswith("company_tickers_exchange.json")
    paths = [request.url.path for request in requests]
    assert paths.count("/files/company_tickers_exchange.json") == 1
    assert paths.count("/submissions/CIK0000320193.json") == 1
    assert "/include/ticker.txt" not in paths


def test_sec_company_to_original_document_and_text() -> None:
    transport, requests = _transport()
    company = Company("AAPL", market="US", provider=SECProvider(user_agent="Example Contact contact@example.com", transport=transport))
    filing = company.filings(form="annual", start="2024-01-01").latest()
    assert company.entity.entity_id == "0000320193"
    assert filing.filing_type_raw == "10-K"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.period_end.isoformat() == "2024-09-28"
    assert filing.source_url.endswith("0000320193-24-000123-index.htm")
    assert filing.primary_document.filename == "aapl-20240928.htm"
    assert len(filing.documents) == 3
    assert filing.download().startswith(b"<html>")
    assert filing.text() == "Annual report\nRevenue grew."
    assert filing.primary_document.provenance.source_url == filing.primary_document.source_url
    assert all("contact@example.com" in request.headers["user-agent"] for request in requests)
    with pytest.raises(UnsupportedCapabilityError):
        _ = filing.facts


def test_sec_saved_html_text_does_not_buffer_original(tmp_path, monkeypatch) -> None:
    transport, _ = _transport()
    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=transport)
    filing = Company("AAPL", market="US", provider=provider).filings(form="annual").latest()
    document = filing.primary_document
    saved = tmp_path / "annual.htm"
    document.download(saved)

    def fail_buffer(_document):
        raise AssertionError("saved HTML text must not buffer the original")

    monkeypatch.setattr(provider, "download_document", fail_buffer)
    assert document.text() == "Annual report\nRevenue grew."
    assert document.text() == html_to_text(saved.read_bytes())
    assert document._cached_bytes is None
    assert saved.read_bytes().startswith(b"<html>")


def test_sec_10k_sections_follow_contents_titles_and_keep_source() -> None:
    toc = "".join(
        f"<p>Item {code}.</p><p>{title}</p>"
        for code, title in (("1", "Business"), ("1A", "Risk Factors"),
                            ("1B", "Unresolved Staff Comments"), ("2", "Properties"),
                            ("3", "Legal Proceedings"), ("15", "Exhibits"))
    )
    body = """<p>Item 1. Business</p><p>Products and services.</p>
<p>Item 1</p><p>Running page header.</p>
<p>Item 1A. Risk Factors</p><p>Competition risk.</p>
<p>Item 1B.</p><p>Unresolved Staff Comments</p><p>None.</p>
<p>Item 2.</p><p>Properties</p><p>Headquarters.</p>
<p>Item 3. Legal Proceedings</p><p>No material proceedings.</p>
<p>Item 15. Exhibits</p><p>Filing exhibits.</p>
<p>SIGNATURES</p><p>Director signed.</p>"""
    transport, _ = _transport(inline_xhtml=(toc + body).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    sections = filing.sections()
    assert [section.item for section in sections] == ["1", "1A", "1B", "2", "3", "15"]
    assert sections[0].title == "Business"
    assert "Products and services." in sections[0].text
    assert "Competition risk." not in sections[0].text
    assert "SIGNATURES" not in sections[-1].text
    assert sections[0].source_url == filing.primary_document.source_url
    assert sections[0].provenance == filing.primary_document.provenance
    assert sections[0].start_line < sections[0].end_line < sections[1].start_line


def test_sec_10k_contents_match_list_number_before_body_item() -> None:
    rows = (("1", "Business"), ("1A", "Risk Factors"), ("2", "Properties"),
            ("7", "Management Discussion"), ("8", "Financial Statements"), ("15", "Exhibits"))
    toc = "".join(f"<p>Item {code}.</p><p>{title}</p>" for code, title in rows)
    body = "".join(
        f"<p>{'1.' if code == '15' else ''}Item {code}. {title}</p><p>Source prose for {code}.</p>"
        for code, title in rows
    ) + "<p>SIGNATURES</p>"
    transport, _ = _transport(inline_xhtml=(toc + body).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    sections = filing.sections()
    assert [section.item for section in sections] == [code for code, _ in rows]
    assert sections[-1].text.startswith("1.Item 15. Exhibits\nSource prose for 15.")
    assert all(section.text == "\n".join(filing.text().splitlines()[section.start_line - 1:section.end_line])
               for section in sections)


def test_sec_10k_list_number_does_not_override_a_mismatched_contents_title() -> None:
    rows = (("1", "Business"), ("1A", "Risk Factors"), ("2", "Properties"),
            ("7", "Management Discussion"), ("8", "Financial Statements"), ("15", "Exhibits"))
    toc = "".join(f"<p>Item {code}.</p><p>{title}</p>" for code, title in rows)
    body = "".join(
        f"<p>{'1.' if code == '15' else ''}Item {code}. "
        f"{'Unrelated heading' if code == '15' else title}</p><p>Source prose.</p>"
        for code, title in rows
    )
    transport, _ = _transport(inline_xhtml=(toc + body).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
        filing.sections()


@pytest.mark.parametrize("pointer,kind,target", [
    ("The financial statements are included in this report beginning on page F-3.", "page", "F-3"),
    ("The financial statements are shown in Exhibit 13 and incorporated by reference.", "document", "EX-13"),
])
def test_sec_item8_exposes_source_reference_without_inventing_content(
    pointer: str, kind: str, target: str,
) -> None:
    rows = (("1", "Business"), ("1A", "Risk Factors"), ("2", "Properties"),
            ("7", "Management Discussion"), ("8", "Financial Statements"), ("15", "Exhibits"))
    toc = "".join(f"<p>Item {code}.</p><p>{title}</p>" for code, title in rows)
    body = "".join(
        f"<p>Item {code}. {title}</p><p>{pointer if code == '8' else 'Source prose.'}</p>"
        for code, title in rows
    )
    transport, _ = _transport(inline_xhtml=(toc + body).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    sections = filing.sections()
    item8 = next(section for section in sections if section.item == "8")
    assert item8.text.endswith(pointer)
    assert len(item8.references) == 1
    reference = item8.references[0]
    assert isinstance(reference, FilingSectionReference)
    assert (reference.kind, reference.target, reference.source_text) == (kind, target, pointer)
    assert reference.source_url == item8.source_url
    assert reference.source_line == item8.start_line + 1
    assert reference.provenance == item8.provenance
    assert all(not section.references for section in sections if section.item != "8")


def test_sec_10k_sections_follow_verified_numeric_contents_table() -> None:
    rows = (("1", "Business"), ("1A.", "Risk Factors"),
            ("1B.", "Unresolved Staff Comments"), ("2", "Properties"),
            ("3", "Legal Proceedings"), ("15", "Exhibits"))
    toc = "<table><tr><th>Item</th><th>Page</th></tr>" + "".join(
        f"<tr><td>{code}</td><td></td><td>{'<span>Pro</span><span>perties</span>' if code == '2' else title}</td><td>1</td></tr>"
        for code, title in rows
    ) + "</table>"
    body = "".join(f"<p>Item {code} {title}</p><p>Report content.</p>" for code, title in rows)
    transport, _ = _transport(inline_xhtml=(toc + body + "<p>SIGNATURES</p>").encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    assert [section.item for section in filing.sections()] == ["1", "1A", "1B", "2", "3", "15"]
    assert "SIGNATURES" not in filing.sections()[-1].text


@pytest.mark.parametrize("toc_title,body_title", [
    ("Exhibit and Financial Statement Schedules", "Exhibits and Financial Statement Schedules"),
    ("Exhibits, Financial Statement Schedules", "Exhibits and Financial Statement Schedules"),
    ("Disclosures Regarding Foreign Jurisdictions", "Disclosure Regarding Foreign Jurisdictions"),
])
def test_sec_10k_sections_accept_unique_minor_title_variants(toc_title: str, body_title: str) -> None:
    rows = (("1", "Business"), ("1A", "Risk Factors"), ("1B", "Unresolved Staff Comments"),
            ("2", "Properties"), ("3", "Legal Proceedings"), ("15", toc_title))
    toc = "".join(f"<p>Item {item}.</p><p>{title}</p>" for item, title in rows)
    body = "".join(f"<p>Item {item}. {body_title if item == '15' else title}</p><p>Body.</p>"
                   for item, title in rows)
    transport, _ = _transport(inline_xhtml=(toc + body).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    sections = filing.sections()
    assert [section.item for section in sections] == [item for item, _ in rows]
    assert sections[-1].title == toc_title
    assert body_title in sections[-1].text


def test_sec_10k_sections_accept_em_dash_headings_with_source_title_prefix() -> None:
    rows = (("1", "Business"), ("1A", "Risk Factors"),
            ("1B", "Unresolved Staff Comments"), ("2", "Properties"),
            ("7", "Management's Discussion and Analysis"), ("15", "Exhibits"))
    toc = "".join(f"<p>Item {item}.</p><p>{title}</p>" for item, title in rows)
    body = "".join(
        f"<p>Item {item}—{title}{' (amounts in millions)' if item == '7' else ''}</p><p>Body.</p>"
        for item, title in rows
    )
    transport, _ = _transport(inline_xhtml=(toc + body + "<p>SIGNATURES</p>").encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    sections = filing.sections()
    assert [section.item for section in sections] == [item for item, _ in rows]
    assert sections[4].text.startswith("Item 7—Management's Discussion and Analysis (amounts in millions)")
    assert "SIGNATURES" not in sections[-1].text


def test_sec_10k_sections_use_source_body_when_contents_are_inline() -> None:
    codes = ("1", "1A", "1B", "1C", "2", "3", "4", "5", "7", "7A", "8", "9",
             "9A", "9B", "10", "11", "12", "13", "14", "15", "16")
    toc = "".join(f"<p>Item {code}. Topic {code}</p>" for code in codes)
    body = "".join(
        f"<p>Item {code}. Topic {code}</p><p>{'Source prose. ' * 35}{code}</p>"
        for code in codes
    )
    transport, _ = _transport(inline_xhtml=(toc + body + "<p>SIGNATURES</p>").encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    sections = filing.sections()
    assert [section.item for section in sections] == list(codes)
    assert sections[0].title == "Topic 1"
    assert sections[0].text.startswith("Item 1. Topic 1\nSource prose.")
    assert "Topic 1A" not in sections[0].text
    assert "SIGNATURES" not in sections[-1].text
    lines = filing.text().splitlines()
    assert all(section.text == "\n".join(lines[section.start_line - 1:section.end_line]) for section in sections)


@pytest.mark.parametrize("heading", [
    "ITEMS 10, 11, 12 and 13.",
    "ITEMS 10, 11, 12, and 13.",
])
def test_sec_10k_joint_item_heading_is_one_labeled_source_span(heading: str) -> None:
    codes = ("1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8",
             "9", "9A", "9B", "9C", "14", "15", "16")
    title = ("DIRECTORS, EXECUTIVE OFFICERS AND CORPORATE GOVERNANCE; EXECUTIVE COMPENSATION; "
             "SECURITY OWNERSHIP OF CERTAIN BENEFICIAL OWNERS AND MANAGEMENT; "
             "CERTAIN RELATIONSHIPS AND RELATED TRANSACTIONS")
    body = "".join(
        f"<p>Item {code}. Topic {code}</p><p>{'Source prose. ' * 35}{code}</p>"
        for code in codes[:16]
    )
    body += f"<p><strong>{heading} {title}</strong></p><p>Shared source prose.</p>"
    body += "".join(
        f"<p>Item {code}. Topic {code}</p><p>{'Source prose. ' * 35}{code}</p>"
        for code in codes[16:]
    ) + "<p>SIGNATURES</p>"
    transport, _ = _transport(inline_xhtml=body.encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    sections = filing.sections()
    shared = filing.section("11")
    assert [section.item for section in sections] == [*codes[:16], "10-13", *codes[16:]]
    assert shared is filing.section("10") is filing.section("12") is filing.section("13")
    assert shared.item == "10-13"
    assert shared.items == ("10", "11", "12", "13")
    assert shared.text.startswith(heading)
    assert shared.text.endswith("Shared source prose.")
    assert all(section.text == "\n".join(filing.text().splitlines()[section.start_line - 1:section.end_line])
               for section in sections)
    assert all(section.items == (section.item,) for section in sections if section is not shared)


@pytest.mark.parametrize("joint_heading", [
    "<strong>ITEMS 10, 12 and 13. SHARED GOVERNANCE INFORMATION</strong>",
    "ITEMS 10, 11, 12 and 13. SHARED GOVERNANCE INFORMATION",
])
def test_sec_10k_joint_heading_requires_consecutive_bold_source_items(joint_heading: str) -> None:
    codes = ("1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8",
             "9", "9A", "9B", "9C", "14", "15", "16")
    before = "".join(f"<p>Item {code}. Topic {code}</p><p>{'Source prose. ' * 35}</p>"
                     for code in codes[:16])
    after = "".join(f"<p>Item {code}. Topic {code}</p><p>{'Source prose. ' * 35}</p>"
                    for code in codes[16:])
    transport, _ = _transport(inline_xhtml=(before + f"<p>{joint_heading}</p><p>Shared prose.</p>" + after).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
        filing.sections()


def test_sec_10k_body_headings_in_table_cells_keep_text_line_positions() -> None:
    codes = ("1", "1A", "1B", "1C", "2", "3", "4", "5", "7", "7A", "8", "9",
             "9A", "9B", "10", "11", "12", "13", "14", "15", "16")
    toc = "".join(f"<p>Item {code}. Topic {code}</p>" for code in codes)
    body = "".join(
        f"<table><tr><td>Item {code}.</td><td>Topic {code}</td></tr></table>"
        f"<p>{'Source prose. ' * 35}{code}</p>"
        for code in codes
    )
    transport, _ = _transport(inline_xhtml=(toc + body + "<p>SIGNATURES</p>").encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    sections = filing.sections()
    assert [section.item for section in sections] == list(codes)
    assert sections[0].text.startswith("Item 1.\tTopic 1\nSource prose.")
    lines = filing.text().splitlines()
    assert all(section.text == "\n".join(lines[section.start_line - 1:section.end_line]) for section in sections)


def test_sec_10k_rejects_dense_page_reference_table_as_body() -> None:
    codes = ("1", "1A", "1B", "1C", "2", "3", "4", "5", "7", "7A", "8", "9",
             "9A", "9B", "10", "11", "12", "13", "14", "15", "16")
    index = "<table>" + "".join(
        f"<tr><td>Item {code}.</td><td>Topic {code}</td><td>{number}</td></tr>"
        for number, code in enumerate(codes, 1)
    ) + "</table>"
    transport, _ = _transport(inline_xhtml=("<p>Report narrative without Item headings.</p>" + index).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
        filing.sections()


def test_sec_10k_sections_reject_ambiguous_minor_title_variants() -> None:
    rows = (("1", "Business"), ("1A", "Risk Factors"), ("1B", "Unresolved Staff Comments"),
            ("2", "Properties"), ("3", "Legal Proceedings"),
            ("15", "Exhibit and Financial Statement Schedules"))
    toc = "".join(f"<p>Item {item}.</p><p>{title}</p>" for item, title in rows)
    body = "".join(f"<p>Item {item}. {title}</p><p>Body.</p>" for item, title in rows[:-1])
    body += ("<p>Item 15. Exhibits and Financial Statement Schedules</p><p>First.</p>"
             "<p>Item 15. Exhibit Financial Statement Schedules</p><p>Second.</p>")
    transport, _ = _transport(inline_xhtml=(toc + body).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
        filing.sections()


def test_sec_10k_numeric_contents_rejects_table_title_mismatch() -> None:
    html = """<table><tr><th>Item</th><th>Page</th></tr>
<tr><td>1</td><td></td><td>Business</td><td>1</td></tr>
<tr><td>1A.</td><td></td><td>Risk Factors</td><td>2</td></tr>
<tr><td>1B.</td><td></td><td>Comments</td><td>3</td></tr>
<tr><td>2</td><td></td><td>Properties</td><td>4</td></tr>
<tr><td>3</td><td></td><td>Proceedings</td><td>5</td></tr>
<tr><td>15</td><td></td><td>Exhibits</td><td>6</td></tr></table>
<p>Item 1. Business</p><p>Item 1A. Risk Factors</p>
<p>Item 1B. Comments</p><p>Item 2. Properties</p>
<p>Item 3. Proceedings</p><p>Item 15. Exhibits</p>""".replace(
        "<td>Exhibits</td>", "<td>Unrelated title</td>"
    )
    transport, _ = _transport(inline_xhtml=html.encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
        filing.sections()


def test_sec_sections_fail_closed_when_contents_do_not_match_body() -> None:
    toc = "".join(f"<p>Item {code}.</p><p>{title}</p>" for code, title in
                  (("1", "Business"), ("1A", "Risk Factors"),
                   ("1B", "Unresolved Staff Comments"), ("2", "Properties"),
                   ("3", "Legal Proceedings"), ("15", "Exhibits")))
    transport, _ = _transport(inline_xhtml=(toc + "<p>Item 1. Business</p>").encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
        filing.sections()


def test_sec_sections_reject_other_forms_before_document_download() -> None:
    transport, requests = _transport()
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="10-K/A").latest()

    with pytest.raises(UnsupportedCapabilityError, match="include_amendments=False"):
        filing.sections()
    with pytest.raises(UnsupportedCapabilityError, match="include_amendments=False"):
        filing.section_references("8")
    for amended_form in ("10-Q/A", "8-K/A"):
        filing.filing_type_raw = amended_form
        with pytest.raises(UnsupportedCapabilityError, match="include_amendments=False"):
            filing.sections()
    assert not any(request.url.path.endswith("aapl-20230930.htm") for request in requests)


def test_sec_sections_accept_source_punctuation_and_spacing_variants() -> None:
    html = """<p>Item 1.</p><p>Business</p>
<p>Item 1A.</p><p>Risk Factors</p>
<p>Item 1B.</p><p>Unresolved Staff Comments</p>
<p>Item 1C</p><p>Cybersecurity</p>
<p>Item 15.</p><p>Registrant�s Exhibits</p>
<p>ITEM 1.BUSINESS</p><p>Products.</p>
<p>ITEM 1A.RISK FACTORS</p><p>Risks.</p>
<p>ITEM 1B.UNRESOLVED STAFF COMMENTS</p><p>None.</p>
<p>ITEM 1C.CYBERSECURITY</p><p>Controls.</p>
<p>ITEM 15. REGISTRANT'S EXHIBITS</p><p>Exhibits.</p>"""
    transport, _ = _transport(inline_xhtml=html.encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()

    assert [section.item for section in filing.sections()] == ["1", "1A", "1B", "1C", "15"]


def test_sec_10q_sections_keep_part_and_verify_repeated_item_numbers() -> None:
    contents = """<p>Part I</p><p>Item 1.</p><p>Financial Statements</p>
<p>Item 2.</p><p>Management's Discussion</p>
<p>Item 3.</p><p>Market Risk</p><p>Item 4.</p><p>Controls</p>
<p>Part II</p><p>Item 1.</p><p>Legal Proceedings</p>
<p>Item 1A.</p><p>Risk Factors</p><p>Item 2.</p><p>Unregistered Sales</p>
<p>Item 5.</p><p>Other Information</p><p>Item 6.</p><p>Exhibits</p>"""
    body = """<p>PART I. FINANCIAL INFORMATION</p>
<p>ITEM 1. FINANCIAL STATEMENTS</p><p>Balance sheet.</p>
<p>ITEM 2.MANAGEMENT'S DISCUSSION</p><p>Operating results.</p>
<p>ITEM 3. MARKET RISK</p><p>Interest rates.</p>
<p>ITEM 4. CONTROLS</p><p>Effective.</p>
<p>PART II. OTHER INFORMATION</p>
<p>ITEM 1. LEGAL PROCEEDINGS</p><p>None.</p>
<p>ITEM 1A. RISK FACTORS</p><p>Competition.</p>
<p>ITEM 2. UNREGISTERED SALES</p><p>None.</p>
<p>ITEM 5. OTHER INFORMATION</p><p>None.</p>
<p>ITEM 6. EXHIBITS</p><p>Index.</p>
<p>SIGNATURE</p><p>Officer signed.</p>"""
    transport, _ = _transport(quarterly_html=(contents + body).encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="quarterly").latest()

    sections = filing.sections()
    assert [(section.part, section.item) for section in sections] == [
        ("I", "1"), ("I", "2"), ("I", "3"), ("I", "4"),
        ("II", "1"), ("II", "1A"), ("II", "2"), ("II", "5"), ("II", "6"),
    ]
    assert "Balance sheet." in sections[0].text
    assert "Legal Proceedings" not in sections[0].text
    assert "PART II" not in sections[3].text
    assert "SIGNATURE" not in sections[-1].text
    assert sections[4].source_url == filing.primary_document.source_url
    assert filing.section("Item 1", part="I") == sections[0]
    assert filing.section("1", part="II") == sections[4]
    assert filing.section("1A") == sections[5]
    with pytest.raises(ValueError, match="part"):
        filing.section("1")
    with pytest.raises(KeyError, match="Item 9"):
        filing.section("9")
    with pytest.raises(ValueError, match="Item"):
        filing.section("not an item")
    with pytest.raises(ValueError, match="part"):
        filing.section("1", part="III")


def test_sec_10q_sections_accept_same_line_contents_titles() -> None:
    html = """<p>Part I. Financial Information</p>
<p>Item 1. Financial Statements</p><p>Balance Sheet</p>
<p>Item 2. Management Discussion</p><p>Item 3. Market Risk</p>
<p>Item 4. Controls</p><p>Part II. Other Information</p>
<p>Item 1. Legal Proceedings</p><p>Item 6. Exhibits</p>
<p>PART I. FINANCIAL INFORMATION</p>
<p>ITEM 1. FINANCIAL STATEMENTS</p><p>Balance sheet.</p>
<p>ITEM 2. MANAGEMENT DISCUSSION</p><p>Discussion.</p>
<p>ITEM 3. MARKET RISK</p><p>Risk.</p>
<p>ITEM 4. CONTROLS</p><p>Effective.</p>
<p>PART II. OTHER INFORMATION</p>
<p>ITEM 1. LEGAL PROCEEDINGS</p><p>None.</p>
<p>ITEM 6. EXHIBITS</p><p>Index.</p><p>SIGNATURE</p>"""
    transport, _ = _transport(quarterly_html=html.encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="quarterly").latest()

    assert [(section.part, section.item) for section in filing.sections()] == [
        ("I", "1"), ("I", "2"), ("I", "3"), ("I", "4"), ("II", "1"), ("II", "6"),
    ]


def test_sec_10q_sections_fail_when_part_ii_contents_are_missing() -> None:
    html = """<p>Part I</p><p>Item 1.</p><p>Financial Statements</p>
<p>Item 2.</p><p>Discussion</p><p>Item 3.</p><p>Market Risk</p>
<p>Item 4.</p><p>Controls</p><p>ITEM 1. FINANCIAL STATEMENTS</p>"""
    transport, _ = _transport(quarterly_html=html.encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="quarterly").latest()

    with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
        filing.sections()


def test_sec_10q_sections_use_verified_contents_anchors_for_unlabelled_items() -> None:
    html = """<p>Part I</p><table>
<tr><td><p>Item 1.</p></td><td><p><a href="#statements">Financial Statements</a></p></td></tr>
<tr><td><p>Item 2.</p></td><td><p><a href="#discussion">Management's Discussion</a></p></td></tr>
</table><p>Item 3.</p><p>Market Risk</p><p>Item 4.</p><p>Controls</p>
<p>Part II</p><p>Item 1.</p><p>Legal Proceedings</p>
<p>Item 1A.</p><p>Risk Factors</p><p>Item 2.</p><p>Unregistered Sales</p>
<p>Item 5.</p><p>Other Information</p><p>Item 6.</p><p>Exhibits</p>
<div id="discussion"></div><p>INTRODUCTION</p><p>Operating analysis.</p>
<div id="statements"></div><p>Consolidated statements</p><p>Income data.</p>
<p>Item 3. Market Risk</p><p>Rates.</p><p>Item 4. Controls</p><p>Effective.</p>
<p>Part II. Other Information</p><p>Item 1. Legal Proceedings</p><p>None.</p>
<p>Item 1A. Risk Factors</p><p>Competition.</p>
<p>Item 2. Unregistered Sales</p><p>None.</p>
<p>Item 5. Other Information</p><p>None.</p>
<p>Item 6. Exhibits</p><p>Index.</p><p>SIGNATURE</p>"""
    transport, _ = _transport(quarterly_html=html.encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="quarterly").latest()

    sections = filing.sections()
    assert [(section.part, section.item) for section in sections[:2]] == [("I", "1"), ("I", "2")]
    assert sections[0].text.startswith("Consolidated statements")
    assert sections[1].text.startswith("INTRODUCTION")
    assert sections[1].end_line < sections[0].start_line
    assert "Income data." not in sections[1].text
    for replacement in ('<span id="discussion"></span>', '<div id="other"></div>'):
        changed = html.replace('<div id="discussion"></div>', replacement)
        bad_transport, _ = _transport(quarterly_html=changed.encode())
        bad_filing = Company("AAPL", market="US", provider=SECProvider(
            user_agent="Example Contact contact@example.com", transport=bad_transport,
        )).filings(form="quarterly").latest()
        with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
            bad_filing.sections()


def test_sec_10q_sections_use_unique_contents_link_for_repeated_body_heading() -> None:
    html = """<p>Part I</p><table>
<tr><td>Item 1.</td><td>Financial Statements</td></tr>
<tr><td>Item 2.</td><td><a href="#analysis">Management's Discussion</a></td></tr>
</table><p>Item 3.</p><p>Market Risk</p><p>Item 4.</p><p>Controls</p>
<p>Part II</p><p>Item 1.</p><p>Legal Proceedings</p>
<p>Item 2.</p><p>Unregistered Sales</p><p>Item 6.</p><p>Exhibits</p>
<p>Part I Financial Information</p>
<p>Item 1. Financial Statements</p><p>Balances.</p>
<p id="analysis">Item 2. Management's Discussion</p><p>Opening analysis.</p>
<p>Item 2. Management's Discussion</p><p>Continued analysis.</p>
<p>Item 3. Market Risk</p><p>Rates.</p><p>Item 4. Controls</p><p>Effective.</p>
<p>Part II Other Information</p><p>Item 1. Legal Proceedings</p><p>None.</p>
<p>Item 2. Unregistered Sales</p><p>None.</p><p>Item 6. Exhibits</p><p>Index.</p>
<p>SIGNATURE</p>"""
    transport, _ = _transport(quarterly_html=html.encode())
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="quarterly").latest()

    sections = filing.sections()
    item_2 = next(section for section in sections if section.part == "I" and section.item == "2")
    assert item_2.text.startswith("Item 2. Management's Discussion\nOpening analysis.")
    assert "Continued analysis." in item_2.text
    assert "Market Risk" not in item_2.text

    for changed in (html.replace('id="analysis"', 'id="other"'),
                    html.replace('<p id="analysis">', '<span id="analysis">'),
                    html.replace('<p>Item 2. Management\'s Discussion</p><p>Continued analysis.</p>',
                                 '<p id="analysis">Item 2. Management\'s Discussion</p><p>Continued analysis.</p>')):
        bad_transport, _ = _transport(quarterly_html=changed.encode())
        bad_filing = Company("AAPL", market="US", provider=SECProvider(
            user_agent="Example Contact contact@example.com", transport=bad_transport,
        )).filings(form="quarterly").latest()
        with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
            bad_filing.sections()


def test_sec_primary_document_avoids_archive_listing_until_documents_are_requested() -> None:
    transport, requests = _transport()
    filing = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()
    primary = filing.primary_document
    assert primary.filename == "aapl-20240928.htm"
    assert primary.source_url.endswith("/aapl-20240928.htm")
    assert filing.text() == "Annual report\nRevenue grew."
    assert not any("/Archives/" in request.url.path and request.url.path.endswith(("index.json", "-index.htm"))
                   for request in requests)
    assert len(filing.documents) == 3
    assert filing.primary_document is primary
    assert filing.select_document(filename="aapl-20240928.htm") is primary
    assert primary.description == "Annual report"
    assert primary.provider_metadata["index_sequence"] == "1"
    assert sum(request.url.path.endswith("/aapl-20240928.htm") for request in requests) == 1


def test_sec_primary_document_falls_back_to_listing_without_a_source_filename() -> None:
    transport, requests = _transport()
    original_get_json = transport.get_json

    def no_primary(url: str, **kwargs: object) -> dict:
        payload = original_get_json(url, **kwargs)
        if url.endswith("/submissions/CIK0000320193.json"):
            payload["filings"]["recent"].pop("primaryDocument")
        return payload

    transport.get_json = no_primary
    filing = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()
    assert filing.primary_document.filename == "aapl-20240928.htm"
    assert any(request.url.path.endswith("/index.json") for request in requests)


def test_sec_amendment_and_cik_lookup() -> None:
    transport, requests = _transport()
    company = Company("320193", market="US", provider=SECProvider(user_agent="Example Contact contact@example.com", transport=transport))
    assert [filing.filing_id for filing in company.filings(form="annual", include_amendments=False)] == ["0000320193-24-000123"]
    assert [filing.filing_id for filing in company.filings(form="annual")] == ["0000320193-24-000123"]
    assert [filing.filing_id for filing in company.filings(form="annual", include_amendments=True)] == [
        "0000320193-24-000123", "0000320193-23-000106"]
    assert [filing.filing_id for filing in company.filings(form="10-k")] == ["0000320193-24-000123"]
    assert [filing.filing_id for filing in company.filings(form="10-K/A")] == ["0000320193-23-000106"]
    assert not any(request.url.path.endswith("company_tickers_exchange.json") for request in requests)


def test_sec_exact_ticker_uses_small_official_mapping_before_exchange_json() -> None:
    transport, requests = _transport()
    original_get = transport.get

    def ticker_text(url: str, **kwargs: object) -> bytes:
        if url.endswith("/include/ticker.txt"):
            return b"aapl\t320193\nmsft\t789019\n"
        return original_get(url, **kwargs)

    transport.get = ticker_text
    company = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    assert company.entity.entity_id == "0000320193"
    assert not any(request.url.path.endswith("company_tickers_exchange.json") for request in requests)


def test_sec_ticker_mapping_miss_falls_back_to_exchange_json() -> None:
    transport, requests = _transport()
    original_get = transport.get

    def ticker_text(url: str, **kwargs: object) -> bytes:
        if url.endswith("/include/ticker.txt"):
            return b"msft\t789019\n"
        return original_get(url, **kwargs)

    transport.get = ticker_text
    company = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    assert company.entity.entity_id == "0000320193"
    assert any(request.url.path.endswith("company_tickers_exchange.json") for request in requests)


def test_sec_ticker_mapping_duplicate_ciks_is_ambiguous() -> None:
    transport, _ = _transport()
    original_get = transport.get

    def ticker_text(url: str, **kwargs: object) -> bytes:
        if url.endswith("/include/ticker.txt"):
            return b"aapl\t320193\naapl\t123456\n"
        return original_get(url, **kwargs)

    transport.get = ticker_text
    company = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    with pytest.raises(AmbiguousEntityError):
        _ = company.entity


def test_sec_stale_ticker_mapping_rechecks_exchange_listing_and_profile() -> None:
    transport, requests = _transport()
    original_get = transport.get
    original_get_json = transport.get_json

    def stale_ticker_text(url: str, **kwargs: object) -> bytes:
        if url.endswith("/include/ticker.txt"):
            return b"aapl\t123456\n"
        return original_get(url, **kwargs)

    def profiles(url: str, **kwargs: object) -> dict:
        if url.endswith("/CIK0000123456.json"):
            return {"cik": "0000123456", "name": "Former Apple", "tickers": ["OLD"]}
        return original_get_json(url, **kwargs)

    transport.get = stale_ticker_text
    transport.get_json = profiles
    company = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    assert company.entity.entity_id == "0000320193"
    assert any(request.url.path.endswith("company_tickers_exchange.json") for request in requests)


def test_sec_removed_ticker_mapping_cik_rechecks_exchange_listing() -> None:
    transport, requests = _transport()
    original_get = transport.get

    def stale_ticker_text(url: str, **kwargs: object) -> bytes:
        if url.endswith("/include/ticker.txt"):
            return b"aapl\t123456\n"
        return original_get(url, **kwargs)

    transport.get = stale_ticker_text
    company = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    assert company.entity.entity_id == "0000320193"
    assert any(request.url.path.endswith("company_tickers_exchange.json") for request in requests)


def test_sec_ticker_mapping_mismatch_fails_closed_when_exchange_agrees() -> None:
    transport, _ = _transport()
    original_get = transport.get
    original_get_json = transport.get_json

    def ticker_text(url: str, **kwargs: object) -> bytes:
        if url.endswith("/include/ticker.txt"):
            return b"aapl\t320193\n"
        return original_get(url, **kwargs)

    def stale_profile(url: str, **kwargs: object) -> dict:
        if url.endswith("/CIK0000320193.json"):
            return {"cik": "0000320193", "name": "Former Apple", "tickers": ["OLD"]}
        return original_get_json(url, **kwargs)

    transport.get = ticker_text
    transport.get_json = stale_profile
    company = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    with pytest.raises(EntityNotFoundError, match="AAPL"):
        _ = company.entity


def test_sec_date_filter_skips_historical_submission_files_outside_range() -> None:
    transport, _ = _transport()
    original_get_json = transport.get_json
    requested: list[str] = []

    def dated_submissions(url: str, **kwargs: object) -> dict:
        requested.append(url)
        if url.endswith("/CIK0000320193.json"):
            payload = original_get_json(url, **kwargs)
            payload["filings"]["files"] = [
                {"name": "CIK0000320193-submissions-2024.json", "filingTo": "2024-03-01"},
                {"name": "CIK0000320193-submissions-2023.json", "filingTo": "2023-12-31"},
                {"name": "CIK0000320193-submissions-unknown.json", "filingTo": "unknown"},
            ]
            return payload
        if url.endswith("/CIK0000320193-submissions-2024.json"):
            return {"accessionNumber": ["0000320193-24-000001"],
                    "filingDate": ["2024-03-01"], "reportDate": ["2023-12-31"],
                    "form": ["10-K"], "primaryDocument": ["annual.htm"]}
        if url.endswith("/CIK0000320193-submissions-2023.json"):
            raise AssertionError("out-of-range historical SEC file was fetched")
        if url.endswith("/CIK0000320193-submissions-unknown.json"):
            return {"accessionNumber": []}
        return original_get_json(url, **kwargs)

    transport.get_json = dated_submissions
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    filings = list(company.filings(form="annual", start="2024-01-01"))
    assert [filing.filing_id for filing in filings] == [
        "0000320193-24-000123", "0000320193-24-000001",
    ]
    assert any(url.endswith("/CIK0000320193-submissions-2024.json") for url in requested)
    assert any(url.endswith("/CIK0000320193-submissions-unknown.json") for url in requested)
    assert not any(url.endswith("/CIK0000320193-submissions-2023.json") for url in requested)


def test_sec_end_filter_skips_historical_submission_files_after_range() -> None:
    transport, _ = _transport()
    original_get_json = transport.get_json
    requested: list[str] = []

    def dated_submissions(url: str, **kwargs: object) -> dict:
        requested.append(url)
        if url.endswith("/CIK0000320193.json"):
            payload = original_get_json(url, **kwargs)
            payload["filings"]["files"] = [
                {"name": "CIK0000320193-submissions-2024.json", "filingFrom": "2024-01-01"},
                {"name": "CIK0000320193-submissions-2022.json", "filingFrom": "2022-01-01"},
            ]
            return payload
        if url.endswith("/CIK0000320193-submissions-2024.json"):
            raise AssertionError("future historical SEC file was fetched")
        if url.endswith("/CIK0000320193-submissions-2022.json"):
            return {"accessionNumber": ["0000320193-22-000001"],
                    "filingDate": ["2022-10-28"], "reportDate": ["2022-09-24"],
                    "form": ["10-K"], "primaryDocument": ["annual.htm"]}
        return original_get_json(url, **kwargs)

    transport.get_json = dated_submissions
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    filings = list(company.filings(form="annual", end="2022-12-31"))
    assert [filing.filing_id for filing in filings] == ["0000320193-22-000001"]
    assert any(url.endswith("/CIK0000320193-submissions-2022.json") for url in requested)
    assert not any(url.endswith("/CIK0000320193-submissions-2024.json") for url in requested)


def test_sec_direct_accession_lookup_uses_original_index_without_listing_scan() -> None:
    transport, requests = _transport()
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    filing = company.get_filing(_DIRECT_ACCESSION)
    assert filing.filing_type_raw == "10-K"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.filing_date.isoformat() == "2022-10-28"
    assert filing.period_end.isoformat() == "2022-09-24"
    assert filing.provider_metadata["accepted_display"] == "2022-10-28 06:00:00"
    assert filing.published_at is None
    assert filing.primary_document.filename == "annual.htm"
    assert filing.text() == "Annual report"
    assert not any("/submissions/CIK0000320193-" in request.url.path for request in requests)
    assert sum(request.url.path.endswith(f"/{_DIRECT_ACCESSION}-index.htm") for request in requests) == 1
    assert not any(request.url.path.endswith("/index.json") for request in requests)


def test_sec_index_exhibits_have_raw_type_description_and_reuse_direct_index() -> None:
    transport, requests = _transport()
    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=transport)
    recent = Company("AAPL", market="US", provider=provider).filings(form="annual").latest()
    exhibit = recent.select_document(document_type="EX-21.1")
    assert exhibit.filename == "aapl-ex21.htm"
    assert exhibit.description == "Subsidiaries of Apple Inc."
    assert recent.select_document(description="Subsidiaries of Apple Inc.") is exhibit
    assert exhibit.provider_metadata["index_sequence"] == "2"
    assert exhibit.provider_metadata["index_description"] == "Subsidiaries of Apple Inc."
    assert exhibit.text() == "Apple subsidiaries"
    assert recent.select_document(filename="aapl-20240928.xsd").document_type is None
    assert sum(request.url.path.endswith("/0000320193-24-000123-index.htm") for request in requests) == 1

    direct = Company("320193", market="US", provider=provider).get_filing(_DIRECT_ACCESSION)
    assert direct.select_document(document_type="EX-10.1").description == "Material agreement"
    assert sum(request.url.path.endswith(f"/{_DIRECT_ACCESSION}-index.htm") for request in requests) == 1


def test_sec_directory_remains_available_when_optional_index_table_is_missing() -> None:
    transport, _ = _transport()
    original_get = transport.get

    def missing_index(url: str, **kwargs: object) -> bytes:
        if url.endswith("-index.htm"):
            raise ProviderError("source returned HTTP 404 for filing index")
        return original_get(url, **kwargs)

    transport.get = missing_index
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()
    assert filing.primary_document.filename == "aapl-20240928.htm"
    assert filing.primary_document.document_type == "10-K"
    assert len(filing.documents) == 3
    assert filing.select_document(filename="aapl-ex21.htm").document_type is None


def test_sec_direct_accession_accepts_agent_prefix_when_index_names_issuer() -> None:
    transport, requests = _transport()
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    filing = company.get_filing(_AGENT_ACCESSION)
    assert filing.entity_id == "0000320193"
    assert filing.filing_id == _AGENT_ACCESSION
    assert filing.source_url.endswith(f"/320193/{_AGENT_ACCESSION.replace('-', '')}/{_AGENT_ACCESSION}-index.htm")
    assert sum(request.url.path.endswith(f"/{_AGENT_ACCESSION}-index.htm") for request in requests) == 1


def test_sec_direct_accession_rejects_foreign_record_in_issuer_scoped_archive() -> None:
    transport, requests = _transport()
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    with pytest.raises(FilingNotFoundError):
        company.get_filing("0000000001-22-000001")
    assert any(request.url.path.endswith("/0000000001-22-000001-index.htm")
               and "/Archives/edgar/data/320193/" in request.url.path for request in requests)


def test_sec_direct_accession_rejects_index_with_another_issuer_cik() -> None:
    transport, _ = _transport()
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    _ = company.entity
    original_get = transport.get

    def foreign_index(url: str, **kwargs: object) -> bytes:
        if url.endswith(f"/{_DIRECT_ACCESSION}-index.htm"):
            return _DIRECT_INDEX.replace(b">0000320193</a>", b">0000789019</a>")
        return original_get(url, **kwargs)

    transport.get = foreign_index
    with pytest.raises(FilingNotFoundError, match="another company"):
        company.get_filing(_DIRECT_ACCESSION)


def test_sec_direct_accession_missing_record_and_invalid_id() -> None:
    transport, _ = _transport()
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    with pytest.raises(FilingNotFoundError):
        company.get_filing("0000320193-20-999999")
    with pytest.raises(ValueError, match="accession"):
        company.get_filing("../../other-company")


def test_sec_direct_accession_malformed_source_is_explicit() -> None:
    transport, _ = _transport()
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    _ = company.entity
    def malformed_index(url: str, **kwargs: object) -> bytes:
        return b"<html><div id='formName'>Form 10-K</div></html>"
    transport.get = malformed_index
    with pytest.raises(ParseError):
        company.get_filing(_DIRECT_ACCESSION)


def test_sec_raw_facts_read_original_filing_instance() -> None:
    transport, requests = _transport(instance=True)
    company = Company("AAPL", market="US", provider=SECProvider(user_agent="Example Contact contact@example.com", transport=transport))
    filing = company.filings(form="annual").latest()
    fact, = filing.facts
    assert fact.concept_raw == "us-gaap:Revenues"
    assert fact.value == "100"
    assert fact.context_id == "FY24"
    assert fact.dimensions == {"us-gaap:StatementBusinessSegmentsAxis": "us-gaap:ConsolidatedEntitiesMember"}
    assert fact.period_end.isoformat() == "2024-09-28"
    assert fact.provenance.source_url.endswith("/aapl-20240928_htm.xml")
    assert fact.source_location.startswith(fact.provenance.source_url)
    assert not any("companyfacts" in str(request.url) for request in requests)


def test_sec_saved_classic_instance_does_not_buffer_original(tmp_path) -> None:
    transport, _ = _transport(instance=True)
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()
    instance = next(document for document in filing.documents if document.filename.endswith("_htm.xml"))
    instance.download(tmp_path / "instance.xml")

    assert [fact.concept_raw for fact in filing.facts] == ["us-gaap:Revenues"]
    assert instance._cached_bytes is None


def test_sec_inline_only_xhtml_exposes_raw_tags() -> None:
    transport, _ = _transport(inline_xhtml=XHTML)
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()
    facts = filing.facts
    assert len(facts) == 3
    assert facts[0].concept_raw == "ex:Assets"
    assert facts[0].provenance.source_url.endswith("/aapl-20240928.htm")


def test_sec_saved_inline_facts_do_not_buffer_original(tmp_path) -> None:
    transport, _ = _transport(inline_xhtml=XHTML)
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()
    document = filing.primary_document
    document.download(tmp_path / "annual.htm")

    assert [fact.concept_raw for fact in filing.facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]
    assert document._cached_bytes is None


def test_sec_unknown_ticker_is_explicit() -> None:
    transport, _ = _transport()
    company = Company("MISSING", market="US", provider=SECProvider(user_agent="Example Contact contact@example.com", transport=transport))
    from opencorpfilings import EntityNotFoundError

    with pytest.raises(EntityNotFoundError, match="ticker"):
        _ = company.entity


def test_sec_zip_attachment_can_use_common_archive_member_view() -> None:
    assert _media_type("attachment.zip") == "application/zip"


@pytest.mark.parametrize("media_type,filename", [
    ("application/pdf", "bad.pdf"), ("application/zip", "bad.zip"),
])
def test_sec_selected_binary_rejects_html_error_body_with_http_200(tmp_path, media_type, filename) -> None:
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, content=b"<html>Document unavailable</html>"),
    )))
    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=transport)
    url = f"https://www.sec.gov/Archives/edgar/data/320193/123/{filename}"
    document = FilingDocument(
        document_id=filename, filing_id="0000320193-24-000123", filename=filename,
        source_url=url, provenance=Provenance("sec", provider.regulator, "US", url, filename),
        media_type=media_type, _provider=provider,
    )
    with pytest.raises(DownloadError, match="unexpected"):
        document.download()
    target = tmp_path / filename
    target.write_bytes(b"existing")
    with pytest.raises(ProviderError, match="unexpected document format"):
        document.download(target)
    assert target.read_bytes() == b"existing"


def test_sec_document_saves_without_buffering_and_reuses_saved_source(tmp_path) -> None:
    transport, requests = _transport()
    filing = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest()
    document = filing.primary_document
    target = tmp_path / "annual.htm"
    assert filing.download(target) == target
    assert target.read_bytes().startswith(b"<html>")
    assert document._cached_bytes is None
    calls = len(requests)
    assert document.download() == target.read_bytes()
    assert len(requests) == calls


def test_sec_saved_document_is_refetched_if_file_changes(tmp_path) -> None:
    transport, requests = _transport()
    document = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest().primary_document
    target = tmp_path / "annual.htm"
    document.download(target)
    calls = len(requests)
    target.write_bytes(b"tampered")
    assert document.download().startswith(b"<html>")
    assert len(requests) == calls + 1


def test_sec_second_path_save_reuses_verified_file_without_buffering(tmp_path) -> None:
    transport, requests = _transport()
    document = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest().primary_document
    first, second = tmp_path / "first.htm", tmp_path / "second.htm"
    document.download(first)
    calls = len(requests)
    assert document.download(second) == second
    assert second.read_bytes() == first.read_bytes()
    assert document._cached_bytes is None
    assert len(requests) == calls


def test_sec_second_path_save_refetches_when_saved_file_changes(tmp_path) -> None:
    transport, requests = _transport()
    document = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest().primary_document
    first, second = tmp_path / "first.htm", tmp_path / "second.htm"
    document.download(first)
    first.write_bytes(b"tampered")
    calls = len(requests)
    document.download(second)
    assert second.read_bytes().startswith(b"<html>")
    assert document._cached_bytes is None
    assert len(requests) == calls + 1


def test_sec_second_path_copy_preserves_target_if_replace_fails(tmp_path, monkeypatch) -> None:
    transport, requests = _transport()
    document = Company("AAPL", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport,
    )).filings(form="annual").latest().primary_document
    first, second = tmp_path / "first.htm", tmp_path / "second.htm"
    document.download(first)
    second.write_bytes(b"existing")
    calls = len(requests)

    def fail_replace(*_args: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        document.download(second)
    assert second.read_bytes() == b"existing"
    assert set(tmp_path.iterdir()) == {first, second}
    assert len(requests) == calls


def test_sec_search_puts_the_company_named_by_the_query_ahead_of_longer_names():
    # README walkthrough: "Apple" returned Apple Hospitality REIT before Apple Inc.
    class Listing:
        def get_json(self, url, **_):
            return {"fields": ["cik", "name", "ticker", "exchange"], "data": [
                [1418121, "Apple Hospitality REIT, Inc.", "APLE", "NYSE"],
                [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                [1134982, "Apple iSports Group, Inc.", "AAPI", "OTC"]]}

        def close(self):
            pass

    provider = SECProvider(user_agent="Example Contact contact@example.com", transport=Listing())
    assert [entity.name for entity in provider.search_entities("Apple", limit=3)][0] == "Apple Inc."
    assert provider.search_entities("aapl", limit=1)[0].name == "Apple Inc."


def _single_filing_transport(row: dict, directory: list[str], index: bytes = b"") -> tuple[HttpTransport, list[str]]:
    requested: list[str] = []
    recent = {key: [value] for key, value in row.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/submissions/CIK0000320193.json":
            return httpx.Response(200, json={"cik": "0000320193", "name": "Apple Inc.", "tickers": ["AAPL"],
                                             "filings": {"recent": recent, "files": []}})
        if request.url.path.endswith("/index.json"):
            return httpx.Response(200, json={"directory": {"item": [{"name": name, "type": "file"} for name in directory]}})
        if request.url.path.endswith("-index.htm"):
            return httpx.Response(200, content=index)
        return httpx.Response(200, content=b"<?xml version='1.0'?><ownershipDocument/>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpTransport(client=client, user_agent="Example Contact contact@example.com"), requested


@pytest.mark.parametrize("form", ["SCHEDULE 13G", "SCHEDULE 13G/A", "SCHEDULE 13D", "SC 13G"])
def test_sec_schedule_13d_and_13g_under_their_current_names_are_ownership(form: str) -> None:
    transport, _ = _single_filing_transport({
        "accessionNumber": "0000320193-25-000001", "filingDate": "2025-02-14", "reportDate": "",
        "form": form, "primaryDocument": "schedule.xml"}, ["schedule.xml"])
    company = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport))
    filing = company.filings(form="ownership", include_amendments=True).latest()
    assert filing.filing_type_raw == form
    assert filing.filing_type_normalized == "OWNERSHIP"


def test_sec_ownership_primary_is_the_filed_xml_not_secs_rendered_view() -> None:
    transport, _ = _single_filing_transport({
        "accessionNumber": "0000320193-25-000002", "filingDate": "2025-02-14", "reportDate": "2025-02-12",
        "form": "4", "primaryDocument": "xslF345X05/wk-form4_1739.xml"}, ["wk-form4_1739.xml"])
    filing = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport)).filings(form="4").latest()
    assert filing.primary_document.filename == "wk-form4_1739.xml"
    assert [(document.filename, document.is_primary, document.role) for document in filing.documents] == [
        ("wk-form4_1739.xml", True, "report")]
    assert filing.primary_document.source_url.endswith("/000032019325000002/wk-form4_1739.xml")


def test_sec_direct_accession_accepts_a_co_registrant_named_after_the_first_filer() -> None:
    index = _DIRECT_INDEX.replace(b'<div class="companyInfo">', b'<div class="companyInfo"><span class="companyName">'
                                  b'Parent Holdings (Filer) CIK: <a href="/cgi-bin/browse-edgar?CIK=0000789019">'
                                  b'0000789019</a></span></div><div class="companyInfo">', 1)
    transport, _ = _transport()
    original_get = transport.get
    transport.get = lambda url, **kwargs: index if url.endswith(f"/{_DIRECT_ACCESSION}-index.htm") else original_get(url, **kwargs)
    filing = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport)).get_filing(_DIRECT_ACCESSION)
    assert filing.entity_id == "0000320193"


def test_sec_raw_facts_on_a_filing_without_xbrl_fail_before_downloading_documents() -> None:
    transport, requested = _single_filing_transport({
        "accessionNumber": "0000320193-05-000003", "filingDate": "2005-12-01", "reportDate": "2005-09-24",
        "form": "10-K", "primaryDocument": "annual.htm", "isXBRL": 0, "isInlineXBRL": 0},
        ["annual.htm", "ex-99.htm", "data.xml"])
    filing = Company("320193", market="US", provider=SECProvider(
        user_agent="Example Contact contact@example.com", transport=transport)).filings(form="annual").latest()
    with pytest.raises(UnsupportedCapabilityError, match="no XBRL"):
        filing.facts()
    assert not any(path.endswith((".htm", ".xml")) and "index" not in path for path in requested)
