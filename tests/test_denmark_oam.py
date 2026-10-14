"""Danish OAM public search, announcement detail and one original file."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from zipfile import ZipFile

import pytest

from opencorpfilings import Company, EntityNotFoundError, FilingNotFoundError, ProviderError, UnsupportedCapabilityError, search_companies
from opencorpfilings.providers import provider_for_market
from opencorpfilings.providers.denmark_oam import DenmarkOAMProvider


_ROOT = "https://appft.gold.extension.gopublic.dk/api/9217fa13-5d9a-46c6-9921-69ee7e6cfaf6"
_DOC = "https://saesappublicprd.blob.core.windows.net/stc-public-submissions/2026/02/sample/documents/Carlsberg-2025-12-31-en.zip"
_XHTML = b'''<html xmlns="http://www.w3.org/1999/xhtml"
 xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:ex="https://example.test/taxonomy"><body>
 <ix:header><ix:resources><xbrli:context id="c1"><xbrli:entity>
 <xbrli:identifier scheme="test">Carlsberg</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
 </xbrli:context></ix:resources></ix:header>
 <p>Carlsberg annual report <ix:nonNumeric name="ex:Note" contextRef="c1">Original</ix:nonNumeric></p>
 </body></html>'''


def _element(name, value, *, kind="text", title=None):
    return {"type": "keyvalue", "key": {"name": name},
            "value": {"type": kind, "value": value} if kind == "text" else
                     {"type": kind, "title": title, "url": value}}


class DenmarkTransport:
    def __init__(self) -> None:
        self.searches: list[dict] = []
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("reports/annual.xhtml", _XHTML)
        self.package = buffer.getvalue()

    def get_json(self, url: str, **_: object):
        if url == _ROOT + "/config":
            return {"components": {"filters": [{"key": "IssuerFilter", "options": [
                {"id": "DK-61056416", "label": "CARLSBERG A/S"},
                {"id": "DK-25508343", "label": "CARLSBERG BREWERIES A/S"},
                {"id": "DK-22756214", "label": "A.P. MØLLER - MÆRSK A/S"},
                {"id": "DK-12345678", "label": "ØRSTED A/S"},
                {"id": "DK-36213728", "label": "DONG Energy A/S"},
                {"id": "DK-36213728", "label": "Ørsted A/S"},
                {"id": "CH-CHE-474.101.854", "label": "Trifork Holding AG"},
            ]}, {"key": "CategoryFilter", "options": [
                {"id": "ANFIRE", "label": "Annual financial report"},
                {"id": "HYFIRE", "label": "Half year financial report"},
            ]}]}}
        if url == _ROOT + "/details/300003388":
            return {"heading": "Carlsberg A/S 2025 Annual Report", "sections": [
                {"heading": "Notification", "elements": [
                    _element("Announcement ID", "300003388"),
                    _element("Type", "Annual financial report"),
                    _element("Document(s)", _DOC, kind="link", title="Carlsberg-2025-12-31-en.zip (English)"),
                ]},
                {"heading": "Time", "elements": [
                    _element("Published", "04-02-2026 14:55:23"),
                    _element("Registration time", "04-02-2026 14:55:51"),
                ]},
                {"heading": "Issuer", "elements": [
                    _element("Company", "CARLSBERG A/S"),
                    _element("National business ID", "DK-61056416"),
                    _element("LEI code", "5299001O0WJQYB5GYZ19"),
                ]},
            ]}
        raise AssertionError(url)

    def post_json(self, url: str, payload: dict, **_: object):
        assert url == _ROOT + "/search"
        self.searches.append(payload)
        assert payload["pageSize"] == 25
        if payload["page"] > 1:
            return {"paging": {"page": payload["page"], "pageSize": 25,
                                "totalCount": 1, "totalPages": 1},
                    "data": {"type": "table", "rows": []}}
        return {"paging": {"page": 1, "pageSize": 25, "totalCount": 1, "totalPages": 1},
                "data": {"type": "table", "rows": [{
                    "id": "300003388", "HeadlineColumn": "Carlsberg A/S 2025 Annual Report",
                    "IssuerColumn": "CARLSBERG A/S", "CategoryColumn": "Annual financial report",
                    "PublicationDateColumn": "04-02-2026 14:55:23",
                    "RegistrationDateColumn": "04-02-2026 14:55:51",
                    "IsHistoricalColumn": False,
                }]}}

    def get(self, url: str, **_: object) -> bytes:
        assert url == _DOC
        return self.package

    def get_to_file(self, url: str, path, *, expected_prefix=None):
        content = self.get(url)
        assert expected_prefix is None or content.startswith(expected_prefix)
        path.write_bytes(content)
        return path


def test_denmark_annual_issuer_original_zip_and_raw_facts(tmp_path) -> None:
    assert isinstance(provider_for_market("DK", source="oam"), DenmarkOAMProvider)
    transport = DenmarkTransport()
    company = Company("DK-61056416", market="DK", provider=DenmarkOAMProvider(transport=transport))
    assert company.entity.name == "CARLSBERG A/S"
    filing = company.filings(form="annual", start="2026-01-01", limit=1).latest()
    assert filing.filing_id == "300003388"
    assert filing.filing_date == date(2026, 2, 4)
    assert filing.filing_type_raw == "Annual financial report"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.period_end is None
    assert filing.provider_metadata["registration_display"] == "04-02-2026 14:55:51"
    assert filing.source_url.endswith("/details/300003388")
    assert len(filing.documents) == 1
    assert filing.primary_document.source_url == _DOC
    assert "Carlsberg annual report" in filing.text()
    assert filing.facts[0].concept_raw == "ex:Note"
    assert filing.primary_document.download(tmp_path / "one.zip").read_bytes().startswith(b"PK\x03\x04")
    assert transport.searches[0]["filters"] == [
        {"type": "dropdown", "key": "IssuerFilter", "options": ["DK-61056416"]},
        {"type": "dropdown", "key": "CategoryFilter", "options": ["ANFIRE"]},
    ]


def test_denmark_search_exact_name_and_direct_id() -> None:
    provider = DenmarkOAMProvider(transport=DenmarkTransport())
    matches = search_companies("Carlsberg", market="DK", provider=provider)
    assert {item.entity_id for item in matches} == {"DK-61056416", "DK-25508343"}
    assert search_companies("Trifork", market="DK", provider=provider)[0].entity_id == "CH-CHE-474.101.854"
    company = Company("CARLSBERG A/S", market="DK", provider=provider)
    assert company.entity.entity_id == "DK-61056416"


    filing = company.get_filing("300003388", max_scan=1)
    assert filing.filing_id == "300003388"
    assert filing.documents[0].source_url == _DOC
    with pytest.raises(FilingNotFoundError):
        company.get_filing("300003388", start="2026-02-05")
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(form="quarterly").latest()
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(form="annual", include_amendments=False).latest()
    with pytest.raises(EntityNotFoundError):
        _ = Company("Carlsberg", market="DK", provider=provider).entity


def test_denmark_name_search_accepts_ascii_danish_spelling() -> None:
    provider = DenmarkOAMProvider(transport=DenmarkTransport())
    maersk = search_companies("Maersk", market="DK", provider=provider)
    assert [(entity.entity_id, entity.name) for entity in maersk] == [
        ("DK-22756214", "A.P. MØLLER - MÆRSK A/S")
    ]
    assert search_companies("Orsted", market="DK", provider=provider)[0].entity_id == "DK-12345678"


def test_denmark_issuer_rename_keeps_business_id_and_source_filing_name() -> None:
    class RenamedTransport(DenmarkTransport):
        def post_json(self, url: str, payload: dict, **kwargs: object):
            return {"paging": {"totalPages": 1}, "data": {"rows": [{
                "id": "300003541", "IssuerColumn": "Ørsted A/S",
                "CategoryColumn": "Annual financial report",
                "PublicationDateColumn": "06-02-2026 08:00:01",
            }]}}

        def get_json(self, url: str, **kwargs: object):
            if url.endswith("/details/300003541"):
                return {"heading": "Annual report", "sections": [
                    {"heading": "Notification", "elements": [
                        _element("Announcement ID", "300003541"),
                        _element("Type", "Annual financial report"),
                        _element("Document(s)", _DOC, kind="link", title="annual.zip (English)"),
                    ]},
                    {"heading": "Time", "elements": [_element("Published", "06-02-2026 08:00:01")]},
                    {"heading": "Issuer", "elements": [
                        _element("Company", "Ørsted A/S"),
                        _element("National business ID", "DK-36213728"),
                    ]},
                ]}
            return super().get_json(url, **kwargs)

    provider = DenmarkOAMProvider(transport=RenamedTransport())
    company = Company("DK-36213728", market="DK", provider=provider)
    assert company.entity.name == "Ørsted A/S"
    filing = company.filings(form="annual", limit=1).latest()
    assert filing.entity_id == "DK-36213728"
    assert filing.provider_metadata["source_issuer_name"] == "Ørsted A/S"
    assert len(filing.documents) == 1
    assert company.get_filing("300003541").provider_metadata["source_issuer_name"] == "Ørsted A/S"

    with pytest.raises(ProviderError, match="another issuer"):
        provider._filing(company.entity, {
            "id": "300003542", "IssuerColumn": "OTHER A/S",
            "CategoryColumn": "Annual financial report",
            "PublicationDateColumn": "06-02-2026 08:00:01",
        })


def test_denmark_htm_original_is_readable_html() -> None:
    html_url = _DOC.replace(".zip", ".htm")

    class HtmlDetail(DenmarkTransport):
        def get_json(self, url: str, **kwargs: object):
            data = super().get_json(url, **kwargs)
            if url.endswith("/details/300003388"):
                link = data["sections"][0]["elements"][2]["value"]
                link["url"] = html_url
                link["title"] = "Annual report.htm (English)"
            return data

        def get(self, url: str, **_: object) -> bytes:
            assert url == html_url
            return b"<html><body><p>Filed annual report</p></body></html>"

    filing = Company("DK-61056416", market="DK", provider=DenmarkOAMProvider(
        transport=HtmlDetail(),
    )).filings(form="annual").latest()
    document = filing.primary_document
    assert document.media_type == "text/html"
    assert "Filed annual report" in filing.text()


def test_denmark_detail_rejects_changed_source_issuer() -> None:
    class MismatchedDetail(DenmarkTransport):
        def get_json(self, url: str, **kwargs: object):
            data = super().get_json(url, **kwargs)
            if url.endswith("/details/300003388"):
                data["sections"][2]["elements"][0]["value"]["value"] = "ANOTHER ISSUER"
            return data

    provider = DenmarkOAMProvider(transport=MismatchedDetail())
    filing = Company("DK-61056416", market="DK", provider=provider).filings(form="annual").latest()
    with pytest.raises(ProviderError, match="differs from the selected filing"):
        _ = filing.documents


def test_cover_notice_is_an_announcement_and_the_report_file_is_primary():
    # DSV, Coloplast and Danske interims "passed" on an ~8k-character HTML notice;
    # the report was the PDF or ZIP beside it.
    notice = _DOC.replace("Carlsberg-2025-12-31-en.zip", "announcement.html")
    report = _DOC.replace("Carlsberg-2025-12-31-en.zip", "interim-report.pdf")

    class NoticeAndReport(DenmarkTransport):
        def get_json(self, url, **kwargs):
            data = super().get_json(url, **kwargs)
            if url.endswith("/details/300003388"):
                elements = data["sections"][0]["elements"]
                elements[2] = _element("Document(s)", notice, kind="link", title="announcement.html (English)")
                elements.append(_element("Document(s)", report, kind="link", title="interim-report.pdf (English)"))
            return data

    filing = Company("DK-61056416", market="DK", provider=DenmarkOAMProvider(transport=NoticeAndReport())).filings(
        form="annual", limit=1).latest()
    roles = {document.filename: document.role for document in filing.documents}
    assert roles == {"announcement.html": "announcement", "interim-report.pdf": "report"}
    assert filing.primary_document.filename == "interim-report.pdf"
