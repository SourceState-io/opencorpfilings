"""Source-linked HTML table structure without accounting interpretation."""

from io import BytesIO
from zipfile import ZipFile

import pytest

from opencorpfilings import (
    Filing, FilingDocument, ParseError, Provenance, UnsupportedCapabilityError,
)


HTML = b"""<html><body><table><caption>Revenue &amp; costs</caption>
<tr><th rowspan="2">Year</th><th colspan="2">Revenue</th></tr>
<tr><td><ix:nonFraction>1,234</ix:nonFraction></td><td>2<span>.5</span></td></tr>
<tr><td>Note <table><tr><td>Nested</td></tr></table> after</td></tr>
</table><script><table><tr><td>Hidden</td></tr></table></script></body></html>"""


class TableProvider:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    def download_document(self, _document: FilingDocument) -> bytes:
        self.calls += 1
        return self.content


def _document(content: bytes, *, media_type: str = "application/xhtml+xml") -> FilingDocument:
    provider = TableProvider(content)
    url = "https://example.test/report.xhtml"
    return FilingDocument(
        "doc-1", "filing-1", "report.xhtml", url,
        Provenance("fixture", "Registry", "UK", url, "doc-1"),
        media_type=media_type, is_primary=True, _provider=provider,
    )


def test_html_tables_keep_raw_rows_spans_nesting_and_provenance() -> None:
    document = _document(HTML)
    first, nested = document.tables()
    assert first.index == 1
    assert first.caption == "Revenue & costs"
    assert [[cell.text for cell in row] for row in first.rows] == [
        ["Year", "Revenue"], ["1,234", "2.5"], ["Note after"],
    ]
    assert first.rows[0][0].tag == "th"
    assert first.rows[0][0].rowspan == "2"
    assert first.rows[0][1].colspan == "2"
    assert first.source_url == document.source_url
    assert first.source_location == f"{document.source_url}#table=1"
    assert first.provenance.source_id == "doc-1:table:1"
    assert first.provenance.raw["parent_source_id"] == "doc-1"
    assert nested.index == 2
    assert nested.rows[0][0].text == "Nested"
    tables = document.tables()
    tables.clear()
    assert len(document.tables()) == 2
    assert document._provider.calls == 1


def test_archive_member_tables_keep_full_nested_source_path() -> None:
    nested = BytesIO()
    with ZipFile(nested, "w") as archive:
        archive.writestr("reports/accounts.xhtml", HTML)
    outer = BytesIO()
    with ZipFile(outer, "w") as archive:
        archive.writestr("original/esef.zip", nested.getvalue())
    package = _document(outer.getvalue(), media_type="application/zip")
    report = package.members[0].members[0]
    table = report.tables()[0]
    assert table.source_location == f"{report.source_location}#table=1"
    assert table.provenance.source_id == f"{report.provenance.source_id}:table:1"
    assert table.provenance.raw["parent_source_id"] == report.provenance.source_id
    assert table.rows[1][0].text == "1,234"
    assert package._provider.calls == 1
    with pytest.raises(UnsupportedCapabilityError, match="HTML/XHTML"):
        package.members[0].tables()


def test_filing_tables_delegate_to_primary_html_and_reject_unsupported_formats() -> None:
    document = _document(HTML)
    filing = Filing(
        "filing-1", "issuer-1", "UK", "fixture", "Registry",
        "https://example.test/filing", Provenance("fixture", "Registry", "UK", "https://example.test/filing", "filing-1"),
        _documents=[document], _provider=document._provider,
    )
    assert filing.tables()[0].caption == "Revenue & costs"
    assert _document(b"<div>Positioned account</div>").tables() == []
    with pytest.raises(UnsupportedCapabilityError, match="HTML/XHTML"):
        _document(b"%PDF", media_type="application/pdf").tables()
    with pytest.raises(UnsupportedCapabilityError, match="HTML/XHTML"):
        _document(b"<xml/>", media_type="application/zip").tables()


def test_html_table_source_is_bounded_before_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("opencorpfilings.html_tables.MAX_ARCHIVE_MEMBER_BYTES", 10)
    with pytest.raises(ParseError, match="inspection limit"):
        _document(HTML).tables()


