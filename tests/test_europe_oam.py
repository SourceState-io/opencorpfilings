"""Offline contract fixtures for the two national OAM routes and index routing."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile

import httpx
import pytest

from opencorpfilings import (
    AmbiguousEntityError, Company, DownloadError, EntityNotFoundError, FilingArchiveMember,
    FilingNotFoundError, ProviderError,
    UnsupportedCapabilityError, search_companies,
)
from opencorpfilings import UnsupportedMarketError, models
from opencorpfilings.providers import provider_for_market
from opencorpfilings.providers.esef import ESEFProvider, INDEX_COUNTRIES
from opencorpfilings.providers.finland_oam import FinlandOAMProvider
from opencorpfilings.providers.france_oam import FranceOAMProvider
from opencorpfilings.providers.spain_cnmv import SpainCNMVProvider
from opencorpfilings.providers.sweden_oam import SwedenOAMProvider
from opencorpfilings.transport import HttpTransport
from test_ixbrl import XHTML


FR_LEI = "969500U43TVR8CCVBJ97"


def _original_zip() -> bytes:
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("original.txt", "source bytes")
    return payload.getvalue()


ORIGINAL_ZIP = _original_zip()


class FranceTransport:
    def __init__(self) -> None:
        self.rows = [
            {"uin_idt_uin": "582412_20250514", "uin_dat_amf": "2025-05-14T14:27:16+00:00",
             "identificationdiffuseur_idi_cod_dif": "432",
             "identificationsociete_iso_cd_lei": FR_LEI,
             "identificationsociete_iso_nom_soc": "AB SCIENCE",
             "identificationsociete_iso_cd_isi": "FR0010557264",
             "informationdeposee_inf_stp_pri": "003000",
             "informationdeposee_inf_tit_inf": "Rapport Financier Annuel 2024",
             "informationdeposee_inf_upg_inf_inf_upg_sts": "NEW",
             "informationdeposee_inf_lng_inf": "Français",
             "url_de_recuperation": "https://fr.ftp.opendatasoft.com/datadila/INFOFI/432/report.zip"},
        ]

    def get_json(self, url: str, *, params: dict) -> dict:
        assert "flux-amf-new-prod/records" in url
        assert FR_LEI in params["where"]
        assert params["order_by"] == "uin_dat_amf DESC"
        return {"total_count": 1, "results": self.rows[params["offset"]: params["offset"] + params["limit"]]}

    def get(self, url: str, **_: object) -> bytes:
        assert url.endswith("/report.zip")
        return ORIGINAL_ZIP

    def get_to_file(self, url, path, *, expected_prefix=None):
        content = self.get(url)
        assert expected_prefix is None or content.startswith(expected_prefix)
        path.write_bytes(content)
        return path


def test_france_oam_annual_is_source_dated_and_keeps_raw_code() -> None:
    company = Company(FR_LEI, market="FR", provider=FranceOAMProvider(transport=FranceDirectTransport()))
    collection = company.filings(form="annual")
    assert collection.order_basis == "published_at"
    filing = collection.latest()
    assert filing.filing_id == "432:582412_20250514"
    assert filing.filing_date == date(2025, 5, 14)
    assert filing.filing_type_raw == "003000"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.primary_document.source_url.endswith("/report.zip")
    assert filing.primary_document.download() == ORIGINAL_ZIP
    assert collection.head(1)[0].filing_id == filing.filing_id
    assert collection.latest(1)[0].filing_id == filing.filing_id
    assert collection.get(filing.filing_id).filing_id == filing.filing_id
    assert company.get_filing(filing.filing_id).filing_id == filing.filing_id
    assert filing.select_document(media_type="application/zip").document_id.endswith("report.zip")


def test_france_annual_in_secondary_source_code_keeps_primary_code() -> None:
    class SecondaryAnnualTransport(FranceTransport):
        def __init__(self) -> None:
            super().__init__()
            self.rows[0].update(
                informationdeposee_inf_stp_pri="300005",
                informationdeposee_inf_stp_inf='["300005", "003000"]',
                informationdeposee_inf_tit_inf="Document d'enregistrement universel 2024",
                url_de_recuperation="https://fr.ftp.opendatasoft.com/datadila/INFOFI/156/report.xbri",
            )
            self.where = ""

        def get_json(self, url: str, *, params: dict) -> dict:
            self.where = params["where"]
            if "informationdeposee_inf_stp_pri" in self.where:
                assert "informationdeposee_inf_stp_inf LIKE '%\"003000\"%'" in self.where
            return super().get_json(url, params=params)

        def get(self, url: str, **_: object) -> bytes:
            assert url.endswith("/report.xbri")
            return ORIGINAL_ZIP

    transport = SecondaryAnnualTransport()
    company = Company(FR_LEI, market="FR", provider=FranceOAMProvider(transport=transport))
    filing = company.filings(form="annual").latest()
    assert filing.filing_type_raw == "300005"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.provider_metadata["informationdeposee_inf_stp_inf"] == '["300005", "003000"]'
    assert filing.primary_document.source_url.endswith("/report.xbri")
    assert filing.primary_document.media_type == "application/zip"
    assert filing.primary_document.members[0].entry_path == "original.txt"


@pytest.mark.parametrize("extension", [".htm", ".html"])
def test_france_zip_reads_inline_facts_from_html_named_report(extension: str) -> None:
    class HtmlReportTransport(FranceTransport):
        def get(self, url: str, **_: object) -> bytes:
            assert url.endswith("/report.zip")
            package = BytesIO()
            with ZipFile(package, "w") as archive:
                archive.writestr("report" + extension, XHTML)
            return package.getvalue()

    filing = Company(FR_LEI, market="FR", provider=FranceOAMProvider(
        transport=HtmlReportTransport())).filings(form="annual").latest()
    assert "Part A" in filing.text()
    facts = filing.facts
    assert [fact.concept_raw for fact in facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]
    assert all(f"::report{extension}#ix-fact-" in fact.source_location for fact in facts)


def test_france_direct_html_reads_inline_facts() -> None:
    class HtmlReportTransport(FranceTransport):
        def __init__(self) -> None:
            super().__init__()
            self.rows[0]["url_de_recuperation"] = (
                "https://fr.ftp.opendatasoft.com/datadila/INFOFI/432/report.htm"
            )

        def get(self, url: str, **_: object) -> bytes:
            assert url.endswith("/report.htm")
            return XHTML

    filing = Company(FR_LEI, market="FR", provider=FranceOAMProvider(
        transport=HtmlReportTransport())).filings(form="annual").latest()
    assert filing.primary_document.media_type == "text/html"
    assert [fact.concept_raw for fact in filing.facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]


def test_france_untagged_html_remains_without_raw_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    class PlainReportTransport(FranceTransport):
        def get(self, url: str, **_: object) -> bytes:
            package = BytesIO()
            with ZipFile(package, "w") as archive:
                archive.writestr("report.htm", b"<html><body>Unclosed<br>plain report")
            return package.getvalue()

    import opencorpfilings.providers.france_oam as france_oam

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    filing = Company(FR_LEI, market="FR", provider=FranceOAMProvider(
        transport=PlainReportTransport())).filings(form="annual").latest()
    member = filing.primary_document.members[0]
    with pytest.raises(UnsupportedCapabilityError, match="no parsed inline XBRL facts"):
        _ = filing.facts
    assert member._cached_bytes is None


def test_france_stops_extracting_zip_members_after_tagged_report(monkeypatch: pytest.MonkeyPatch) -> None:
    class TwoReportTransport(FranceTransport):
        def get(self, url: str, **_: object) -> bytes:
            package = BytesIO()
            with ZipFile(package, "w") as archive:
                archive.writestr("issuer/reports/report.xhtml", XHTML)
                archive.writestr("later.xhtml", XHTML)
            return package.getvalue()

    original_download = FilingArchiveMember.download

    def selected_download(member: FilingArchiveMember, *args, **kwargs):
        if member.entry_path == "later.xhtml":
            raise AssertionError("later archive member should not be extracted")
        return original_download(member, *args, **kwargs)

    monkeypatch.setattr(FilingArchiveMember, "download", selected_download)
    filing = Company(FR_LEI, market="FR", provider=FranceOAMProvider(
        transport=TwoReportTransport())).filings(form="annual").latest()
    assert len(filing.facts) == 3


def test_france_large_inline_member_parses_without_retaining_member_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    class HtmlReportTransport(FranceTransport):
        def get(self, url: str, **_: object) -> bytes:
            package = BytesIO()
            with ZipFile(package, "w") as archive:
                archive.writestr("report.htm", XHTML)
            return package.getvalue()

    import opencorpfilings.providers.france_oam as france_oam

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    filing = Company(FR_LEI, market="FR", provider=FranceOAMProvider(
        transport=HtmlReportTransport())).filings(form="annual").latest()
    member = filing.primary_document.members[0]
    assert member._cached_bytes is None
    assert [fact.concept_raw for fact in filing.facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]
    assert member._cached_bytes is None


def test_france_streams_original_zip_and_reads_saved_archive(tmp_path: Path) -> None:
    provider = FranceOAMProvider(transport=FranceDirectTransport())
    filing = Company(FR_LEI, market="FR", provider=provider).filings(form="annual").latest()
    document = filing.primary_document
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=ORIGINAL_ZIP)

    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    target = tmp_path / "annual.zip"
    assert document.download(target) == target
    assert target.read_bytes() == ORIGINAL_ZIP
    assert document._cached_bytes is None
    assert document.members[0].download() == b"source bytes"
    assert document._cached_bytes is None
    assert len(requests) == 1


def test_france_streamed_error_preserves_existing_target(tmp_path: Path) -> None:
    provider = FranceOAMProvider(transport=FranceDirectTransport())
    document = Company(FR_LEI, market="FR", provider=provider).filings(form="annual").latest().primary_document
    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"<html>source unavailable</html>"),
    )))
    target = tmp_path / "annual.zip"
    target.write_bytes(b"existing")
    with pytest.raises(DownloadError, match="attachment failed"):
        document.download(target)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


class FranceDirectTransport(FranceTransport):
    def __init__(self) -> None:
        super().__init__()
        self.queries: list[dict] = []
        self.direct_rows: list[dict] = self.rows

    def get_json(self, url: str, *, params: dict) -> dict:
        self.queries.append(params)
        if "uin_idt_uin" in params["where"]:
            return {"total_count": len(self.direct_rows), "results": self.direct_rows}
        return super().get_json(url, params=params)


def test_france_direct_filing_id_uses_one_source_record_request() -> None:
    transport = FranceDirectTransport()
    company = Company(FR_LEI, market="FR", provider=FranceOAMProvider(transport=transport))
    filing = company.get_filing("432:582412_20250514", start="2025-01-01", end="2025-12-31")
    assert filing.filing_id == "432:582412_20250514"
    assert filing.primary_document.source_url.endswith("/report.zip")
    assert len(transport.queries) == 2  # issuer profile, then exact record
    assert "uin_idt_uin = '582412_20250514'" in transport.queries[1]["where"]
    assert "identificationdiffuseur_idi_cod_dif = '432'" in transport.queries[1]["where"]
    assert transport.queries[1]["limit"] == 2


def test_france_direct_filing_id_rejects_absent_foreign_and_malformed_records() -> None:
    transport = FranceDirectTransport()
    company = Company(FR_LEI, market="FR", provider=FranceOAMProvider(transport=transport))
    with pytest.raises(FilingNotFoundError):
        company.get_filing("432:582412_20250514", end="2024-12-31")
    transport.direct_rows = []
    with pytest.raises(FilingNotFoundError):
        company.get_filing("432:582412_20250514")
    # Another issuer differs in both LEI and ISIN; a shared ISIN is the same issuer.
    transport.direct_rows = [{**transport.rows[0], "identificationsociete_iso_cd_lei": "969500AAA00000000001",
                              "identificationsociete_iso_cd_isi": "FR0000000001"}]
    with pytest.raises(FilingNotFoundError):
        company.get_filing("432:582412_20250514")
    with pytest.raises(FilingNotFoundError):
        company.get_filing("../../other")


def test_france_direct_filing_id_rejects_nonunique_source_result() -> None:
    transport = FranceDirectTransport()
    transport.direct_rows = [transport.rows[0], transport.rows[0]]
    company = Company(FR_LEI, market="FR", provider=FranceOAMProvider(transport=transport))
    with pytest.raises(ProviderError, match="inconsistent records"):
        company.get_filing("432:582412_20250514")


class FranceSearchTransport(FranceTransport):
    def __init__(self) -> None:
        super().__init__()
        self.queries: list[dict] = []
        self.total_override: int | None = None
        self.candidates = [
            {"identificationsociete_iso_cd_lei": "969500AAA00000000001",
             "identificationsociete_iso_nom_soc": "AB SCIENCE HOLDINGS", "latest": "2026-10-01T00:00:00+00:00"},
            {"identificationsociete_iso_cd_lei": FR_LEI,
             "identificationsociete_iso_nom_soc": "AB SCIENCE SA", "latest": "2026-09-30T00:00:00+00:00"},
            {"identificationsociete_iso_cd_lei": FR_LEI,
             "identificationsociete_iso_nom_soc": "AB SCIENCE", "latest": "2026-09-29T06:07:12+00:00"},
        ]

    def get_json(self, url: str, *, params: dict) -> dict:
        self.queries.append(params)
        if "group_by" in params:
            return {"total_count": self.total_override if self.total_override is not None else len(self.candidates),
                    "results": self.candidates[:params["limit"]]}
        return super().get_json(url, params=params)


def test_france_source_name_candidates_and_exact_name_resolution() -> None:
    transport = FranceSearchTransport()
    provider = FranceOAMProvider(transport=transport)
    matches = search_companies("ab science", market="FR", provider=provider)
    assert [(item.name, item.entity_id) for item in matches] == [
        ("AB SCIENCE", FR_LEI), ("AB SCIENCE HOLDINGS", "969500AAA00000000001")]
    assert matches[0].provenance.source_url == matches[0].source_url
    assert matches[0].identifiers[0].value == FR_LEI
    assert "search(identificationsociete_iso_nom_soc, 'ab science')" in transport.queries[0]["where"]
    assert "group_by" in transport.queries[0]
    company = Company("ab science", market="FR", provider=provider)
    assert company.entity.entity_id == FR_LEI
    assert company.filings(form="annual").latest().filing_type_raw == "003000"
    assert Company(matches[0], provider=provider).filings(form="annual").latest().entity_id == FR_LEI


def test_france_exact_name_rejects_ambiguous_lei_and_no_match() -> None:
    transport = FranceSearchTransport()
    transport.candidates[0]["identificationsociete_iso_nom_soc"] = "AB SCIENCE"
    company = Company("AB SCIENCE", market="FR", provider=FranceOAMProvider(transport=transport))
    with pytest.raises(AmbiguousEntityError):
        _ = company.entity
    transport.candidates = []
    with pytest.raises(EntityNotFoundError):
        _ = Company("unknown issuer", market="FR", provider=FranceOAMProvider(transport=transport)).entity


def test_france_name_search_escapes_apostrophe_in_source_query() -> None:
    transport = FranceSearchTransport()
    transport.candidates = []
    assert search_companies("L'OREAL", market="FR", provider=FranceOAMProvider(transport=transport)) == []
    assert "search(identificationsociete_iso_nom_soc, 'L\\'OREAL')" in transport.queries[0]["where"]


def test_france_exact_name_requires_complete_candidate_page() -> None:
    transport = FranceSearchTransport()
    transport.total_override = 201
    with pytest.raises(AmbiguousEntityError, match="candidate limit"):
        _ = Company("AB SCIENCE", market="FR", provider=FranceOAMProvider(transport=transport)).entity


def test_france_name_search_escapes_backslash_in_source_query() -> None:
    transport = FranceSearchTransport()
    transport.candidates = []
    assert search_companies("A\\B", market="FR", provider=FranceOAMProvider(transport=transport)) == []
    assert "search(identificationsociete_iso_nom_soc, 'A\\\\B')" in transport.queries[0]["where"]


class FrancePeriodTransport(FranceTransport):
    def __init__(self) -> None:
        super().__init__()
        base = self.rows[0]
        self.rows = [
            {**base, "uin_idt_uin": uin, "uin_dat_amf": timestamp,
             "informationdeposee_inf_stp_pri": code,
             "informationdeposee_inf_tit_inf": title,
             "url_de_recuperation": f"https://fr.ftp.opendatasoft.com/datadila/INFOFI/432/{uin}.pdf"}
            for uin, timestamp, code, title in (
                ("annual_20250514", "2025-05-14T14:27:16+00:00", "003000", "Rapport financier annuel"),
                ("half_20251010", "2025-10-10T16:17:06+00:00", "004000", "Rapport financier semestriel 2025"),
                ("half_20241011", "2024-10-11T16:08:27+00:00", "004000", "Rapport financier semestriel 2024"),
                ("q1_20260917", "2026-09-17T16:00:00+00:00", "005001", "Information T1"),
                ("q3_20250908", "2025-09-08T16:00:00+00:00", "005002", "Information T3"),
                ("notice_20250701", "2025-07-01T12:00:00+00:00", "002003", "Mise à disposition"),
                ("qold_20090201", "2009-02-01T12:00:00+00:00", "005000", "Information trimestrielle"),
            )
        ]
        self.requests: list[str] = []

    def get_json(self, url: str, *, params: dict) -> dict:
        assert "flux-amf-new-prod/records" in url
        where = params["where"]
        assert FR_LEI in where
        self.requests.append(where)
        match = re.search(r"informationdeposee_inf_stp_pri = '(\d{6})'", where)
        in_match = re.search(r"informationdeposee_inf_stp_pri IN \(([^)]+)\)", where)
        codes = {match.group(1)} if match else set(re.findall(r"'(\d{6})'", in_match.group(1))) if in_match else None
        lower = re.search(r"uin_dat_amf >= '(\d{4}-\d{2}-\d{2})'", where)
        upper = re.search(r"uin_dat_amf < '(\d{4}-\d{2}-\d{2})'", where)
        rows = sorted((row for row in self.rows
                       if (codes is None or row["informationdeposee_inf_stp_pri"] in codes)
                       and (lower is None or row["uin_dat_amf"][:10] >= lower.group(1))
                       and (upper is None or row["uin_dat_amf"][:10] < upper.group(1))),
                      key=lambda row: row["uin_dat_amf"], reverse=True)
        return {"total_count": len(rows),
                "results": rows[params["offset"]:params["offset"] + params["limit"]]}

    def get(self, url: str, **_: object) -> bytes:
        assert url.endswith(".pdf")
        return b"%PDF-1.7 original"


def test_france_interim_uses_source_half_year_code_and_pushes_date_window() -> None:
    transport = FrancePeriodTransport()
    company = Company(FR_LEI, market="FR", provider=FranceOAMProvider(transport=transport))
    filing = company.filings(form="interim", start="2025-01-01", end="2025-12-31").latest()
    assert filing.filing_id == "432:half_20251010"
    assert filing.filing_type_raw == "004000"
    assert filing.filing_type_normalized == "INTERIM"
    assert filing.filing_date == date(2025, 10, 10)
    assert filing.primary_document.media_type == "application/pdf"
    assert filing.primary_document.download().startswith(b"%PDF")
    assert "informationdeposee_inf_stp_pri = '004000'" in transport.requests[-1]
    assert "uin_dat_amf >= '2025-01-01'" in transport.requests[-1]
    assert "uin_dat_amf < '2026-01-01'" in transport.requests[-1]


def test_france_quarterly_codes_and_unfiltered_types_keep_source_meaning() -> None:
    transport = FrancePeriodTransport()
    company = Company(FR_LEI, market="FR", provider=FranceOAMProvider(transport=transport))
    quarterly = company.filings(form="quarterly").head(2)
    assert [filing.filing_type_raw for filing in quarterly] == ["005001", "005002"]
    assert all(filing.filing_type_normalized == "QUARTERLY" for filing in quarterly)
    assert "informationdeposee_inf_stp_pri IN ('005000','005001','005002')" in transport.requests[-1]
    assert company.filings(form="005002").latest().filing_type_raw == "005002"
    unfiltered = {filing.filing_type_raw: filing.filing_type_normalized
                  for filing in company.filings().head(7)}
    assert unfiltered["003000"] == "ANNUAL"
    assert unfiltered["004000"] == "INTERIM"
    assert unfiltered["005000"] == "QUARTERLY"
    assert unfiltered["002003"] is None


_LANDING = b"""<html><input name='_csrf' value='token'>
<nef-form-select name='company' options='[{"value":"552","label":"KONE Oyj"}]'></nef-form-select></html>"""
_SEARCH = b"""<nef-table><nef-table-row class='message-row'>
<nef-table-cell>2024-01-26 08:45:25 EET</nef-table-cell>
<nef-table-cell>KONE Oyj</nef-table-cell>
<nef-table-cell><nef-link href='/view/441549?lang=en'>KONE Annual Review 2023</nef-link></nef-table-cell>
<nef-table-cell>Annual financial report</nef-table-cell>
</nef-table-row></nef-table>"""
_NOTICE = b"""<html><nef-link href='/cns-web/oam/viewAttachment.action?messageAttachmentId=311728'>
KONE-2023-12-31-en.zip</nef-link></html>"""


class FinlandTransport:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    def get(self, url: str, **_: object) -> bytes:
        if url == "https://oam.fi/":
            return _LANDING
        if url == "https://oam.fi/view/441549?lang=en":
            return _NOTICE
        if "messageAttachmentId=311728" in url:
            return ORIGINAL_ZIP
        raise AssertionError(url)

    def post_form(self, url: str, *, data: dict) -> bytes:
        assert url == "https://oam.fi/"
        self.posts.append(data)
        return _SEARCH


def test_finland_oam_exact_name_annual_and_original_attachment() -> None:
    transport = FinlandTransport()
    company = Company("KONE Oyj", market="FI", provider=FinlandOAMProvider(transport=transport))
    assert company.entity.entity_id == "552"
    filing = company.filings(form="annual", limit=1).latest()
    assert filing.filing_id == "441549"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.published_at.isoformat() == "2024-01-26T08:45:25+02:00"
    assert transport.posts[0]["company"] == "552"
    assert transport.posts[0]["category"] == "270"
    assert filing.primary_document.document_id == "311728"
    assert filing.primary_document.download() == ORIGINAL_ZIP


def test_finland_oam_requires_exact_identity_and_rejects_unverified_forms() -> None:
    company = Company("KONE", market="FI", provider=FinlandOAMProvider(transport=FinlandTransport()))
    with pytest.raises(EntityNotFoundError, match=r"search_companies\('KONE', market='FI'\)"):
        _ = company.entity
    company = Company("Nokia Oyj", market="FI", provider=FinlandOAMProvider(transport=FinlandTransport()))
    with pytest.raises(EntityNotFoundError, match=r"search_companies\('Nokia', market='FI'\)"):
        _ = company.entity
    company = Company("KONE Oyj", market="FI", provider=FinlandOAMProvider(transport=FinlandTransport()))
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(form="quarterly").latest()


def test_finland_oam_full_page_scan_has_a_configurable_safety_bound() -> None:
    transport = FinlandTransport()
    provider = FinlandOAMProvider(transport=transport, page_size=1, max_pages=1)
    company = Company("KONE Oyj", market="FI", provider=provider)
    with pytest.raises(UnsupportedCapabilityError, match="page safety bound"):
        list(company.filings(form="annual"))
    assert [post["page"] for post in transport.posts] == ["1"]


def test_index_route_is_separate_from_national_oam() -> None:
    assert len(INDEX_COUNTRIES) == 21
    assert isinstance(provider_for_market("FR"), FranceOAMProvider)
    assert isinstance(provider_for_market("FI"), FinlandOAMProvider)
    assert isinstance(provider_for_market("FR", source="esef_index"), ESEFProvider)
    assert isinstance(provider_for_market("ES"), SpainCNMVProvider)
    assert isinstance(provider_for_market("ES", source="esef_index"), ESEFProvider)
    assert isinstance(provider_for_market("ES", source="oam"), SpainCNMVProvider)
    assert isinstance(provider_for_market("SE", source="oam"), SwedenOAMProvider)
    with pytest.raises(UnsupportedCapabilityError):
        provider_for_market("IT", source="oam")
    with pytest.raises(UnsupportedCapabilityError):
        provider_for_market("NO", source="oam")


def test_retired_national_routes_fall_back_to_the_index_or_are_unsupported() -> None:
    # Eleven small-market national routes were retired on 2026-10-09.
    for market in ("IS", "LT", "HR", "SK", "EE", "MT", "HU"):
        provider = provider_for_market(market)
        try:
            assert provider.name == "esef_index"
        finally:
            provider.close()
        with pytest.raises(UnsupportedCapabilityError, match="no national OAM route"):
            provider_for_market(market, source="oam")
    for market in ("RO", "LV", "CY", "LI"):
        with pytest.raises(UnsupportedMarketError):
            provider_for_market(market)


@pytest.mark.parametrize("market,provider_name", [
    ("FR", "france_oam"), ("FI", "finland_oam"), ("ES", "spain_cnmv"),
    ("SE", "sweden_oam"), ("PL", "poland_oam"), ("NL", "netherlands_oam"), ("DK", "denmark_oam"),
])
def test_national_source_is_default_and_index_remains_explicit(market, provider_name) -> None:
    routes = [({}, provider_name), ({"source": "oam"}, provider_name)]
    if market in INDEX_COUNTRIES:  # CZ, CY, RO, LV and PL left the index on 2026-10-08
        routes.append(({"source": "esef_index"}, "esef_index"))
    for options, expected in routes:
        provider = provider_for_market(market, **options)
        try:
            assert provider.name == expected
        finally:
            provider.close()


_CNMV = b"""<html><head><title>CNMV - Informes financieros anuales - IBERDROLA, S.A.</title></head>
<body><table id='ctl00_ContentPrincipal_gridInformes'><tr><th>Header</th></tr>
<tr><td>20515</td><td>31/12/2024</td><td>28/02/2025</td><td>KPMG</td>
<td><a href='https://www.cnmv.es/webservices/verdocumento/ver?e=pdf'>Individual</a></td>
<td><a href='https://www.cnmv.es/webservices/verdocumento/ver?e=zip'>ZIP</a></td>
<td></td><td><a href='infadicionifa.aspx?id=0&amp;nreg=2025031726&amp;nregaud=20515'>More</a></td>
</tr></table></body></html>"""


class SpainTransport:
    def get(self, url: str, **_: object) -> bytes:
        if "/portal/Consultas/IFA/ListadoIFA?" in url:
            assert "A-48010615" in url
            return _CNMV
        if "e=zip" in url:
            return ORIGINAL_ZIP
        if "e=pdf" in url:
            return b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>Spanish annual source text</body></html>'
        raise AssertionError(url)


def test_spain_cnmv_annual_register_preserves_local_id_and_zip() -> None:
    company = Company("A-48010615", market="ES", provider=SpainCNMVProvider(transport=SpainTransport()))
    assert company.entity.name == "IBERDROLA, S.A."
    filing = company.filings(form="annual", start="2025-01-01", end="2025-12-31").latest()
    assert filing.filing_id == "2025031726"
    assert filing.filing_date == date(2025, 2, 28)
    assert filing.period_end == date(2024, 12, 31)
    assert filing.filing_type_raw == "IFA"
    assert filing.primary_document.media_type == "application/zip"
    assert filing.primary_document.download() == ORIGINAL_ZIP


def test_cnmv_pdf_label_can_resolve_to_original_xhtml() -> None:
    company = Company("A-48010615", market="ES", provider=SpainCNMVProvider(transport=SpainTransport()))
    filing = company.filings(form="annual", start="2025-01-01", end="2025-12-31").latest()
    document = next(item for item in filing.documents if item.media_type == "application/pdf")
    assert "Spanish annual source text" in document.text()
    assert document.media_type == "application/xhtml+xml"
    assert document.filename.endswith(".xhtml")
    assert document.provider_metadata["listed_media_type"] == "application/pdf"
    with pytest.raises(UnsupportedCapabilityError, match="PDF pages"):
        _ = document.pages


def test_cnmv_streamed_save_keeps_original_zip_and_discovered_xhtml(tmp_path: Path) -> None:
    xhtml = (b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
             b'<body>Spanish annual source text</body></html>')

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("ListadoIFA"):
            return httpx.Response(200, content=_CNMV)
        return httpx.Response(200, content=ORIGINAL_ZIP if request.url.params.get("e") == "zip" else xhtml)

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    company = Company("A-48010615", market="ES", provider=SpainCNMVProvider(transport=transport))
    filing = company.filings(form="annual", start="2025-01-01", end="2025-12-31").latest()
    package = filing.primary_document
    saved_zip = tmp_path / "annual.zip"
    assert package.download(saved_zip) == saved_zip
    assert saved_zip.read_bytes() == ORIGINAL_ZIP
    assert package._cached_bytes is None
    assert package.members[0].download() == b"source bytes"

    report = next(document for document in filing.documents if document.media_type == "application/pdf")
    saved_report = tmp_path / "annual.xhtml"
    assert report.download(saved_report) == saved_report
    assert saved_report.read_bytes() == xhtml
    assert report._cached_bytes is None
    assert report.media_type == "application/xhtml+xml"
    assert report.filename.endswith(".xhtml")
    assert report.provider_metadata["listed_media_type"] == "application/pdf"
    assert "Spanish annual source text" in report.text()


def test_cnmv_saved_annual_zip_facts_do_not_buffer_large_report(tmp_path: Path, monkeypatch) -> None:
    from opencorpfilings import models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("reports/annual.xhtml", XHTML)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("ListadoIFA"):
            return httpx.Response(200, content=_CNMV)
        return httpx.Response(200, content=buffer.getvalue() if request.url.params.get("e") == "zip" else XHTML)

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    filing = Company("A-48010615", market="ES", provider=SpainCNMVProvider(
        transport=transport,
    )).filings(form="annual", start="2025-01-01", end="2025-12-31").latest()
    package = filing.primary_document
    package.download(tmp_path / "annual.zip")
    member = package.members[0]

    assert [fact.concept_raw for fact in filing.facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]
    assert package._cached_bytes is None
    assert member._cached_bytes is None


@pytest.mark.parametrize("kind,invalid", [("zip", b"PK\x03\x04broken"), ("pdf", b"unexpected source")])
def test_cnmv_streamed_save_rejects_invalid_bytes_without_replacing_target(
    tmp_path: Path, kind: str, invalid: bytes,
) -> None:

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("ListadoIFA"):
            return httpx.Response(200, content=_CNMV)
        return httpx.Response(200, content=invalid if request.url.params.get("e") == kind else ORIGINAL_ZIP)

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    company = Company("A-48010615", market="ES", provider=SpainCNMVProvider(transport=transport))
    filing = company.filings(form="annual", start="2025-01-01", end="2025-12-31").latest()
    document = next(document for document in filing.documents if
                    document.media_type == ("application/zip" if kind == "zip" else "application/pdf"))
    target = tmp_path / "original"
    target.write_bytes(b"keep existing")
    with pytest.raises(DownloadError):
        document.download(target)
    assert target.read_bytes() == b"keep existing"
    assert list(tmp_path.iterdir()) == [target]


def test_cnmv_original_pdf_retains_page_access() -> None:
    class PdfSpainTransport(SpainTransport):
        def get(self, url: str, **kwargs: object) -> bytes:
            if "e=pdf" in url:
                from pathlib import Path

                return (Path(__file__).parent / "fixtures" / "two_page_report.pdf").read_bytes()
            return super().get(url, **kwargs)

    company = Company("A-48010615", market="ES", provider=SpainCNMVProvider(transport=PdfSpainTransport()))
    filing = company.filings(form="annual", start="2025-01-01", end="2025-12-31").latest()
    document = next(item for item in filing.documents if item.media_type == "application/pdf")
    assert len(document.pages) == 2
    assert document.media_type == "application/pdf"
    assert "Annual revenue" in document.text()
    assert "listed_media_type" not in document.provider_metadata


_SE_LANDING = b"<form><input name='__VIEWSTATE' type='hidden' value='v'><input name='__EVENTVALIDATION' type='hidden' value='e'></form>"
_SE_RESULT = b"""<span id='ctl00_main_lblCompanyName'>Swedbank AB</span>
<span id='ctl00_main_lblOrganizationNumberValue'>502017-7753</span>
<span id='ctl00_main_lblLEIValue'>M312WZV08Y7LYUC71685</span>
<table id='ctl00_main_gvwYearReports'><tr><th>Report period</th></tr><tr><td>2024</td>
<td><a href='/search/GetFile.aspx?fid=57992'>Svenska</a>
<a href='/search/GetFile.aspx?fid=57991'>Engelska</a></td></tr></table>
<table id='ctl00_main_gvwHalfYearReports'><tr><td>2025</td>
<td><a href='/search/GetFile.aspx?fid=59630'>Engelska</a></td></tr></table>
<table id='ctl00_main_gvwQuarterReports'><tr><td>2025-09</td>
<td><a href='/search/GetFile.aspx?fid=60001'>Engelska</a></td></tr></table>"""


class SwedenTransport:
    def __init__(self) -> None:
        self.searches: list[dict] = []
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("report.xhtml", "<html><body>Swedbank annual report</body></html>")
        self.package = buffer.getvalue()

    def get(self, url: str, **_: object) -> bytes:
        if url.endswith("Search.aspx"):
            return _SE_LANDING
        if "fid=57991" in url:
            return self.package
        if "GetFile.aspx?fid=" in url:
            return b"%PDF-1.4 fixture"
        raise AssertionError(url)

    def post_form(self, url: str, *, data: dict) -> bytes:
        self.searches.append(data)
        return _SE_RESULT


def test_sweden_oam_org_lookup_report_period_and_source_files() -> None:
    transport = SwedenTransport()
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(transport=transport))
    assert company.entity.name == "Swedbank AB"
    assert company.entity.identifiers[1].value == "M312WZV08Y7LYUC71685"
    annual = company.filings(form="annual")
    assert annual.order_basis == "report_period_label"
    filing = annual.latest()
    assert filing.period_end is None
    assert filing.provider_metadata["report_period_raw"] == "2024"
    assert filing.filing_date is None
    assert filing.filing_id == "502017-7753:annual:2024"
    assert [doc.language for doc in filing.documents] == ["sv", "en"]
    assert [doc.document_id for doc in filing.documents] == ["57992", "57991"]
    assert [member.entry_path for member in filing.documents[1].members] == ["report.xhtml"]
    assert filing.documents[1].media_type == "application/zip"
    assert "Swedbank annual report" in filing.documents[1].text()
    assert transport.searches[0]["ctl00$main$txtOrganizationNumber"] == "502017-7753"
    assert company.filings(form="interim").latest().provider_metadata["report_period_raw"] == "2025"
    assert company.filings(form="quarterly").latest().provider_metadata["report_period_raw"] == "2025-09"
    with pytest.raises(UnsupportedCapabilityError):
        company.filings(form="annual", start="2024-01-01").latest()


def test_sweden_raw_facts_stop_after_first_tagged_report(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = SwedenTransport()
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("first.xhtml", XHTML)
        archive.writestr("second.xhtml", XHTML)
    transport.package = buffer.getvalue()
    original_download = FilingArchiveMember.download

    def guarded_download(self, *args, **kwargs):
        if self.entry_path == "second.xhtml":
            raise AssertionError("later XHTML member was read after facts were found")
        return original_download(self, *args, **kwargs)

    monkeypatch.setattr(FilingArchiveMember, "download", guarded_download)
    filing = Company("502017-7753", market="SE", provider=SwedenOAMProvider(
        transport=transport,
    )).filings(form="annual").latest()
    assert [fact.concept_raw for fact in filing.facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]


def test_finland_row_name_drift_does_not_reject_the_issuers_notice() -> None:
    # Live rows showed "Kesko" for "Kesko Oyj" and old names after renames; the
    # search is already scoped to the source company ID.
    class DriftTransport(FinlandTransport):
        def post_form(self, url: str, *, data: dict) -> bytes:
            return super().post_form(url, data=data).replace(b"KONE Oyj", b"KONE")

    company = Company("KONE Oyj", market="FI", provider=FinlandOAMProvider(transport=DriftTransport()))
    filing = company.filings(form="annual", limit=1).latest()
    assert filing.filing_id == "441549"
    assert filing.provider_metadata["company"] == "KONE"
    assert filing.provider_metadata["issuer_list_name"] == "KONE Oyj"
