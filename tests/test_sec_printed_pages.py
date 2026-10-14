"""Source-backed SEC printed-page references, including misleading index labels."""

import pytest

from opencorpfilings import (
    Filing, FilingDocument, FilingSectionReference, FilingPrintedPage,
    Provenance, UnsupportedCapabilityError,
)
from opencorpfilings.providers.sec import SECProvider
from opencorpfilings import sec_printed_pages


def _filing(html: str) -> tuple[Filing, FilingDocument]:
    provider = SECProvider(user_agent="Example Contact contact@example.com")
    url = "https://www.sec.gov/Archives/edgar/data/1/2/annual.htm"
    provenance = Provenance("sec", "SEC", "US", url, "annual.htm")
    document = FilingDocument(
        document_id="annual.htm", filing_id="test", filename="annual.htm", source_url=url,
        provenance=provenance, media_type="text/html", is_primary=True,
        _provider=provider, _cached_bytes=html.encode(),
    )
    filing = Filing(
        filing_id="test", entity_id="1", jurisdiction="US", provider="sec", regulator="SEC",
        source_url=url, provenance=provenance, filing_type_raw="10-K", _primary_document=document,
        _documents=[document], _provider=provider,
    )
    return filing, document


def _reference(document: FilingDocument, target: str) -> FilingSectionReference:
    return FilingSectionReference(
        kind="page", target=target, source_text=f"See page {target}",
        document_id=document.document_id, source_url=document.source_url,
        source_line=1, provenance=document.provenance,
    )


def _page(label: str, body: str) -> str:
    return f"<p>{body}</p><p>{label}</p><div style='page-break-after:always'></div>"


def test_printed_page_uses_body_run_after_index_decoys() -> None:
    html = (
        _page("F-1", "Table of contents")
        + "<p>Other annual report text</p>"
        + "<p>Index to Consolidated Financial Statements</p><p>Balance Sheets</p><p>F-3</p>"
        + _page("F-1", "Financial index")
        + _page("F-2", "Auditor report")
        + _page("F-3", "Consolidated balance sheets")
        + _page("F-4", "Consolidated income statements")
    )
    filing, document = _filing(html)
    page = _reference(document, "F-3").resolve(filing)
    assert isinstance(page, FilingPrintedPage)
    assert page.label == "F-3"
    assert "Consolidated balance sheets" in page.text
    assert "Financial index" not in page.text
    assert "Consolidated income statements" not in page.text
    assert filing.text().splitlines()[page.start_line - 1:page.end_line] == page.text.splitlines()
    assert page.document_id == document.document_id
    assert page.source_url == document.source_url
    assert page.provenance.source_id.endswith("printed-page:F-3")


def test_printed_page_fails_without_verified_page_run() -> None:
    filing, document = _filing("<p>Index</p><p>F-1</p><p>Some other content</p><p>F-3</p>")
    with pytest.raises(UnsupportedCapabilityError, match="printed page"):
        _reference(document, "F-3").resolve(filing)


def test_printed_page_fails_on_equally_valid_runs() -> None:
    html = "".join(_page(f"F-{n}", f"First page {n}") for n in (1, 2, 3))
    html += "".join(_page(f"F-{n}", f"Second page {n}") for n in (1, 2, 3))
    filing, document = _filing(html)
    with pytest.raises(UnsupportedCapabilityError, match="ambiguous"):
        _reference(document, "F-3").resolve(filing)


def test_numbered_annual_report_page_uses_verified_footer_run() -> None:
    footer = "Example Corporation 2025 Annual Report"
    html = (
        f"<p>Cross-reference index</p><p>{footer} 38</p>"
        + "".join(_page(f"{footer} {n}", f"Source page {n}") for n in (37, 38, 39, 40))
    )
    filing, document = _filing(html)
    assert document._provider.supports("printed_pages")
    page = document.printed_page("38")
    assert isinstance(page, FilingPrintedPage)
    assert page.label == "38"
    assert "Source page 38" in page.text
    assert "Cross-reference index" not in page.text
    assert "Source page 39" not in page.text
    assert filing.text().splitlines()[page.start_line - 1:page.end_line] == page.text.splitlines()
    assert page.provenance.source_id.endswith("printed-page:38")


def test_numbered_form_10k_pages_accept_footer_number_on_either_side() -> None:
    footer = "2025 FORM 10-K"
    html = "".join(
        _page(f"{footer} {n}" if n % 2 else f"{n} {footer}", f"Report page {n}")
        for n in (36, 37, 38, 39)
    )
    filing, document = _filing(html)
    page = document.printed_page("38")
    assert page.text.splitlines()[0] == "Report page 38"
    assert page.text.splitlines()[-1] == f"38 {footer}"
    assert filing.text().splitlines()[page.start_line - 1:page.end_line] == page.text.splitlines()


