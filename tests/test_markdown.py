from __future__ import annotations

import builtins
import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest

from opencorpfilings import Filing, FilingDocument, ParseError, Provenance, UnsupportedCapabilityError


HTML = b'''<?xml version="1.0"?>
<html xmlns:inl="http://www.xbrl.org/2013/inlineXBRL"><head><title>Hidden title</title></head><body>
<inl:header><inl:resources>Secret context</inl:resources></inl:header>
<h1>Annual report</h1><p>Visible <strong>prose</strong>.</p>
<img src="data:image/png;base64,QUJDREVGRw==" alt="Company logo" />
<p style="display:none">Secret style</p>
<table><tr><th>Item</th><th>Value</th></tr><tr><td>Sales</td><td>10</td></tr></table>
<table><tr><td></td></tr></table>
</body></html>'''


class _Provider:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    def download_document(self, _document: FilingDocument) -> bytes:
        self.calls += 1
        return self.content


def _document(content: bytes, media_type: str = "application/xhtml+xml") -> FilingDocument:
    url = "https://example.test/report.xhtml"
    return FilingDocument(
        document_id="report", filing_id="filing", filename="report.xhtml",
        source_url=url, provenance=Provenance("fixture", "fixture", "US", url, "report"),
        media_type=media_type, _provider=_Provider(content),
    )


def test_html_markdown_preserves_visible_structure_and_reuses_download() -> None:
    document = _document(HTML)
    result = document.markdown()
    assert "# Annual report" in result
    assert "Visible **prose**" in result
    assert "| Sales | 10 |" in result
    assert "Hidden title" not in result
    assert "Secret context" not in result
    assert "Secret style" not in result
    assert "Company logo" in result
    assert "base64" not in result
    assert "xml version" not in result
    assert result.count("| --- | --- |") == 1
    assert document.markdown() == result
    assert document._provider.calls == 1
    assert document.download() == HTML
    filing = Filing(
        filing_id="filing", entity_id="issuer", jurisdiction="US", provider="fixture",
        regulator="fixture", source_url=document.source_url, provenance=document.provenance,
        _primary_document=document,
    )
    assert filing.markdown() == result


def test_markdown_cache_respects_explicit_encoding() -> None:
    document = _document(b"<p>caf\xe9</p>")
    assert "caf\u00e9" in document.markdown(encoding="latin-1")
    with pytest.raises(ParseError, match="pass encoding="):
        document.markdown()


def test_missing_optional_markdown_dependency_has_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def without_markdownify(name, *args, **kwargs):
        if name == "markdownify":
            raise ModuleNotFoundError("No module named 'markdownify'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_markdownify)
    with pytest.raises(UnsupportedCapabilityError, match="'markdown' extra"):
        _document(HTML).markdown()


def test_markdown_is_explicitly_unavailable_for_pdf() -> None:
    with pytest.raises(UnsupportedCapabilityError, match="HTML/XHTML"):
        _document(b"%PDF-1.7", "application/pdf").markdown()


def test_html_archive_member_has_the_same_markdown_view() -> None:
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("report.xhtml", HTML)
    package = _document(payload.getvalue(), "application/zip")
    package.filename = "report.zip"
    member = package.members[0]
    assert "# Annual report" in member.markdown()
    assert "Secret context" not in member.markdown()
    assert member.download() == HTML


def test_saved_original_markdown_does_not_fill_original_byte_cache(tmp_path) -> None:
    document = _document(HTML)
    saved = tmp_path / "report.xhtml"
    saved.write_bytes(HTML)
    document._saved_path = saved.resolve()
    document._saved_sha256 = hashlib.sha256(HTML).hexdigest()

    assert "# Annual report" in document.markdown()
    assert document._cached_bytes is None
    assert document._saved_path == saved.resolve()


def test_large_archive_member_markdown_uses_temporary_file(monkeypatch) -> None:
    import opencorpfilings.models as models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("report.xhtml", HTML)
    package = _document(payload.getvalue(), "application/zip")
    member = package.members[0]

    assert "# Annual report" in member.markdown()
    assert member._cached_bytes is None


def test_file_backed_markdown_preserves_encoding_and_output(tmp_path) -> None:
    content = b"<html><body><h1>Rapport</h1>\r\n<p>caf\xe9</p></body></html>"
    document = _document(content)
    saved = tmp_path / "report.xhtml"
    saved.write_bytes(content)
    document._saved_path = saved.resolve()
    document._saved_sha256 = hashlib.sha256(content).hexdigest()

    assert document.markdown(encoding="latin-1") == _document(content).markdown(encoding="latin-1")
    assert "caf\u00e9" in document.markdown(encoding="latin-1")
    with pytest.raises(ParseError, match="pass encoding="):
        document.markdown()
    assert document._cached_bytes is None
