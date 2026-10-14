"""PDF text remains page-linked and conditional on the optional parser."""

from pathlib import Path
from io import BytesIO
import sys

import pytest

from opencorpfilings import FilingDocument, ParseError, Provenance, UnsupportedCapabilityError


FIXTURE = Path(__file__).parent / "fixtures" / "two_page_report.pdf"


class DocumentProvider:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = 0

    def supports(self, capability):
        return False

    def download_document(self, document):
        self.calls += 1
        return self.payload


def document(payload: bytes, *, media_type: str = "application/pdf"):
    url = "https://example.test/original-report.pdf"
    provider = DocumentProvider(payload)
    return FilingDocument(
        "pdf-1", "filing-1", "original-report.pdf", url,
        Provenance("fixture", "Fixture OAM", "FR", url, "pdf-1"),
        media_type=media_type, _provider=provider,
    ), provider


def test_pdf_pages_and_text_retain_original_page_location():
    report, provider = document(FIXTURE.read_bytes())
    pages = report.pages
    assert len(pages) == 2
    assert pages[0].number == 1
    assert "Annual revenue" in pages[0].text
    assert "Cash flow" in pages[1].text
    assert pages[1].source_url == report.source_url
    assert pages[1].source_location == report.source_url + "#page=2"
    assert pages[1].provenance.source_id == "pdf-1:page:2"
    assert "Cash flow" in report.text()
    assert provider.calls == 1


def test_pdf_pages_are_capability_gated_and_parser_is_optional(monkeypatch):
    html, _ = document(b"<p>not pdf</p>", media_type="text/html")
    with pytest.raises(UnsupportedCapabilityError, match="PDF"):
        _ = html.pages
    report, _ = document(FIXTURE.read_bytes())
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(UnsupportedCapabilityError, match="'pdf' extra"):
        _ = report.pages


def test_invalid_or_oversized_pdf_reports_parse_error(monkeypatch):
    invalid, _ = document(b"%PDF-1.7\ninvalid")
    with pytest.raises(ParseError):
        _ = invalid.pages

    import opencorpfilings.pdf_text as pdf_text

    monkeypatch.setattr(pdf_text, "MAX_PDF_BYTES", 100)
    oversized, _ = document(FIXTURE.read_bytes())
    with pytest.raises(ParseError, match="size limit"):
        _ = oversized.pages


def test_pdf_page_content_bound_is_checked(monkeypatch):
    import opencorpfilings.pdf_text as pdf_text

    monkeypatch.setattr(pdf_text, "MAX_PAGE_CONTENT_BYTES", 5)
    report, _ = document(FIXTURE.read_bytes())
    with pytest.raises(ParseError, match="page content limit"):
        _ = report.pages


def test_image_only_pages_do_not_claim_text():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    report, _ = document(output.getvalue())
    assert len(report.pages) == 2
    assert report.text() == ""


def test_pdf_page_extracts_only_selected_page_and_reuses_it(monkeypatch):
    import opencorpfilings.pdf_text as pdf_text

    report, provider = document(FIXTURE.read_bytes())
    extracted = []
    real_page_text = pdf_text._page_text
    def selected_only(page, number):
        extracted.append(number)
        return real_page_text(page, number)

    monkeypatch.setattr(pdf_text, "_page_text", selected_only)
    monkeypatch.setattr(pdf_text, "extract_pdf_pages", lambda content: pytest.fail("extracted every page"))
    page = report.page(2)
    assert page.number == 2
    assert "Cash flow" in page.text
    assert page.source_location == report.source_url + "#page=2"
    assert page.provenance.source_id == "pdf-1:page:2"
    assert report.page(2) is page
    assert extracted == [2]
    assert report._pages_cache is None
    assert provider.calls == 1


def test_pdf_page_reuses_full_page_cache_and_checks_bounds():
    report, provider = document(FIXTURE.read_bytes())
    assert report.page(1).number == 1
    with pytest.raises(ValueError, match="positive"):
        report.page(0)
    with pytest.raises(IndexError, match="page 3"):
        report.page(3)
    pages = report.pages
    assert report.page(2) is pages[1]
    assert provider.calls == 1


def test_selected_pdf_page_respects_parser_and_content_limits(monkeypatch):
    import opencorpfilings.pdf_text as pdf_text

    invalid, _ = document(b"%PDF-1.7\ninvalid")
    with pytest.raises(ParseError):
        invalid.page(1)

    monkeypatch.setattr(pdf_text, "MAX_PDF_BYTES", 100)
    oversized, _ = document(FIXTURE.read_bytes())
    with pytest.raises(ParseError, match="size limit"):
        oversized.page(1)
    monkeypatch.setattr(pdf_text, "MAX_PDF_BYTES", 50_000_000)

    monkeypatch.setattr(pdf_text, "MAX_PAGE_CONTENT_BYTES", 5)
    report, _ = document(FIXTURE.read_bytes())
    with pytest.raises(ParseError, match="page content limit"):
        report.page(1)

    html, _ = document(b"<p>not pdf</p>", media_type="text/html")
    with pytest.raises(UnsupportedCapabilityError, match="PDF"):
        html.page(1)


def test_saved_pdf_page_and_text_use_verified_file_without_byte_cache(tmp_path):
    payload = FIXTURE.read_bytes()

    class StreamedProvider:
        calls = 0

        def supports(self, capability):
            return capability == "streamed_download"

        def save_document(self, _document, path):
            self.calls += 1
            path.write_bytes(payload)
            return path

    report, _ = document(payload)
    provider = StreamedProvider()
    report._provider = provider
    target = tmp_path / "report.pdf"
    report.download(target)
    assert "Cash flow" in report.page(2).text
    assert report._cached_bytes is None
    assert "Annual revenue" in report.text()
    assert report._cached_bytes is None
    assert provider.calls == 1

    target.write_bytes(b"changed after save")
    refreshed, _ = document(payload)
    refreshed._provider = provider
    refreshed._saved_path = target.resolve()
    refreshed._saved_sha256 = report._saved_sha256
    assert "Annual revenue" in refreshed.page(1).text
    assert refreshed._cached_bytes is None
    assert target.read_bytes() == payload
    assert provider.calls == 2


def test_saved_pdf_path_keeps_parser_size_and_signature_checks(tmp_path, monkeypatch):
    import opencorpfilings.pdf_text as pdf_text

    path = tmp_path / "report.pdf"
    path.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(pdf_text, "MAX_PDF_BYTES", 100)
    with pytest.raises(ParseError, match="size limit"):
        pdf_text.extract_pdf_page(path, 1)
    monkeypatch.setattr(pdf_text, "MAX_PDF_BYTES", 50_000_000)
    path.write_bytes(b"<html>source error</html>")
    with pytest.raises(ParseError, match="not a PDF"):
        pdf_text.extract_pdf_page(path, 1)
