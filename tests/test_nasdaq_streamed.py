"""One Nasdaq OAM attachment can save without buffering its original bytes."""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest

from opencorpfilings import DownloadError, FilingDocument, Provenance
from opencorpfilings.providers.finland_oam import FinlandOAMProvider
from opencorpfilings.transport import HttpTransport


def _zip() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("report.xhtml", "<html><body>Annual report</body></html>")
    return buffer.getvalue()


def _document(provider_type, body: bytes, media_type: str) -> FilingDocument:
    provider = provider_type(transport=HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=body),
    ))))
    url = "https://oam.fi/viewAttachment.action?messageAttachmentId=123"
    return FilingDocument(
        document_id="123", filing_id="456", filename="report.zip" if media_type == "application/zip" else "report.pdf",
        source_url=url, provenance=Provenance(provider.name, provider.regulator, provider.market, url, "123"),
        media_type=media_type, _provider=provider,
    )


@pytest.mark.parametrize("provider_type", [FinlandOAMProvider])
def test_nasdaq_zip_streams_and_keeps_members_on_disk(tmp_path: Path, provider_type) -> None:
    body = _zip()
    document = _document(provider_type, body, "application/zip")
    target = tmp_path / "original.zip"
    assert document.download(target) == target
    assert target.read_bytes() == body
    assert document._cached_bytes is None
    assert [member.entry_path for member in document.members] == ["report.xhtml"]
    assert "Annual report" in document.text()
    assert document._cached_bytes is None


@pytest.mark.parametrize("provider_type", [FinlandOAMProvider])
def test_nasdaq_pdf_streams_and_reads_page_from_disk(tmp_path: Path, provider_type) -> None:
    body = (Path(__file__).parent / "fixtures" / "two_page_report.pdf").read_bytes()
    document = _document(provider_type, body, "application/pdf")
    target = tmp_path / "original.pdf"
    assert document.download(target) == target
    assert "Cash flow" in document.page(2).text
    assert document._cached_bytes is None


@pytest.mark.parametrize("provider_type", [FinlandOAMProvider])
@pytest.mark.parametrize("media_type,body", [
    ("application/zip", b"PK\x03\x04broken"),
    ("application/pdf", b"<html>temporary source error</html>"),
])
def test_nasdaq_rejects_invalid_original_without_replacing_target(
    tmp_path: Path, provider_type, media_type: str, body: bytes,
) -> None:
    document = _document(provider_type, body, media_type)
    target = tmp_path / "original"
    target.write_bytes(b"existing")
    with pytest.raises(DownloadError):
        document.download(target)
    assert target.read_bytes() == b"existing"
    assert document._cached_bytes is None
    assert list(tmp_path.iterdir()) == [target]
