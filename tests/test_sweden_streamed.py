"""Single-document streamed saves preserve Finanscentralen's discovered format."""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest

from opencorpfilings import DownloadError, Filing, FilingDocument, Provenance, ProviderError, UnsupportedCapabilityError
from opencorpfilings.providers.sweden_oam import SwedenOAMProvider
from opencorpfilings.transport import HttpTransport
from test_ixbrl import XHTML


_URL = "https://finanscentralen.fi.se/search/GetFile.aspx?fid=57991"


def _package() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("report.xhtml", "<html><body>Original annual report</body></html>")
    return buffer.getvalue()


def _document(content: bytes) -> FilingDocument:
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=content),
    )))
    return FilingDocument(
        document_id="57991", filing_id="issuer:annual:2024", filename="Finanscentralen-57991",
        source_url=_URL, provenance=Provenance("sweden_oam", "Finanscentralen", "SE", _URL, "57991"),
        provider_metadata={"format_discovered_on_download": True},
        _provider=SwedenOAMProvider(transport=transport),
    )


@pytest.mark.parametrize("content,media_type,suffix", [
    (_package(), "application/zip", ".zip"),
    (b"%PDF-1.4 fixture", "application/pdf", ".pdf"),
    (b"<html><body>Annual report</body></html>", "application/xhtml+xml", ".xhtml"),
])
def test_sweden_streamed_save_discovers_format_without_buffering(
    tmp_path: Path, content: bytes, media_type: str, suffix: str,
) -> None:
    document = _document(content)
    target = tmp_path / "original"
    assert document.download(target) == target
    assert target.read_bytes() == content
    assert document._cached_bytes is None
    assert document.media_type == media_type
    assert document.filename.endswith(suffix)
    if media_type == "application/zip":
        assert [member.entry_path for member in document.members] == ["report.xhtml"]
    target.write_bytes(b"changed after save")
    assert document.download(target) == target
    assert target.read_bytes() == content
    assert document.filename == f"Finanscentralen-57991{suffix}"
    assert document._cached_bytes is None


@pytest.mark.parametrize("content", [b"PK\x03\x04broken", b"unrecognized original"])
def test_sweden_streamed_save_rejects_invalid_source_without_replacing_target(
    tmp_path: Path, content: bytes,
) -> None:
    document = _document(content)
    target = tmp_path / "original"
    target.write_bytes(b"existing")
    with pytest.raises(DownloadError):
        document.download(target)
    assert target.read_bytes() == b"existing"
    assert document.media_type is None
    assert list(tmp_path.iterdir()) == [target]


def test_sweden_saved_zip_text_and_facts_keep_original_on_disk(tmp_path: Path) -> None:
    document = _document(_package())
    document.download(tmp_path / "original.zip")
    assert "Original annual report" in document.text()
    assert document._cached_bytes is None
    filing = Filing(
        filing_id=document.filing_id, entity_id="issuer", jurisdiction="SE",
        provider="sweden_oam", regulator="Finanscentralen", source_url=_URL,
        provenance=document.provenance, _provider=document._provider, _documents=[document],
    )
    with pytest.raises(UnsupportedCapabilityError, match="no parsed inline facts"):
        filing.facts
    assert document._cached_bytes is None


def test_sweden_saved_zip_facts_do_not_buffer_large_report_member(tmp_path: Path, monkeypatch) -> None:
    from opencorpfilings import models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("report.xhtml", XHTML)
    document = _document(buffer.getvalue())
    document.download(tmp_path / "original.zip")
    member = document.members[0]
    filing = Filing(
        filing_id=document.filing_id, entity_id="issuer", jurisdiction="SE",
        provider="sweden_oam", regulator="Finanscentralen", source_url=_URL,
        provenance=document.provenance, _provider=document._provider, _documents=[document],
    )

    assert [fact.concept_raw for fact in filing.facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]
    assert member._cached_bytes is None
    assert document._cached_bytes is None


def test_sweden_saved_direct_xhtml_facts_do_not_buffer_original(tmp_path: Path) -> None:
    document = _document(XHTML)
    document.download(tmp_path / "original.xhtml")
    filing = Filing(
        filing_id=document.filing_id, entity_id="issuer", jurisdiction="SE",
        provider="sweden_oam", regulator="Finanscentralen", source_url=_URL,
        provenance=document.provenance, _provider=document._provider, _documents=[document],
    )

    assert [fact.concept_raw for fact in filing.facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]
    assert document._cached_bytes is None


@pytest.mark.parametrize("save_to_file", [False, True])
def test_sweden_rejects_source_file_id_that_differs_from_document(
    tmp_path: Path, save_to_file: bool,
) -> None:
    document = _document(_package())
    document.source_url = "https://finanscentralen.fi.se/search/GetFile.aspx?fid=57992"
    with pytest.raises(DownloadError, match="file ID"):
        if save_to_file:
            document._provider.save_document(document, tmp_path / "wrong.zip")
        else:
            document._provider.download_document(document)
    assert not (tmp_path / "wrong.zip").exists()


def test_sweden_rejects_ambiguous_source_file_id() -> None:
    document = _document(_package())
    document.source_url = _URL + "&fid=57992"
    with pytest.raises(ProviderError, match="invalid source file link"):
        document._provider.download_document(document)


@pytest.mark.parametrize("content", [
    b'\xef\xbb\xbf<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>Report</body></html>',
    b"<!doctype html><html><body>Report</body></html>",
    b"<HTML><BODY>Report</BODY></HTML>",
], ids=["bom-xml-declaration", "lowercase-doctype", "uppercase-html"])
@pytest.mark.parametrize("save_to_file", [False, True])
def test_sweden_recognises_markup_after_a_bom_or_in_any_case(tmp_path: Path, content: bytes, save_to_file: bool) -> None:
    document = _document(content)
    if save_to_file:
        assert document.download(tmp_path / "original").read_bytes() == content
    else:
        assert document.download() == content
    assert document.media_type == "application/xhtml+xml"
    assert document.filename.endswith(".xhtml")
