"""AFM financial-reporting register source records and original files."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from zipfile import ZipFile

import pytest

from opencorpfilings import Company, EntityNotFoundError, FilingNotFoundError, ProviderError, UnsupportedCapabilityError, search_companies
from opencorpfilings.providers import provider_for_market
from opencorpfilings.providers.netherlands_oam import NetherlandsOAMProvider


_XML = b"""<register name="financiele-verslaggeving">
<vermelding><id>A2510-03564</id><datum>2/25/2026 11:11:34 AM</datum>
<uitgevende-instelling>ASML Holding N.V.</uitgevende-instelling><boekjaar>2025</boekjaar>
<filename>asml-2025-12-31-1-en-A2510-03564.xbri</filename>
<objecttype>Jaarlijkse financi\xeble verslaggeving</objecttype>
<objecttype_eng>Annual financial report</objecttype_eng></vermelding>
<vermelding><id>A2510-03845</id><datum>7/15/2026 9:19:28 AM</datum>
<uitgevende-instelling>ASML Holding N.V.</uitgevende-instelling><boekjaar>2026</boekjaar>
<filename>Statutory Interim Report 2026-A2510-03845.pdf</filename>
<objecttype>Halfjaarlijkse financi\xeble verslaggeving</objecttype>
<objecttype_eng>Half-yearly financial report</objecttype_eng></vermelding>
<vermelding><id>A9999-00001</id><datum>1/1/2026 1:00:00 PM</datum>
<uitgevende-instelling>ASML Finance B.V.</uitgevende-instelling><boekjaar>2025</boekjaar>
<filename>finance.pdf</filename><objecttype>Jaarlijkse verslaggeving</objecttype>
<objecttype_eng>Annual financial report</objecttype_eng></vermelding>
</register>"""
_DETAIL = b"""<div class="cc-em--detail-list__item">
<span class="cc-em--detail-list__label">Filing date</span>
<span class="cc-em--detail-list__value">25 feb 2026</span></div>
<div class="cc-em--detail-list__item"><span class="cc-em--detail-list__label">Issuing institution</span>
<span class="cc-em--detail-list__value">ASML Holding N.V.</span></div>
<div class="cc-em--detail-list__item"><span class="cc-em--detail-list__label">Reporting year</span>
<span class="cc-em--detail-list__value">2025</span></div>
<table class="cc-table-wrap-text"><tr><th>Type of document</th><th>Document</th></tr>
<tr><td>Jaarlijkse verslaggeving</td><td>
<a href="/downloadregisterfile.aspx?type=financiele-verslaggeving&amp;enc=opaque+token%2Fvalue">
asml-2025-12-31-1-en-a2510-03564.xbri</a></td></tr></table>"""


class AFMTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict | None]] = []
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("reports/annual.xhtml", b"<html><body>AFM original report</body></html>")
        self.package = buffer.getvalue()

    def get(self, url: str, *, params: dict | None = None, **_: object) -> bytes:
        self.requests.append((url, params))
        if "export.aspx" in url:
            return _XML
        if "/details" in url:
            return _DETAIL
        if "downloadregisterfile.aspx" in url:
            return self.package
        raise AssertionError(url)

    def get_to_file(self, url: str, path, *, expected_prefix=None):
        content = self.get(url)
        assert expected_prefix is None or content.startswith(expected_prefix)
        path.write_bytes(content)
        return path


def test_afm_issuer_annual_and_original_package(tmp_path) -> None:
    assert isinstance(provider_for_market("NL", source="oam"), NetherlandsOAMProvider)
    transport = AFMTransport()
    company = Company("ASML Holding N.V.", market="NL", provider=NetherlandsOAMProvider(transport=transport))
    assert company.entity.entity_id == "ASML Holding N.V."
    filing = company.filings(form="annual", start="2025-01-01").latest()
    assert filing.filing_id == "A2510-03564"
    assert filing.filing_date == date(2026, 2, 25)
    assert filing.period_end is None
    assert filing.provider_metadata["report_year"] == "2025"
    assert filing.filing_type_raw == "Jaarlijkse financiële verslaggeving"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.source_url.endswith("id=A2510-03564")
    assert len(filing.documents) == 1
    document = filing.primary_document
    assert document.media_type == "application/zip"
    assert document.filename.endswith(".xbri")
    assert document.download().startswith(b"PK\x03\x04")
    assert document.provenance.source_url == document.source_url
    assert document.download(tmp_path / "one.xbri").read_bytes().startswith(b"PK\x03\x04")
    assert any(params and params.get("KeyWords") == "ASML Holding N.V." for _, params in transport.requests)


def test_afm_search_and_interim_are_exact_issuer_scoped() -> None:
    provider = NetherlandsOAMProvider(transport=AFMTransport())
    matches = search_companies("ASML", market="NL", provider=provider)
    assert {entity.entity_id for entity in matches} == {"ASML Holding N.V.", "ASML Finance B.V."}
    company = Company("ASML Holding N.V.", market="NL", provider=provider)
    filing = company.filings(form="interim", limit=1).latest()
    assert filing.filing_id == "A2510-03845"
    assert filing.filing_type_normalized == "INTERIM"
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(form="quarterly").latest()
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(include_amendments=False).latest()
    with pytest.raises(EntityNotFoundError):
        _ = Company("ASML", market="NL", provider=provider).entity


def test_afm_rejects_detail_from_another_issuer() -> None:
    class WrongDetail(AFMTransport):
        def get(self, url: str, *, params: dict | None = None, **kwargs: object) -> bytes:
            if "/details" in url:
                return _DETAIL.replace(b"ASML Holding N.V.", b"Another Issuer N.V.")
            return super().get(url, params=params, **kwargs)

    company = Company("ASML Holding N.V.", market="NL", provider=NetherlandsOAMProvider(transport=WrongDetail()))
    with pytest.raises(ProviderError, match="selected issuer"):
        _ = company.filings(form="annual").latest().documents
    with pytest.raises(FilingNotFoundError, match="selected issuer"):
        company.get_filing("A2510-03564")


def test_afm_known_id_uses_one_direct_detail_and_checks_issuer() -> None:
    transport = AFMTransport()
    company = Company("ASML Holding N.V.", market="NL", provider=NetherlandsOAMProvider(transport=transport))
    _ = company.entity
    transport.requests.clear()

    filing = company.get_filing("A2510-03564", max_scan=1)
    assert filing.filing_id == "A2510-03564"
    assert filing.entity_id == "ASML Holding N.V."
    assert filing.filing_date == date(2026, 2, 25)
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.provider_metadata["report_year"] == "2025"
    assert len(transport.requests) == 1
    assert "/details?id=A2510-03564" in transport.requests[0][0]
    with pytest.raises(FilingNotFoundError):
        company.get_filing("A2510-03564", end="2026-02-24")
