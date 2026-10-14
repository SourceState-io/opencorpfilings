"""The report inside an original package is found by content, at any nesting, never as decoded binary."""

import gzip
import io
import zipfile

import pytest

from opencorpfilings import FilingDocument, ParseError, Provenance, UnsupportedCapabilityError
from opencorpfilings import models
from opencorpfilings.packages import best_reports, report_members

REPORT = b"<?xml version='1.0'?><html xmlns='http://www.w3.org/1999/xhtml'><body><p>Annual report</p></body></html>"


def _zip(entries: dict[str, bytes], compression=zipfile.ZIP_STORED) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as package:
        for name, content in entries.items():
            package.writestr(name, content)
    return output.getvalue()


def _document(content: bytes) -> FilingDocument:
    class Provider:
        def download_document(self, _):
            return content

    url = "https://example.test/original.zip"
    return FilingDocument("f1:original", "f1", "original.zip", url,
                          Provenance("fixture", "Registry", "PL", url, "f1:original"),
                          media_type="application/zip", _provider=Provider())


def test_report_inside_a_nested_esef_package_is_found():
    esef = _zip({"issuer-2025-12-31-en/reports/issuer-2025-12-31-en.xhtml": REPORT,
                 "issuer-2025-12-31-en/META-INF/reportPackage.json": b"{}"})
    document = _document(_zip({"citadele-2025-12-31-en.xbri": esef}))
    found = report_members(document)
    assert [member.entry_path for member in found] == ["issuer-2025-12-31-en/reports/issuer-2025-12-31-en.xhtml"]
    assert "Annual report" in found[0].text()


def test_gzip_wrapped_package_is_opened_and_gzipped_markup_is_decoded_not_garbled():
    # Amica: the ESEF report sits in a gzip-wrapped .xbri; the management report is gzipped XHTML.
    esef = _zip({"amica-2025-12-31-pl/reports/amica-2025-12-31-pl.xhtml": REPORT})
    management = gzip.compress(b"<html><body>Management report</body></html>")
    rap = _zip({"Attachment/x/AMICA SA-2025-12-31-1-pl.xbri": gzip.compress(esef),
                "Attachment/x/Sprawozdanie Zarzadu.xhtml": management})
    document = _document(_zip({"SRR_2025.rap": rap}))
    found = best_reports(document)
    assert [member.entry_path for member in found] == [
        "amica-2025-12-31-pl/reports/amica-2025-12-31-pl.xhtml", "Attachment/x/Sprawozdanie Zarzadu.xhtml"]
    assert found[1].text() == "Management report"
    assert found[1].html() == "<html><body>Management report</body></html>"
    binary = _document(_zip({"blob.xhtml": gzip.compress(bytes(range(256)) * 4)}))
    member = binary.members[0]
    with pytest.raises(UnsupportedCapabilityError, match="not HTML/XHTML"):
        member.text()


def test_reports_folder_and_xhtml_rank_ahead_of_other_markup():
    document = _document(_zip({
        "index.html": b"<html><body>Cover</body></html>",
        "pkg/reports/annual.html": b"<html><body>HTML rendering</body></html>",
        "pkg/reports/annual.xhtml": REPORT,
    }))
    assert [member.entry_path for member in report_members(document)] == [
        "index.html", "pkg/reports/annual.html", "pkg/reports/annual.xhtml"]
    assert [member.entry_path for member in best_reports(document)] == [
        "pkg/reports/annual.xhtml", "pkg/reports/annual.html", "index.html"]


def test_package_without_markup_returns_no_report():
    document = _document(_zip({"comply_or_explain.xlsx": b"PK\x03\x04not-really", "report.pdf": b"%PDF-1.7"}))
    assert report_members(document) == []


def test_text_over_the_in_memory_limit_streams_when_compression_is_plausible(monkeypatch):
    monkeypatch.setattr(models, "MAX_ARCHIVE_MEMBER_BYTES", 2_000)
    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1_000)
    body = b"<html><body>" + b"".join(b"<p>row %d value %d</p>" % (i, i * 7919 % 10007) for i in range(400)) + b"</body></html>"
    document = _document(_zip({"reports/big.xhtml": body}, zipfile.ZIP_DEFLATED))
    member = report_members(document)[0]
    assert member.size > 2_000
    assert "row 399" in member.text()


def test_implausible_compression_over_the_in_memory_limit_is_refused(monkeypatch):
    monkeypatch.setattr(models, "MAX_ARCHIVE_MEMBER_BYTES", 2_000)
    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1_000)
    bomb = b"<html><body>" + b"0" * 2_000_000 + b"</body></html>"
    document = _document(_zip({"reports/bomb.xhtml": bomb}, zipfile.ZIP_DEFLATED))
    with pytest.raises(ParseError, match="compression ratio"):
        report_members(document)[0].text()


def test_large_nested_package_spills_to_disk_instead_of_failing(monkeypatch):
    # Sligro's FY2025 ZIP holds a single 182 MB .xbri; nested packages were capped at 100 MB in memory.
    monkeypatch.setattr(models, "MAX_ARCHIVE_MEMBER_BYTES", 5_000)
    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1_000)
    body = b"<html><body>" + b"".join(b"<p>line %d value %d</p>" % (i, i * 7919 % 10007) for i in range(600)) + b"</body></html>"
    inner = _zip({"sligro-2025-12-31-en/reports/sligro-2025-12-31-en.xhtml": body}, zipfile.ZIP_STORED)
    assert len(inner) > 5_000
    for wrapped in (inner, gzip.compress(inner)):
        document = _document(_zip({"sligro-2025-12-31-en.xbri": wrapped}))
        package = document.members[0]
        found = report_members(document)
        assert [member.entry_path for member in found] == ["sligro-2025-12-31-en/reports/sligro-2025-12-31-en.xhtml"]
        assert package._archive_payload_cache is None and package._archive_payload_path is not None
        assert "line 599" in found[0].text()


def test_gzip_compressed_esef_xhtml_is_a_report_and_outranks_a_larger_management_report():
    # LPP FY2025: KNF gzips every attachment and the ESEF report is a bare XHTML,
    # beside a 4.3 MB management report; neither was found as text.
    management = b"<html><body>" + b"<p>Management report</p>" * 400 + b"</body></html>"
    rap = _zip({"Attachment/x/LPP-2026-01-31-1-pl.xhtml": gzip.compress(REPORT),
                "Attachment/x/LPP-2026-01-31-1-pl.xhtml.XAdES": gzip.compress(b"<signature/>"),
                "Attachment/x/GK_LPP_SzD_2025.xhtml": gzip.compress(management)})
    document = _document(_zip({"RR_2025.rap": rap}))
    found = best_reports(document)
    assert [member.entry_path for member in found] == [
        "Attachment/x/LPP-2026-01-31-1-pl.xhtml", "Attachment/x/GK_LPP_SzD_2025.xhtml"]
    assert "Annual report" in found[0].text()
