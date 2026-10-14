import io
import zipfile
import gzip

import pytest

from opencorpfilings import DownloadError, FilingDocument, ParseError, Provenance, UnsupportedCapabilityError
from opencorpfilings.models import MAX_ARCHIVE_MEMBER_BYTES


def archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        package.writestr("PublicDoc/report.xhtml", b"<html/>")
        package.writestr("XBRL/facts.xbrl", b"<xbrl/>")
    return output.getvalue()


class Provider:
    def __init__(self):
        self.calls = 0

    def download_document(self, document):
        self.calls += 1
        return archive()


def document(provider, media_type="application/zip"):
    url = "https://example.test/original.zip"
    return FilingDocument("f1:original", "f1", "original.zip", url,
                          Provenance("fixture", "Registry", "JP", url, "f1:original"),
                          media_type=media_type, _provider=provider)


def test_one_archive_member_keeps_package_and_entry_provenance(tmp_path):
    provider = Provider()
    package = document(provider)
    members = package.members
    assert [member.entry_path for member in members] == ["PublicDoc/report.xhtml", "XBRL/facts.xbrl"]
    assert members[0].source_url == package.source_url
    assert members[0].provenance.source_id == "f1:original::PublicDoc/report.xhtml"
    assert members[0].source_location.endswith("::PublicDoc/report.xhtml")
    assert members[0].download() == b"<html/>"
    assert members[1].download(tmp_path / "facts.xbrl").read_bytes() == b"<xbrl/>"
    assert provider.calls == 1
    members.clear()
    assert [member.entry_path for member in package.members] == ["PublicDoc/report.xhtml", "XBRL/facts.xbrl"]
    assert provider.calls == 1


def test_large_archive_member_text_streams_without_caching_member_bytes():
    report = b"<p>Visible annual report</p><!--" + b"x" * 16_000_000 + b"-->"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package_bytes:
        package_bytes.writestr("reports/annual.xhtml", report)

    class LargeProvider:
        def download_document(self, _):
            return output.getvalue()

    member = document(LargeProvider()).members[0]
    assert member.text() == "Visible annual report"
    assert member._cached_bytes is None
    assert member.source_location.endswith("::reports/annual.xhtml")


def test_large_archive_member_html_does_not_retain_member_bytes(monkeypatch):
    from opencorpfilings import models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package_bytes:
        package_bytes.writestr("reports/annual.xhtml", b"<html>\r\nOriginal annual report\r\n</html>")

    class HtmlProvider:
        def download_document(self, _):
            return output.getvalue()

    member = document(HtmlProvider()).members[0]
    assert member.html() == "<html>\r\nOriginal annual report\r\n</html>"
    assert member._cached_bytes is None


def test_cached_member_cannot_be_relabelled_with_another_source_or_entry(tmp_path):
    package = document(Provider())
    member = package.members[0]
    assert member.download() == b"<html/>"
    member.source_url = "https://example.test/other.zip"
    target = tmp_path / "wrong-source.xhtml"
    with pytest.raises(DownloadError, match="source URL changed"):
        member.download(target)
    with pytest.raises(DownloadError, match="source URL changed"):
        _ = member.source_location
    assert not target.exists()

    member.source_url = package.source_url
    member.entry_path = "XBRL/facts.xbrl"
    with pytest.raises(DownloadError, match="entry path changed"):
        member.download()


def test_cached_member_checks_parent_source_before_returning_tables():
    package = document(Provider())
    member = package.members[0]
    assert member.tables() == []
    package.source_url = "https://example.test/other.zip"
    with pytest.raises(DownloadError, match="source URL changed"):
        member.tables()


def test_cached_nested_member_checks_each_parent_source():
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as inner:
        inner.writestr("report.xhtml", b"<html>annual</html>")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as package_bytes:
        package_bytes.writestr("nested.zip", nested.getvalue())

    class NestedProvider:
        def download_document(self, _):
            return outer.getvalue()

    package = document(NestedProvider())
    parent = package.members[0]
    child = parent.members[0]
    assert child.download() == b"<html>annual</html>"
    parent.source_url = "https://example.test/other.zip"
    with pytest.raises(DownloadError, match="source URL changed"):
        child.download()
    with pytest.raises(DownloadError, match="source URL changed"):
        _ = child.filename


