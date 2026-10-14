"""Offline KNF OAM discovery, source detail and nested package contract."""

from __future__ import annotations

import gzip
from datetime import date
from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest

from opencorpfilings import Company, search_companies
from opencorpfilings.errors import DownloadError
from opencorpfilings.providers import provider_for_market
from opencorpfilings.providers.poland_oam import PolandOAMProvider
from opencorpfilings.transport import HttpTransport


_NAME = "mBank Spółka Akcyjna"
_ID = "87CC574FDDF43ADAC1258DAA00614B3B"
_LAUNCH = "AppForm?readForm&rok=2026&kat=20260226&plik=l45utoed01_Raport.zip"
_SOURCE = "https://moam.knf.gov.pl/mOAM/2026/20260226/l45utoed01_Raport.zip"
_SEARCH = f"""<html><table class='edittable'><tr><th>Emitent</th><th>Data</th><th>Title</th><th>File</th></tr>
<tr><td>{_NAME}</td><td>2026-02-26</td><td><a href='0/{_ID}'>SRR, -</a></td>
<td><a href='{_LAUNCH.replace('&', '&amp;')}'>open</a></td></tr></table></html>""".encode()
_DETAIL = f"""<html><table>
<tr><td><strong>Emitent:</strong></td><td></td><td>{_NAME}</td></tr>
<tr><td><strong>Nazwa raportu:</strong></td><td></td><td>SRR</td></tr>
<tr><td><strong>Data odebrania:</strong></td><td></td><td>02/26/2026 06:03:37 PM</td></tr>
<tr><td><strong>Rok:</strong></td><td></td><td>2025</td></tr>
<tr><td><strong>Korekta:</strong></td><td></td><td>Nie</td></tr>
<tr><td><strong>Plik raportu:</strong></td><td></td><td><a href='{_LAUNCH.replace('&', '&amp;')}'>source ZIP</a></td></tr>
</table></html>""".encode()
_JNLP = f"<jnlp><application-desc><argument>-reportPath</argument><argument>{_SOURCE}</argument></application-desc></jnlp>".encode()


def _zip(name: str, content: bytes) -> bytes:
    result = BytesIO()
    with ZipFile(result, "w") as archive:
        archive.writestr(name, content)
    return result.getvalue()


class PolandTransport:
    def __init__(self) -> None:
        report = b'''<html xmlns="http://www.w3.org/1999/xhtml"
 xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:ex="https://example.test/taxonomy"><body>
 <ix:header><ix:resources><xbrli:context id="c1"><xbrli:entity>
 <xbrli:identifier scheme="test">mBank</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
 </xbrli:context></ix:resources></ix:header>
 <p>mBank annual report <ix:nonNumeric name="ex:Note" contextRef="c1">Source fact</ix:nonNumeric></p>
 </body></html>'''
        esef = _zip("esef/reports/annual.xhtml", report)
        form = _zip("Attachment/annual.zip", gzip.compress(esef))
        self.source = _zip("SRR_2025.rap", form)

    def get(self, url: str, *, params: dict | None = None, **_: object) -> bytes:
        if url.endswith("/search"):
            assert params and params["Value"] == _NAME
            return _SEARCH if params["start"] == 1 else b"<html>Nie znaleziono dokument</html>"
        if url.endswith("/0/" + _ID):
            return _DETAIL
        if "/AppForm?" in url:
            return _JNLP
        if url == _SOURCE:
            return self.source
        raise AssertionError(url)

    def get_to_file(self, url, path, *, expected_prefix=None):
        content = self.get(url)
        assert expected_prefix is None or content.startswith(expected_prefix)
        path.write_bytes(content)
        return path


def test_poland_oam_annual_report_and_original_nested_esef() -> None:
    assert isinstance(provider_for_market("PL", source="oam"), PolandOAMProvider)
    company = Company(_NAME, market="PL", provider=PolandOAMProvider(transport=PolandTransport()))
    assert company.entity.entity_id == _NAME
    filing = company.filings(form="annual", include_amendments=False, limit=1).latest()
    assert filing.filing_id == _ID
    assert filing.filing_type_raw == "SRR"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.filing_date == date(2026, 2, 26)
    assert filing.period_end is None
    assert filing.amendment is False
    assert filing.provider_metadata["Rok"] == "2025"
    document = filing.primary_document
    assert document.source_url == _SOURCE
    assert document.download().startswith(b"PK")
    report = document.members[0].members[0].members[0]
    assert report.source_location.endswith(
        "::SRR_2025.rap::Attachment/annual.zip::esef/reports/annual.xhtml"
    )
    assert "mBank annual report" in filing.text()
    facts = filing.facts
    assert len(facts) == 1
    assert facts[0].concept_raw == "ex:Note"
    assert facts[0].period_end == date(2025, 12, 31)
    assert "::SRR_2025.rap::Attachment/annual.zip::esef/reports/annual.xhtml#ix-fact-" in facts[0].source_location


