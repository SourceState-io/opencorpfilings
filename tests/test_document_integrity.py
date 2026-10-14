from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
from zipfile import ZipFile

import pytest

from opencorpfilings import DownloadError, FilingDocument, Provenance


class _Provider:
    def __init__(self, body: bytes, *, discovered_type: str | None = None) -> None:
        self.body = body
        self.discovered_type = discovered_type

    def supports(self, _capability: str) -> bool:
        return False

    def download_document(self, document: FilingDocument) -> bytes:
        if self.discovered_type:
            document.media_type = self.discovered_type
        return self.body


def _document(body: bytes, media_type: str | None, *, discovered_type: str | None = None) -> FilingDocument:
    url = "https://example.test/filing/original"
    return FilingDocument(
        document_id="original", filing_id="filing", filename="original",
        source_url=url, provenance=Provenance("fixture", "fixture", "US", url, "original"),
        media_type=media_type, _provider=_Provider(body, discovered_type=discovered_type),
    )


@pytest.mark.parametrize("media_type", ["application/pdf", "application/zip"])
def test_buffered_binary_rejects_html_200_without_replacing_target(tmp_path, media_type) -> None:
    document = _document(b"<html>temporarily unavailable</html>", media_type)
    with pytest.raises(DownloadError, match="source bytes do not match"):
        document.download()
    assert document._cached_bytes is None
    target = tmp_path / "original"
    target.write_bytes(b"prior original")
    with pytest.raises(DownloadError, match="source bytes do not match"):
        document.download(target)
    assert target.read_bytes() == b"prior original"


@pytest.mark.parametrize("media_type", ["text/html", None])
def test_buffered_document_rejects_empty_200_without_caching_or_replacing_target(tmp_path, media_type) -> None:
    document = _document(b"", media_type)
    target = tmp_path / "original"
    target.write_bytes(b"prior original")
    with pytest.raises(DownloadError, match="empty document"):
        document.download(target)
    assert document._cached_bytes is None
    assert target.read_bytes() == b"prior original"
    with pytest.raises(DownloadError, match="empty document"):
        document.download()
    document._cached_bytes = b""
    with pytest.raises(DownloadError, match="empty document"):
        document.download()


def test_buffered_binary_keeps_original_pdf_and_zip_bytes() -> None:
    pdf = (Path(__file__).parent / "fixtures" / "two_page_report.pdf").read_bytes()
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("original.txt", "source bytes")
    for media_type, body in (("application/pdf", pdf), ("application/zip", payload.getvalue())):
        assert _document(body, media_type).download() == body


def test_provider_discovered_xhtml_is_not_rejected_as_listed_pdf() -> None:
    body = b"<html xmlns='http://www.w3.org/1999/xhtml'>Report</html>"
    document = _document(body, "application/pdf", discovered_type="application/xhtml+xml")
    assert document.download() == body
    assert document.media_type == "application/xhtml+xml"


def test_prepopulated_binary_bytes_are_checked_too() -> None:
    document = _document(b"%PDF-1.7", "application/pdf")
    document._cached_bytes = b"<html>error</html>"
    with pytest.raises(DownloadError, match="source bytes do not match"):
        document.download()


def test_buffered_zip_rejects_truncated_archive_before_caching_or_saving(tmp_path) -> None:
    document = _document(b"PK\x03\x04truncated", "application/zip")
    target = tmp_path / "original.zip"
    target.write_bytes(b"existing")
    with pytest.raises(DownloadError, match="invalid ZIP"):
        document.download(target)
    assert document._cached_bytes is None
    assert target.read_bytes() == b"existing"


def test_document_sha256_hashes_original_once_when_buffered() -> None:
    body = b"original source bytes"
    document = _document(body, "text/plain")
    assert document.sha256() == hashlib.sha256(body).hexdigest()
    assert document.sha256() == hashlib.sha256(body).hexdigest()
    assert document._cached_bytes == body


def test_document_sha256_reuses_verified_streamed_save_and_recovers_tampering(tmp_path) -> None:
    body = b"%PDF-1.7\noriginal"

    class StreamedProvider:
        calls = 0

        def supports(self, capability: str) -> bool:
            return capability == "streamed_download"

        def save_document(self, _document: FilingDocument, target: Path) -> Path:
            self.calls += 1
            target.write_bytes(body)
            return target

    provider = StreamedProvider()
    document = _document(body, "application/pdf")
    document._provider = provider
    target = tmp_path / "report.pdf"
    document.download(target)

    expected = hashlib.sha256(body).hexdigest()
    assert document.sha256() == expected
    assert provider.calls == 1
    assert document._cached_bytes is None

    target.write_bytes(b"tampered")
    assert document.sha256() == expected
    assert target.read_bytes() == body
    assert provider.calls == 2


def test_document_sha256_streams_fresh_original_without_retaining_file_or_bytes(tmp_path, monkeypatch) -> None:
    body = b"%PDF-1.7\noriginal"

    class StreamedProvider:
        calls = 0

        def supports(self, capability: str) -> bool:
            return capability == "streamed_download"

        def save_document(self, _document: FilingDocument, target: Path) -> Path:
            self.calls += 1
            target.write_bytes(body)
            return target

        def download_document(self, _document: FilingDocument) -> bytes:
            raise AssertionError("hashing must not buffer a streamed original")

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    provider = StreamedProvider()
    document = _document(body, "application/pdf")
    document._provider = provider

    expected = hashlib.sha256(body).hexdigest()
    assert document.sha256() == expected
    assert document.sha256() == expected
    assert provider.calls == 1
    assert document._cached_bytes is None
    assert document._saved_path is None
    assert list(tmp_path.iterdir()) == []


def test_saved_html_reads_original_without_retaining_byte_cache(tmp_path) -> None:
    body = b"<html>\r\nOriginal annual report\r\n</html>"

    class StreamedProvider:
        def supports(self, capability: str) -> bool:
            return capability == "streamed_download"

        def save_document(self, _document: FilingDocument, target: Path) -> Path:
            target.write_bytes(body)
            return target

        def download_document(self, _document: FilingDocument) -> bytes:
            raise AssertionError("saved HTML must not be downloaded again")

    document = _document(body, "text/html")
    document._provider = StreamedProvider()
    document.download(tmp_path / "original.html")

    assert document.html() == body.decode("utf-8")
    assert document._cached_bytes is None