def test_numbered_form_10k_pages_accept_adjacent_footer_lines() -> None:
    footer = "Example Corporation | Fiscal 2026 Form 10-K"
    html = "".join(
        f"<p>Report page {n}</p><p>{footer if n % 2 else n}</p>"
        f"<p>{n if n % 2 else footer}</p><div style='page-break-after:always'></div>"
        for n in (49, 50, 51, 52)
    )
    filing, document = _filing(html)
    page = document.printed_page("50")
    assert page.text.splitlines()[0] == "Report page 50"
    assert page.text.splitlines()[-2:] == ["50", footer]
    assert filing.text().splitlines()[page.start_line - 1:page.end_line] == page.text.splitlines()


def test_numbered_page_rejects_short_or_mixed_footer_runs() -> None:
    footer = "Example Corporation 2025 Annual Report"
    _, short = _filing("".join(_page(f"{footer} {n}", f"Page {n}") for n in (38, 39)))
    with pytest.raises(UnsupportedCapabilityError, match="verified"):
        short.printed_page("38")
    _, mixed = _filing(
        _page(f"{footer} 37", "Page 37")
        + _page("Other Corporation 2025 Annual Report 38", "Page 38")
        + _page(f"{footer} 39", "Page 39")
    )
    with pytest.raises(UnsupportedCapabilityError, match="verified"):
        mixed.printed_page("38")


def test_numbered_page_rejects_equally_long_footer_runs() -> None:
    footer = "Example Corporation 2025 Annual Report"
    html = "".join(_page(f"{footer} {n}", f"First {n}") for n in (37, 38, 39))
    html += "".join(_page(f"{footer} {n}", f"Second {n}") for n in (37, 38, 39))
    _, document = _filing(html)
    with pytest.raises(UnsupportedCapabilityError, match="ambiguous"):
        document.printed_page("38")


def test_printed_pages_reuse_one_verified_footer_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    footer = "Example Corporation 2025 Annual Report"
    html = "".join(_page(f"{footer} {n}", f"Source page {n}") for n in (37, 38, 39, 40))
    filing, document = _filing(html)
    scans = []
    actual = sec_printed_pages.html_to_text_line_offsets

    def counted(source: str, offsets: list[int]) -> list[int]:
        scans.append(1)
        return actual(source, offsets)

    monkeypatch.setattr(sec_printed_pages, "html_to_text_line_offsets", counted)
    assert document.printed_page("37").label == "37"
    assert _reference(document, "38").resolve(filing).label == "38"
    assert document.printed_page("39").label == "39"
    assert len(scans) == 1


def test_terminal_10k_index_exposes_page_pointer_without_claiming_section() -> None:
    footer = "Example Corporation 2025 Annual Report"
    body = "".join(_page(f"{footer} {n}", f"Report page {n}") for n in range(3, 21))
    index = "<p>Form 10-K Cross-Reference Index</p><p>Page reference</p>"
    index += "".join(
        f"<p>Item {n}\tSource title {n}</p><p>Page {n + 2}{', (a)' if n == 10 else ''}</p>"
        for n in range(1, 16)
    )
    filing, _ = _filing(body + index + "<p>Signatures</p>")
    references = filing.section_references("8")
    assert len(references) == 1
    assert references[0].kind == "page"
    assert references[0].target == "10"
    assert references[0].source_text == "Page 10"
    assert references[0].resolve(filing).label == "10"
    assert filing.section_references("Item 10")[0].source_text == "Page 12, (a)"


def test_terminal_10k_index_exposes_explicit_page_ranges() -> None:
    footer = "2025 FORM 10-K"
    body = "".join(_page(f"{footer} {n}", f"Report page {n}") for n in range(3, 26))
    index = "<p>FORM 10-K CROSS REFERENCE INDEX\tPage(s)</p>"
    for n in range(1, 16):
        index += f"<p>Item {n}.\tSource title {n}\t{'10-12' if n == 8 else n + 2}</p>"
        if n == 7:
            index += "<p>Item 7A.\tMarket risk\t5, 13-14</p>"
    filing, _ = _filing(body + index + "<p>SIGNATURES</p>")
    references = filing.section_references("8")
    assert len(references) == 1
    assert references[0].kind == "page_range"
    assert references[0].target == "10-12"
    assert references[0].source_text == "Item 8.\tSource title 8\t10-12"
    pages = references[0].resolve(filing)
    assert tuple(page.label for page in pages) == ("10", "11", "12")
    assert pages[0].text.splitlines()[0] == "Report page 10"
    assert pages[-1].text.splitlines()[0] == "Report page 12"
    risk = filing.section_references("7A")
    assert [(reference.kind, reference.target) for reference in risk] == [
        ("page", "5"), ("page_range", "13-14"),
    ]


