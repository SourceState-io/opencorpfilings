"""Original HTML access on direct documents and selected archive members."""

from io import BytesIO
from zipfile import ZipFile

import pytest

from opencorpfilings import Filing, FilingDocument, ParseError, Provenance, UnsupportedCapabilityError
from opencorpfilings.html_text import html_to_text, html_to_text_line_offsets


class HtmlProvider:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    def download_document(self, _document: FilingDocument) -> bytes:
        self.calls += 1
        return self.content


def _document(content: bytes, media_type: str = "text/html") -> FilingDocument:
    url = "https://example.test/report.html"
    return FilingDocument(
        "doc-1", "filing-1", "report.html", url,
        Provenance("fixture", "Registry", "US", url, "doc-1"),
        media_type=media_type, is_primary=True, _provider=HtmlProvider(content),
    )


def test_direct_html_and_filing_html_reuse_original_bytes() -> None:
    document = _document("<html><p>Café</p></html>".encode("utf-8"))
    filing = Filing(
        "filing-1", "issuer-1", "US", "fixture", "Registry",
        "https://example.test/filing", Provenance("fixture", "Registry", "US", "https://example.test/filing", "filing-1"),
        _documents=[document], _provider=document._provider,
    )
    assert document.html() == "<html><p>Café</p></html>"
    assert filing.html() == document.html()
    assert document.download() == "<html><p>Café</p></html>".encode("utf-8")
    assert document._provider.calls == 1


def test_archive_member_html_preserves_selected_source_path() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("reports/accounts.xhtml", b"<html><p>Accounts</p></html>")
    package = _document(output.getvalue(), "application/zip")
    member = package.members[0]
    assert member.html() == "<html><p>Accounts</p></html>"
    assert member.source_location.endswith("::reports/accounts.xhtml")
    assert package._provider.calls == 1
    with pytest.raises(UnsupportedCapabilityError, match="HTML/XHTML"):
        package.html()


def test_html_encoding_is_explicit_and_formats_are_checked() -> None:
    document = _document(b"<p>Caf\xe9</p>")
    with pytest.raises(ParseError, match="pass encoding="):
        document.html()
    assert document.html(encoding="cp1252") == "<p>Café</p>"
    with pytest.raises(UnsupportedCapabilityError, match="HTML/XHTML"):
        _document(b"%PDF", "application/pdf").html()
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("facts.xml", b"<xbrl/>")
    member = _document(output.getvalue(), "application/zip").members[0]
    with pytest.raises(UnsupportedCapabilityError, match="HTML/XHTML"):
        member.html()


def test_html_uses_format_discovered_on_download() -> None:
    class DynamicProvider(HtmlProvider):
        def download_document(self, document: FilingDocument) -> bytes:
            document.media_type = "application/xhtml+xml"
            return super().download_document(document)

    document = _document(b"<html>Resolved XHTML</html>", "application/pdf")
    document._provider = DynamicProvider(b"<html>Resolved XHTML</html>")
    document.provider_metadata = {"format_discovered_on_download": True}
    assert document.html() == "<html>Resolved XHTML</html>"
    assert document.media_type == "application/xhtml+xml"


def test_html_line_offsets_match_source_prefixes_for_table_headings() -> None:
    html = "<p>Contents</p><p>Item 1. Business</p><table><tr><td>Item 1.</td><td>Business</td></tr></table><p>Prose.</p>"
    offsets = [html.index("<tr>"), html.index("<p>Prose")]
    expected = [len(html_to_text(html[:offset].encode()).splitlines()) for offset in offsets]
    assert html_to_text_line_offsets(html, offsets) == expected