def test_poland_streams_selected_original_and_reads_saved_archive(tmp_path):
    fixture = PolandTransport()
    provider = PolandOAMProvider(transport=fixture)
    filing = Company(_NAME, market="PL", provider=provider).filings(form="annual", limit=1).latest()
    document = filing.primary_document
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=fixture.source)

    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    target = tmp_path / "report.zip"
    assert document.download(target) == target
    assert target.read_bytes() == fixture.source
    assert document._cached_bytes is None
    assert "mBank annual report" in filing.text()
    assert document._cached_bytes is None
    assert len(requests) == 1


def test_poland_saved_nested_report_facts_do_not_cache_member(tmp_path, monkeypatch) -> None:
    from opencorpfilings import models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    filing = Company(_NAME, market="PL", provider=PolandOAMProvider(
        transport=PolandTransport(),
    )).filings(form="annual", limit=1).latest()
    package = filing.primary_document
    package.download(tmp_path / "report.zip")
    report = package.members[0].members[0].members[0]

    assert [fact.concept_raw for fact in filing.facts] == ["ex:Note"]
    assert package._cached_bytes is None
    assert report._cached_bytes is None


def test_poland_streamed_error_keeps_existing_target(tmp_path):
    provider = PolandOAMProvider(transport=PolandTransport())
    document = Company(_NAME, market="PL", provider=provider).filings(form="annual", limit=1).latest().primary_document
    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"<html>source unavailable</html>"),
    )))
    target = tmp_path / "report.zip"
    target.write_bytes(b"existing")
    with pytest.raises(DownloadError, match="attachment|report|ZIP"):
        document.download(target)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


def test_poland_issuer_search_returns_source_candidate() -> None:
    class SearchTransport(PolandTransport):
        def get(self, url: str, *, params: dict | None = None, **kwargs: object) -> bytes:
            if url.endswith("/search"):
                assert params and params["Value"] == "mBank"
                return _SEARCH if params["start"] == 1 else b"<html>Nie znaleziono dokument</html>"
            return super().get(url, params=params, **kwargs)

    entities = search_companies("mBank", market="PL", limit=10,
                                provider=PolandOAMProvider(transport=SearchTransport()))
    assert len(entities) == 1
    assert entities[0].name == _NAME
    assert entities[0].entity_id == _NAME
    assert entities[0].provenance.source_url == entities[0].source_url
    assert entities[0].source_url.startswith("https://moam.knf.gov.pl/moam.nsf/search?")


def test_poland_issuer_search_reads_one_page_with_explicit_scope() -> None:
    row = b"<tr><td>" + _SEARCH.split(b"<tr><td>")[1].split(b"</tr>")[0] + b"</tr>"
    full_page = b"<html><table class='edittable'>" + row * 20 + b"</table></html>"

    class FullPageTransport(PolandTransport):
        calls = 0

        def get(self, url: str, *, params: dict | None = None, **kwargs: object) -> bytes:
            if url.endswith("/search"):
                self.calls += 1
                return full_page
            return super().get(url, params=params, **kwargs)

    transport = FullPageTransport()
    candidates = search_companies("mBank", market="PL", limit=2,
                                  provider=PolandOAMProvider(transport=transport, max_pages=1))
    assert len(candidates) == 1
    assert candidates[0].provider_metadata["search_page_scope"] == "first_page"
    assert transport.calls == 1


def test_poland_issuer_search_does_not_claim_completeness_after_short_page() -> None:
    row = b"<tr><td>" + _SEARCH.split(b"<tr><td>")[1].split(b"</tr>")[0] + b"</tr>"
    short_page = b"<table class='edittable'>" + row * 19 + b"</table>"
    other_page = _SEARCH.replace(_NAME.encode(), b"Other Issuer")

    class ShortPageTransport(PolandTransport):
        calls = 0

        def get(self, url: str, *, params: dict | None = None, **kwargs: object) -> bytes:
            if url.endswith("/search"):
                self.calls += 1
                return {1: short_page, 21: other_page}.get(params["start"], b"Nie znaleziono dokument")
            return super().get(url, params=params, **kwargs)

    transport = ShortPageTransport()
    candidates = search_companies(
        "Issuer", market="PL", limit=2,
        provider=PolandOAMProvider(transport=transport, max_pages=3),
    )
    assert [entity.name for entity in candidates] == [_NAME]
    assert candidates[0].provider_metadata["search_page_scope"] == "first_page"
    assert transport.calls == 1


def test_poland_annual_listing_continues_after_short_source_page() -> None:
    row = b"<tr><td>" + _SEARCH.replace(b"SRR, -", b"ESPI, -").split(b"<tr><td>")[1].split(b"</tr>")[0] + b"</tr>"
    short_page = b"<table class='edittable'>" + row * 19 + b"</table>"

    class ShortPageTransport(PolandTransport):
        def get(self, url: str, *, params: dict | None = None, **kwargs: object) -> bytes:
            if url.endswith("/search"):
                return {1: short_page, 21: _SEARCH}.get(params["start"], b"Nie znaleziono dokument")
            return super().get(url, params=params, **kwargs)

    filing = Company(_NAME, market="PL", provider=PolandOAMProvider(
        transport=ShortPageTransport(), max_pages=3,
    )).filings(form="annual", limit=1).latest()
    assert filing.filing_id == _ID