def test_terminal_split_cell_index_exposes_only_verified_start_pages() -> None:
    body = "".join(_page(f"2026 FORM 10-K {n}", f"Report page {n}") for n in range(3, 41))
    index = "<p>Form 10-K Cross Reference Index</p><p>Form 10-K Cross Reference Index</p>"
    index += "<p>Item\t\tPage(s)</p><p>Part I</p>"
    for n in range(1, 16):
        if n == 10:
            index += "<p>9B\tOther Information\tN/A</p><p>Part III</p>"
        index += f"<p>{n}</p><p>Source title {n}</p><p>{n + 2}</p>"
    filing, _ = _filing(body + index + "<p>Signatures</p>")
    reference, = filing.section_references("8")
    assert (reference.kind, reference.target, reference.source_text) == ("page", "10", "10")
    assert reference.resolve(filing).text.splitlines()[0] == "Report page 10"
    assert filing.section_references("10")[0].target == "12"
    with pytest.raises(UnsupportedCapabilityError):
        filing.section("8")


def test_split_cell_index_accepts_repeated_heading_and_long_filed_title() -> None:
    body = "".join(_page(f"2026 FORM 10-K {n}", f"Report page {n}") for n in range(3, 41))
    heading = "<p>Form 10-K Cross Reference Index</p>" * 3
    index = heading + "<p>Item\t\tPage(s)</p>"
    for n in range(1, 16):
        if n == 10:
            index += "<p>9B\tOther Information\tN/A</p><p>Part III</p>"
        title = "Long as-filed title " * 12 if n == 8 else f"Source title {n}"
        index += f"<p>{n}</p><p>{title}</p><p>{n + 2}</p>"
    filing, _ = _filing(body + index + "<p>Signatures</p>")
    assert filing.section_references("8")[0].target == "10"
    assert filing.section_references("10")[0].target == "12"


def test_early_or_short_index_does_not_claim_item_pages() -> None:
    short = "<p>Form 10-K Cross-Reference Index</p><p>Item 8 Financials</p><p>Page 10</p>"
    filing, _ = _filing(short + "<p>Signatures</p>")
    with pytest.raises(UnsupportedCapabilityError):
        filing.section_references("8")


def test_index_pointer_requires_a_verified_target_page() -> None:
    footer = "Example Corporation 2025 Annual Report"
    body = "".join(_page(f"{footer} {n}", f"Report page {n}") for n in range(3, 23))
    index = "<p>Form 10-K Cross-Reference Index</p>"
    index += "".join(
        f"<p>Item {n}\tSource title {n}</p><p>Page {100 if n == 8 else n + 2}</p>"
        for n in range(1, 16)
    )
    filing, _ = _filing(body + index + "<p>Signatures</p>")
    with pytest.raises(UnsupportedCapabilityError, match="unavailable"):
        filing.section_references("8")


def test_index_range_requires_every_page_in_its_original_run() -> None:
    footer = "2025 FORM 10-K"
    body = "".join(_page(f"{footer} {n}", f"Report page {n}") for n in range(3, 23))
    index = "<p>FORM 10-K CROSS REFERENCE INDEX\tPage(s)</p>"
    index += "".join(
        f"<p>Item {n}.\tSource title {n}\t{'20-24' if n == 8 else n + 2}</p>"
        for n in range(1, 16)
    )
    filing, _ = _filing(body + index + "<p>SIGNATURES</p>")
    with pytest.raises(UnsupportedCapabilityError, match="unavailable"):
        filing.section_references("8")


def test_index_rejects_reversed_page_range() -> None:
    footer = "2025 FORM 10-K"
    body = "".join(_page(f"{footer} {n}", f"Report page {n}") for n in range(3, 23))
    index = "<p>FORM 10-K CROSS REFERENCE INDEX\tPage(s)</p>"
    index += "".join(
        f"<p>Item {n}.\tSource title {n}\t{'12-10' if n == 8 else n + 2}</p>"
        for n in range(1, 16)
    )
    filing, _ = _filing(body + index + "<p>SIGNATURES</p>")
    with pytest.raises(UnsupportedCapabilityError, match="reversed"):
        filing.section_references("8")


def test_exhibit_reference_resolves_one_enumerated_original() -> None:
    filing, primary = _filing("<p>See Exhibit 13</p>")
    exhibit = FilingDocument(
        document_id="ex-13.htm", filing_id="test", filename="ex-13.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/1/2/ex-13.htm",
        provenance=Provenance("sec", "SEC", "US",
                              "https://www.sec.gov/Archives/edgar/data/1/2/ex-13.htm", "ex-13.htm"),
        media_type="text/html", document_type="EX-13",
        _provider=primary._provider,
    )
    filing._documents = [primary, exhibit]
    reference = FilingSectionReference(
        kind="document", target="EX-13", source_text="See Exhibit 13",
        document_id=primary.document_id, source_url=primary.source_url,
        source_line=1, provenance=primary.provenance,
    )
    assert reference.resolve(filing) is exhibit
    other, _ = _filing("<p>Another filing</p>")
    other.primary_document.document_id = "different.htm"
    with pytest.raises(UnsupportedCapabilityError, match="does not belong"):
        reference.resolve(other)
