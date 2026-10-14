"""SEC current-report navigation follows source headings and stops at the signature."""

import pytest

from opencorpfilings import Filing, FilingDocument, Provenance, UnsupportedCapabilityError
from opencorpfilings.html_text import html_to_text
from opencorpfilings.sec_sections import sec_8k_sections


class _Provider:
    def __init__(self, original: bytes):
        self.original = original

    def download_document(self, document):
        return self.original

    def extract_text(self, document):
        return html_to_text(document.download())

    def extract_sections(self, filing):
        return sec_8k_sections(filing.primary_document)


def _filing(html: str) -> Filing:
    source_url = "https://www.sec.gov/Archives/edgar/data/1/filing.htm"
    provenance = Provenance("sec", "SEC", "US", source_url, "accession-1")
    provider = _Provider(html.encode())
    document = FilingDocument(
        "accession-1:primary", "accession-1", "filing.htm", source_url,
        provenance, media_type="text/html", is_primary=True, _provider=provider,
    )
    return Filing(
        "accession-1", "1", "US", "sec", "SEC", source_url, provenance,
        filing_type_raw="8-K", _documents=[document], _primary_document=document,
        _provider=provider,
    )


def test_8k_inline_item_headings_and_signature_boundary() -> None:
    filing = _filing("""<p>Cover page</p>
<p>Item 2.02 Results of Operations and Financial Condition.</p><p>Results prose.</p>
<p>Item 9.01 Financial Statements and Exhibits.</p><p>(d) Exhibits.</p>
<p>SIGNATURE</p><p>Signed by officer.</p>""")

    sections = filing.sections()
    assert [section.item for section in sections] == ["2.02", "9.01"]
    assert filing.section("Item 2.02").title == "Results of Operations and Financial Condition."
    assert filing.section("9.01").text.endswith("(d) Exhibits.")
    assert "SIGNATURE" not in filing.section("9.01").text
    assert sections[0].source_url == filing.primary_document.source_url
    assert sections[0].provenance == filing.primary_document.provenance
    assert sections[0].end_line < sections[1].start_line


def test_8k_split_caption_does_not_treat_body_reference_as_heading() -> None:
    filing = _filing("""<p>Cover page</p>
<p>Item 8.01.</p><p>Other Events.</p><p>Transaction prose.</p>
<p>Item 9.01(c) is mentioned in the transaction terms.</p>
<p>Item 9.01.</p><p>Financial Statements and Exhibits.</p><p>Exhibit list.</p>
<p>SIGNATURES</p>""")

    sections = filing.sections()
    assert [section.item for section in sections] == ["8.01", "9.01"]
    assert filing.section("8.01").title == "Other Events."
    assert "Item 9.01(c)" in filing.section("8.01").text
    assert filing.section("9.01").start_line > filing.section("8.01").start_line


def test_8k_split_caption_without_punctuation() -> None:
    filing = _filing("""<p>Cover page</p>
<p>Item 8.01</p><p>Other Events</p><p>Source event.</p>
<p>Item 9.01</p><p>Financial Statements and Exhibits</p><p>Exhibit list.</p>
<p>SIGNATURE</p>""")

    assert [section.item for section in filing.sections()] == ["8.01", "9.01"]
    assert filing.section("8.01").title == "Other Events"


def test_8k_contents_captions_resolve_to_later_body_headings() -> None:
    filing = _filing("""<p>Cover page</p><p>TABLE OF CONTENTS</p>
<p>ITEM 8.01. OTHER EVENTS.</p><p>3</p>
<p>ITEM 9.01. FINANCIAL STATEMENTS AND EXHIBITS.</p><p>4</p>
<p>SIGNATURES</p><p>5</p>
<p>ITEM 8.01.</p><p>OTHER EVENTS.</p><p>Actual event.</p>
<p>ITEM 9.01.</p><p>FINANCIAL STATEMENTS AND EXHIBITS.</p><p>Actual exhibits.</p>
<p>SIGNATURES</p><p>Signed.</p>""")

    sections = filing.sections()
    assert [section.item for section in sections] == ["8.01", "9.01"]
    assert sections[0].text.endswith("Actual event.")
    assert sections[0].start_line > 6
    assert sections[1].text.endswith("Actual exhibits.")
    assert "SIGNATURES" not in sections[1].text


@pytest.mark.parametrize("html", [
    "<p>Item 8.01 Other Events.</p><p>First.</p><p>Item 8.01 Other Events.</p><p>Second.</p><p>SIGNATURE</p>",
    "<p>Item 8.01 Other Events.</p><p>Event without a signature boundary.</p>",
    "<p>Item 8.01 Other Events.</p><p>SIGNATURES</p><p>Item 9.01 Financial Statements and Exhibits.</p><p>SIGNATURES</p>",
])
def test_8k_ambiguous_or_unbounded_source_fails_closed(html: str) -> None:
    with pytest.raises(UnsupportedCapabilityError, match="verified section boundaries"):
        _filing(html).sections()