def test_html_tables_preserve_declared_legacy_charset_text() -> None:
    korean = '<meta charset="euc-kr"><table><tr><td>매출액</td></tr></table>'.encode("euc-kr")
    assert _document(korean, media_type="text/html").tables()[0].rows[0][0].text == "매출액"

    japanese = ('<?xml version="1.0" encoding="Shift_JIS"?>'
                '<html><table><tr><td>売上高</td></tr></table></html>').encode("shift_jis")
    assert _document(japanese).tables()[0].rows[0][0].text == "売上高"
    utf8_bom = b"\xef\xbb\xbf" + "<table><tr><td>売上高</td></tr></table>".encode("utf-8")
    assert _document(utf8_bom).tables()[0].rows[0][0].text == "売上高"


def test_html_tables_allow_explicit_encoding_for_unlabelled_source_and_cache_separately() -> None:
    korean = "<table><tr><td>매출액</td></tr></table>".encode("cp949")
    document = _document(korean, media_type="text/html")
    with pytest.raises(ParseError, match="encoding"):
        document.tables()
    assert document.tables(encoding="cp949")[0].rows[0][0].text == "매출액"
    assert document.tables(encoding="cp949")[0].rows[0][0].text == "매출액"
    assert document._provider.calls == 1
    filing = Filing(
        "filing-1", "issuer-1", "UK", "fixture", "Registry",
        "https://example.test/filing", Provenance("fixture", "Registry", "UK", "https://example.test/filing", "filing-1"),
        _documents=[document], _provider=document._provider,
    )
    assert filing.tables(encoding="cp949")[0].rows[0][0].text == "매출액"

    archive = BytesIO()
    with ZipFile(archive, "w") as package:
        package.writestr("report.htm", korean)
    member = _document(archive.getvalue(), media_type="application/zip").members[0]
    assert member.tables(encoding="cp949")[0].rows[0][0].text == "매출액"


def test_saved_html_tables_keep_source_structure_without_byte_cache(tmp_path) -> None:
    class StreamedProvider:
        def supports(self, capability: str) -> bool:
            return capability == "streamed_download"

        def save_document(self, _document: FilingDocument, path):
            path.write_bytes(HTML)
            return path

        def download_document(self, _document: FilingDocument) -> bytes:
            raise AssertionError("saved source must not be downloaded again")

    report = _document(HTML)
    report._provider = StreamedProvider()
    report.download(tmp_path / "report.xhtml")
    first, nested = report.tables()
    assert (first.caption, nested.rows[0][0].text) == ("Revenue & costs", "Nested")
    assert first.source_location == f"{report.source_url}#table=1"
    assert report._cached_bytes is None


def test_large_member_tables_keep_source_structure_without_byte_cache(monkeypatch) -> None:
    from opencorpfilings import models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    archive = BytesIO()
    with ZipFile(archive, "w") as package:
        package.writestr("report.xhtml", HTML)
    report = _document(archive.getvalue(), media_type="application/zip").members[0]
    first, nested = report.tables()
    assert (first.caption, nested.rows[0][0].text) == ("Revenue & costs", "Nested")
    assert first.source_location == f"{report.source_location}#table=1"
    assert report._cached_bytes is None


def test_file_backed_tables_match_bytes_across_decoder_chunk_and_declared_charset(tmp_path) -> None:
    from opencorpfilings.html_tables import extract_html_tables

    prefix = b"<table><tr><td>"
    body = prefix + b"x" * (1_000_000 - len(prefix) - 1) + "é".encode("utf-8") + b"</td></tr></table>"
    source = tmp_path / "chunked.html"
    source.write_bytes(body)
    provenance = _document(body).provenance
    streamed = extract_html_tables(source, provenance=provenance, source_location=provenance.source_url)
    buffered = extract_html_tables(body, provenance=provenance, source_location=provenance.source_url)
    assert streamed == buffered
    assert streamed[0].rows[0][0].text.endswith("é")

    legacy = '<meta charset="cp949"><table><tr><td>매출액</td></tr></table>'.encode("cp949")
    source.write_bytes(legacy)
    assert extract_html_tables(source, provenance=provenance, source_location=provenance.source_url) == (
        extract_html_tables(legacy, provenance=provenance, source_location=provenance.source_url)
    )


def test_file_backed_tables_keep_inspection_limit(tmp_path, monkeypatch) -> None:
    from opencorpfilings import html_tables

    source = tmp_path / "too-large.html"
    source.write_bytes(HTML)
    monkeypatch.setattr(html_tables, "MAX_ARCHIVE_MEMBER_BYTES", 10)
    with pytest.raises(ParseError, match="inspection limit"):
        html_tables.extract_html_tables(source, provenance=_document(HTML).provenance,
                                        source_location="https://example.test/report.xhtml")