def test_streamed_zip_member_uses_verified_saved_file_without_buffering_package(tmp_path):
    class StreamingProvider(Provider):
        def __init__(self):
            super().__init__()
            self.save_calls = 0

        def supports(self, capability):
            return capability == "streamed_download"

        def save_document(self, _document, path):
            self.save_calls += 1
            path.write_bytes(archive())
            return path

    provider = StreamingProvider()
    package = document(provider)
    saved = package.download(tmp_path / "original.zip")
    assert package._cached_bytes is None
    assert package.members[0].download() == b"<html/>"
    assert package._cached_bytes is None
    assert provider.save_calls == 1
    assert provider.calls == 0

    saved.write_bytes(b"changed source")
    assert package.members[1].download() == b"<xbrl/>"
    assert package._cached_bytes is None
    assert provider.save_calls == 2


def test_archive_members_require_a_zip_representation():
    with pytest.raises(UnsupportedCapabilityError, match="ZIP"):
        _ = document(Provider(), media_type="application/pdf").members


def test_nested_zip_and_gzip_wrapped_zip_keep_original_bytes_and_path_chain():
    report = io.BytesIO()
    with zipfile.ZipFile(report, "w") as archive:
        archive.writestr("reports/annual.xhtml", b"<html>annual</html>")
    wrapped = gzip.compress(report.getvalue())
    form = io.BytesIO()
    with zipfile.ZipFile(form, "w") as archive:
        archive.writestr("Attachment/esef.zip", wrapped)
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("SRR_2025.rap", form.getvalue())

    class NestedProvider:
        def download_document(self, _):
            return outer.getvalue()

    source = document(NestedProvider())
    form_member = source.members[0]
    wrapped_member = form_member.members[0]
    assert wrapped_member.download() == wrapped
    report_member = wrapped_member.members[0]
    assert report_member.download() == b"<html>annual</html>"
    assert report_member.source_location.endswith(
        "::SRR_2025.rap::Attachment/esef.zip::reports/annual.xhtml"
    )
    assert report_member.provenance.source_id.endswith(
        "::SRR_2025.rap::Attachment/esef.zip::reports/annual.xhtml"
    )
    wrapped_member.members.clear()
    assert wrapped_member.members == [report_member]


def test_member_extraction_has_a_bounded_default_and_explicit_override():
    payload = b"x" * 64
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("reports/large.xhtml", payload)

    class LargeProvider:
        def download_document(self, _):
            return output.getvalue()

    member = document(LargeProvider()).members[0]
    with pytest.raises(ParseError, match="32 byte"):
        member.download(max_bytes=32)
    assert member.download(max_bytes=64) == payload
    with pytest.raises(ParseError, match="32 byte"):
        member.download(max_bytes=32)
    with pytest.raises(ValueError, match="positive"):
        member.download(max_bytes=0)
    member.size = MAX_ARCHIVE_MEMBER_BYTES + 1
    with pytest.raises(ParseError, match="100000000 byte"):
        member.download()
    assert member.download(max_bytes=None) == payload


def test_member_path_save_streams_without_caching_and_replaces_atomically(tmp_path):
    payload = b"original member" * 100_000
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("report.xhtml", payload)

    class ReportProvider:
        def download_document(self, _):
            return output.getvalue()

    member = document(ReportProvider()).members[0]
    target = tmp_path / "report.xhtml"
    target.write_bytes(b"old file")
    assert member.download(target) == target
    assert target.read_bytes() == payload
    assert member._cached_bytes is None


def test_member_path_save_preserves_existing_file_on_crc_failure(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr("report.xhtml", b"original")
    corrupted = output.getvalue().replace(b"original", b"corrupt!", 1)

    class CorruptProvider:
        def download_document(self, _):
            return corrupted

    member = document(CorruptProvider()).members[0]
    target = tmp_path / "report.xhtml"
    target.write_bytes(b"old file")
    with pytest.raises(ParseError, match="could not read ZIP member"):
        member.download(target)
    assert target.read_bytes() == b"old file"
    assert list(tmp_path.iterdir()) == [target]


def test_member_path_save_checks_extracted_size_before_replacing_target(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("report.xhtml", b"long content" * 1_000)

    class ReportProvider:
        def download_document(self, _):
            return output.getvalue()

    member = document(ReportProvider()).members[0]
    member.size = 1  # Exercise the read bound even if reported metadata is wrong.
    target = tmp_path / "report.xhtml"
    target.write_bytes(b"old file")
    with pytest.raises(ParseError, match="100 byte extraction limit"):
        member.download(target, max_bytes=100)
    assert target.read_bytes() == b"old file"
    assert list(tmp_path.iterdir()) == [target]
