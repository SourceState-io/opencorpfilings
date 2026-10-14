"""Offline source-response checks for the Open DART and EDINET adapters."""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from opencorpfilings import Company, search_companies
from opencorpfilings.errors import (
    AuthenticationError, DownloadError, EntityNotFoundError, ParseError, ProviderError, RateLimitError,
    SourceUnavailableError,
    UnsupportedCapabilityError,
)
from opencorpfilings.providers.edinet import API as EDINET_API
from opencorpfilings.providers.edinet import EDINETProvider, REGISTRY, _category as edinet_category
from opencorpfilings.providers.open_dart import API as DART_API, CORP_SEARCH, CORP_SEARCH_EN
from opencorpfilings.providers.open_dart import OpenDARTProvider
from opencorpfilings.transport import HttpTransport
from test_ixbrl import XHTML


def zipped(name: str, content: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def zipped_files(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def xbrl(currency: str) -> bytes:
    return f'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:gaap="urn:filing:gaap">
      <xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="urn:issuer">issuer</xbrli:identifier>
        <xbrli:segment><xbrldi:explicitMember dimension="gaap:RegionAxis">gaap:AsiaMember</xbrldi:explicitMember></xbrli:segment>
      </xbrli:entity><xbrli:period><xbrli:startDate>2024-04-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period></xbrli:context>
      <xbrli:unit id="u1"><xbrli:measure>iso4217:{currency}</xbrli:measure></xbrli:unit>
      <gaap:Revenue contextRef="c1" unitRef="u1">123</gaap:Revenue>
    </xbrli:xbrl>'''.encode()


class Transport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _take(self, url, params):
        safe = {key: value for key, value in (params or {}).items() if key not in {"crtfc_key", "Subscription-Key"}}
        self.calls.append((url, safe))
        # The report-type filter is asserted from calls; fixtures key on the rest.
        key = (url, tuple(sorted((k, v) for k, v in safe.items() if k != "pblntf_detail_ty")))
        return self.responses[key]

    def get(self, url, *, params=None, **_):
        return self._take(url, params)

    def get_json(self, url, *, params=None, **_):
        return self._take(url, params)

    def get_to_file(self, url, path, *, params=None, expected_prefix=None, validate_zip_crc=False, **_):
        body = self._take(url, params)
        assert expected_prefix is None or body.startswith(expected_prefix)
        if validate_zip_crc:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                assert archive.namelist() and archive.testzip() is None
        Path(path).write_bytes(body)
        return Path(path)


def _dart_provider():
    receipt = "20250618000208"
    registry = zipped("CORPCODE.xml", b"<result><list><corp_code>00378363</corp_code><corp_name>3S</corp_name><stock_code>060310</stock_code></list></result>")
    list_params = {
        "corp_code": "00378363",
        "bgn_de": "20250101",
        "end_de": "20251231",
        "last_reprt_at": "N",
        "sort": "date",
        "sort_mth": "desc",
        "page_count": 100,
        "page_no": 1,
    }
    responses = {
        (f"{DART_API}/corpCode.xml", ()): registry,
        (CORP_SEARCH, (("textCrpNm", "060310"),)): b'''<table class="tb"><tbody>
          <tr><td><input name="hiddenCikCD1" value="00378363"></td>
          <td>3S</td><td>CEO</td><td>060310</td><td>industry</td></tr>
        </tbody></table>''',
        (f"{DART_API}/company.json", (("corp_code", "00378363"),)): {
            "status": "000", "corp_code": "00378363", "corp_name": "3S", "stock_code": "060310", "acc_mt": "03"
        },
        (f"{DART_API}/list.json", tuple(sorted(list_params.items()))): {
            "status": "000", "total_page": 1,
            "list": [
                {"rcept_no": receipt, "rcept_dt": "20250618", "report_nm": "사업보고서 (2025.03)", "corp_code": "00378363"},
                {"rcept_no": "20250619000208", "rcept_dt": "20250619", "report_nm": "[정정] 사업보고서 (2025.03)", "corp_code": "00378363", "rm": "U"},
            ],
        },
        (f"{DART_API}/document.xml", (("rcept_no", receipt),)): zipped("report.xml", "<report><p>Original report</p></report>".encode()),
        (f"{DART_API}/fnlttXbrl.xml", (("rcept_no", receipt), ("reprt_code", "11011"))): zipped("facts.xbrl", xbrl("KRW")),
    }
    transport = Transport(responses)
    return OpenDARTProvider(api_key="private", transport=transport), transport


def test_open_dart_ticker_annual_document_provenance_and_amendment():
    provider, transport = _dart_provider()
    company = Company("060310", market="KR", provider=provider)
    assert company.entity.entity_id == "00378363"
    filings = list(company.filings(form="annual", start="2025-01-01", end="2025-12-31", include_amendments=False))
    assert len(filings) == 1
    filing = filings[0]
    assert filing.filing_id == "20250618000208"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.filing_date == date(2025, 6, 18)
    assert filing.period_end == date(2025, 3, 31)
    assert filing.provider_metadata["report_code"] == "11011"
    assert [doc.document_type for doc in filing.documents] == ["original", "xbrl"]
    assert filing.download().startswith(b"PK")
    assert "Original report" in filing.text()
    assert filing.documents[1].download().startswith(b"PK")
    assert "private" not in str(filing.metadata) + str(filing.documents) + str(filing.provenance)
    assert all("private" not in str(call) for call in transport.calls)
    fact = filing.facts[0]
    assert fact.concept_raw == "gaap:Revenue"
    assert fact.period_start == date(2024, 4, 1)
    assert fact.period_end == date(2025, 3, 31)
    assert fact.dimensions == {"gaap:RegionAxis": "gaap:AsiaMember"}
    assert "facts.xbrl" in fact.source_location
    assert fact.provenance.source_id.startswith(filing.filing_id + ":facts.xbrl:")


def test_open_dart_english_semiannual_does_not_match_annual_filter():
    provider, transport = _dart_provider()
    response = next(value for (url, _), value in transport.responses.items()
                    if url.endswith("/list.json"))
    response["list"] = [
        {"rcept_no": "20250930000208", "rcept_dt": "20250930",
         "report_nm": "Semi-annual Report (2025.09)", "corp_code": "00378363"},
        {"rcept_no": "20250618000208", "rcept_dt": "20250618",
         "report_nm": "Annual Report (2025.03)", "corp_code": "00378363"},
    ]
    company = Company("060310", market="KR", provider=provider)
    annual = company.filings(form="annual", start="2025-01-01", end="2025-12-31").head(2)
    interim = company.filings(form="interim", start="2025-01-01", end="2025-12-31").head(2)

    assert [filing.filing_id for filing in annual] == ["20250618000208"]
    assert [filing.filing_id for filing in interim] == ["20250930000208"]
    assert interim[0].filing_type_normalized == "INTERIM"
    assert interim[0].provider_metadata["report_code"] == "11012"


@pytest.mark.parametrize("title", [
    "Semi-annual Report (2025.09)", "Semiannual Report (2025.09)",
    "Half-Year Report (2025.09)", "Half-Yearly Report (2025.09)",
])
def test_open_dart_english_interim_titles_are_not_annual(title):
    from opencorpfilings.providers.open_dart import _category

    assert _category(title)[0] == "interim"


def test_open_dart_streams_original_and_xbrl_without_buffering(tmp_path):
    provider, _ = _dart_provider()
    documents = Company("060310", market="KR", provider=provider).filings(
        form="annual", start="2025-01-01", end="2025-12-31", include_amendments=False,
    ).latest().documents
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.params["crtfc_key"] == "private"
        return httpx.Response(200, content=zipped("report.xml", b"<report>source</report>"))

    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    for document in documents:
        target = tmp_path / document.filename
        assert document.download(target) == target
        assert target.stat().st_size > 0
        assert document._cached_bytes is None
    assert len(requests) == 2
    assert all("private" not in document.source_url for document in documents)


def test_open_dart_saved_archives_support_text_and_facts_without_buffering(tmp_path):
    provider, transport = _dart_provider()
    filing = Company("060310", market="KR", provider=provider).filings(
        form="annual", start="2025-01-01", end="2025-12-31", include_amendments=False,
    ).latest()
    original, xbrl_document = filing.documents
    original.download(tmp_path / "original.zip")
    xbrl_document.download(tmp_path / "facts.zip")
    calls = len(transport.calls)
    assert "Original report" in filing.text()
    assert filing.facts[0].concept_raw == "gaap:Revenue"
    assert original._cached_bytes is None
    assert xbrl_document._cached_bytes is None
    assert len(transport.calls) == calls


@pytest.mark.parametrize("status,error,message", [
    ("013", DownloadError, "013"),
    ("020", RateLimitError, "020"),
    ("800", SourceUnavailableError, "maintenance"),
])
def test_open_dart_streamed_xml_error_preserves_target(tmp_path, status, error, message):
    provider, _ = _dart_provider()
    document = Company("060310", market="KR", provider=provider).filings(
        form="annual", start="2025-01-01", end="2025-12-31", include_amendments=False,
    ).latest().primary_document
    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=f"<result><status>{status}</status></result>".encode()),
    )))
    target = tmp_path / "original.zip"
    target.write_bytes(b"existing")
    with pytest.raises(error, match=message):
        document.download(target)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


def test_open_dart_streamed_damaged_zip_preserves_target(tmp_path):
    provider, _ = _dart_provider()
    document = Company("060310", market="KR", provider=provider).filings(
        form="annual", start="2025-01-01", end="2025-12-31", include_amendments=False,
    ).latest().primary_document
    damaged = zipped("report.xml", b"original report").replace(b"original report", b"damaged report!")
    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=damaged),
    )))
    target = tmp_path / "original.zip"
    target.write_bytes(b"existing")
    with pytest.raises(DownloadError, match="invalid original ZIP"):
        document.download(target)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


def test_open_dart_rejects_filing_row_for_another_issuer():
    provider, transport = _dart_provider()
    key = next(key for key in transport.responses if key[0].endswith("/list.json"))
    transport.responses[key]["list"][0]["corp_code"] = "99999999"
    company = Company("060310", market="KR", provider=provider)
    with pytest.raises(ProviderError, match="another issuer"):
        company.filings(start="2025-01-01", end="2025-12-31").latest()


def test_open_dart_english_name_search_uses_official_english_selector():
    provider, transport = _dart_provider()
    transport.responses[(CORP_SEARCH_EN, (("likeYn", "Y"), ("textCrpNm", "Samsung Electronics")))] = b'''<table class="tb"><tbody>
      <tr><td><input name="hiddenCikCD1" value="00126380"></td>
      <td>SAMSUNG ELECTRONICS</td><td>KOSPI</td><td>005930</td><td>industry</td></tr>
      <tr><td><input name="hiddenCikCD2" value="00252074"></td>
      <td>SAMSUNG ELECTRONICS SALES</td><td>OTHERS</td><td></td><td>industry</td></tr>
    </tbody></table>'''
    matches = search_companies("Samsung Electronics", market="KR", provider=provider)
    assert [(entity.entity_id, entity.name) for entity in matches] == [
        ("00126380", "SAMSUNG ELECTRONICS"),
        ("00252074", "SAMSUNG ELECTRONICS SALES"),
    ]
    assert matches[0].source_url.startswith(CORP_SEARCH_EN)
    assert not any(url.endswith("corpCode.xml") for url, _ in transport.calls)


def test_open_dart_english_selector_miss_falls_back_to_registry_alias():
    provider, transport = _dart_provider()
    provider._registry = [{"corp_code": "00126380", "corp_name": "Samsung Electronics",
                           "corp_eng_name": "Samsung Electronics Co Ltd", "stock_code": "005930"}]
    transport.responses[(CORP_SEARCH_EN, (("likeYn", "Y"),
                                          ("textCrpNm", "Samsung Electronics Co Ltd")))] = (
        b'<table class="tb"><tbody></tbody></table>')
    matches = search_companies("Samsung Electronics Co Ltd", market="KR", provider=provider)
    assert [entity.entity_id for entity in matches] == ["00126380"]
    assert matches[0].provenance.source_url == f"{DART_API}/corpCode.xml"


def test_open_dart_issuer_search_reuses_official_registry_without_profile_fetch():
    provider, transport = _dart_provider()
    for query in ("3s", "no such issuer"):
        transport.responses[(CORP_SEARCH_EN, (("likeYn", "Y"), ("textCrpNm", query)))] = b"<html/>"
    matches = search_companies("3s", market="KR", provider=provider)
    assert [(item.entity_id, item.name, item.tickers) for item in matches] == [
        ("00378363", "3S", ("060310",))]
    assert matches[0].provenance.source_url == f"{DART_API}/corpCode.xml"
    assert search_companies("060310", market="KR", provider=provider, limit=1)[0].entity_id == "00378363"
    assert search_companies("no such issuer", market="KR", provider=provider) == []
    assert Company(matches[0].entity_id, market="KR", provider=provider).entity.name == "3S"
    assert Company(matches[0], provider=provider).filings(
        form="annual", start="2025-01-01", end="2025-12-31").latest().entity_id == matches[0].entity_id
    assert [url for url, _ in transport.calls].count(f"{DART_API}/corpCode.xml") == 1
    assert [url for url, _ in transport.calls].count(f"{DART_API}/company.json") == 1


def test_open_dart_search_ranks_exact_name_before_prefix_and_limits_results():
    provider, transport = _dart_provider()
    transport.responses[(CORP_SEARCH_EN, (("likeYn", "Y"), ("textCrpNm", "3s")))] = b"<html/>"
    provider._registry = [
        {"corp_code": "00000001", "corp_name": "3S Technologies", "stock_code": ""},
        {"corp_code": "00378363", "corp_name": "3S", "stock_code": "060310"},
    ]
    assert [item.entity_id for item in provider.search_entities("3s", limit=1)] == ["00378363"]


def test_open_dart_exact_ticker_uses_small_official_search_without_registry():
    provider, transport = _dart_provider()
    transport.responses[(CORP_SEARCH, (("textCrpNm", "060310"),))] = b'''<table class="tb"><tbody>
      <tr><td><input name="hiddenCikCD1" value="00378363"></td>
      <td>3S</td><td>CEO</td><td>060310</td><td>industry</td></tr>
      <tr><td><input name="hiddenCikCD2" value="99999999"></td>
      <td>Unrelated</td><td>CEO</td><td>160310</td><td>industry</td></tr>
    </tbody></table>'''
    entity = provider.resolve_entity("060310")
    assert entity.entity_id == "00378363"
    assert [url for url, _ in transport.calls] == [CORP_SEARCH, f"{DART_API}/company.json"]


def test_open_dart_korean_name_search_uses_bounded_selector_and_source_provenance():
    provider, transport = _dart_provider()
    query = "\uc0bc\uc131"
    transport.responses[(CORP_SEARCH, (("likeYn", "Y"), ("textCrpNm", query)))] = (
        '<table class="tb"><tbody>'
        '<tr><td><input name="hiddenCikCD1" value="00126380">'
        '<input name="hiddenCikNM1" value="\uc0bc\uc131\uc804\uc790"></td>'
        '<td><span>Y</span>\uc0bc\uc131\uc804\uc790</td><td>CEO</td><td>005930</td><td>industry</td></tr>'
        '<tr><td><input name="hiddenCikCD2" value="00893765">'
        '<input name="hiddenCikNM2" value="\uc0bc\uc131"></td>'
        '<td><span>E</span>\uc0bc\uc131</td><td>CEO</td><td></td><td>industry</td></tr>'
        '</tbody></table><div class="pageInfo">[1/1] [2]</div>'
    ).encode("utf-8")
    matches = search_companies(query, market="KR", provider=provider, limit=2)
    assert [(item.entity_id, item.name) for item in matches] == [
        ("00893765", "\uc0bc\uc131"), ("00126380", "\uc0bc\uc131\uc804\uc790")]
    assert matches[1].tickers == ("005930",)
    assert all(item.provenance.source_url.startswith(CORP_SEARCH + "?") for item in matches)
    assert [url for url, _ in transport.calls] == [CORP_SEARCH]


def test_open_dart_numeric_search_skips_full_registry():
    provider, transport = _dart_provider()
    stock = search_companies("060310", market="KR", provider=provider)
    corp = search_companies("00378363", market="KR", provider=provider)
    assert [item.entity_id for item in stock] == ["00378363"]
    assert [item.entity_id for item in corp] == ["00378363"]
    assert [url for url, _ in transport.calls] == [
        CORP_SEARCH, f"{DART_API}/company.json",
    ]


def test_open_dart_selector_preserves_six_character_source_stock_codes():
    provider, transport = _dart_provider()
    query = "\uc0bc\uc131"
    transport.responses[(CORP_SEARCH, (("likeYn", "Y"), ("textCrpNm", query)))] = (
        '<table class="tb"><tbody>'
        '<tr><td><input name="hiddenCikCD1" value="12345678">'
        '<input name="hiddenCikNM1" value="\uc0bc\uc131\uc608\uc2dc"></td>'
        '<td>\uc0bc\uc131\uc608\uc2dc</td><td>CEO</td><td>0044K0</td><td>industry</td></tr>'
        '</tbody></table>'
    ).encode("utf-8")
    matches = search_companies(query, market="KR", provider=provider)
    assert [(item.entity_id, item.tickers) for item in matches] == [
        ("12345678", ("0044K0",))]
    assert [url for url, _ in transport.calls] == [CORP_SEARCH]


def test_open_dart_alphanumeric_stock_code_resolves_and_checks_profile():
    provider, transport = _dart_provider()
    transport.responses[(CORP_SEARCH, (("textCrpNm", "0044K0"),))] = (
        '<table class="tb"><tbody><tr><td>'
        '<input name="hiddenCikCD1" value="01910759">'
        '<input name="hiddenCikNM1" value="Example"></td>'
        '<td>Example</td><td>CEO</td><td>0044K0</td><td>industry</td>'
        '</tr></tbody></table>'
    ).encode("utf-8")
    transport.responses[(f"{DART_API}/company.json", (("corp_code", "01910759"),))] = {
        "status": "000", "corp_code": "01910759", "corp_name": "Example", "stock_code": "0044K0",
    }
    assert Company("0044k0", market="KR", provider=provider).entity.entity_id == "01910759"
    assert [url for url, _ in transport.calls] == [CORP_SEARCH, f"{DART_API}/company.json"]


def test_open_dart_ticker_search_requires_exact_row_and_matching_profile():
    provider, transport = _dart_provider()
    transport.responses[(CORP_SEARCH, (("textCrpNm", "060310"),))] = b'''<table class="tb"><tbody>
      <tr><td><input name="hiddenCikCD1" value="00378363"></td>
      <td>Different</td><td>CEO</td><td>160310</td><td>industry</td></tr>
    </tbody></table>'''
    with pytest.raises(EntityNotFoundError, match="stock code 060310"):
        provider.resolve_entity("060310")
    transport.responses[(CORP_SEARCH, (("textCrpNm", "060310"),))] = b'''<table class="tb"><tbody>
      <tr><td><input name="hiddenCikCD1" value="00378363"></td>
      <td>3S</td><td>CEO</td><td>060310</td><td>industry</td></tr>
    </tbody></table>'''
    transport.responses[(f"{DART_API}/company.json", (("corp_code", "00378363"),))]["stock_code"] = "160310"
    with pytest.raises(ParseError, match="does not match stock code"):
        provider.resolve_entity("060310")


def test_open_dart_ticker_search_falls_back_to_official_registry_on_changed_markup():
    provider, transport = _dart_provider()
    transport.responses[(CORP_SEARCH, (("textCrpNm", "060310"),))] = b"<html><body>Source unavailable</body></html>"
    assert provider.resolve_entity("060310").entity_id == "00378363"
    assert [url for url, _ in transport.calls] == [
        CORP_SEARCH, f"{DART_API}/corpCode.xml", f"{DART_API}/company.json",
    ]


def test_open_dart_reports_missing_credentials_and_unavailable_package(monkeypatch):
    monkeypatch.delenv("OPENCORPFILINGS_DART_API_KEY", raising=False)
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    with pytest.raises(AuthenticationError, match="OPENCORPFILINGS_DART_API_KEY"):
        OpenDARTProvider()
    provider, transport = _dart_provider()
    company = Company("00378363", market="KR", provider=provider)
    filing = company.filings(form="annual", start="2025-01-01", end="2025-12-31", limit=1).latest()
    transport.responses[(f"{DART_API}/document.xml", (("rcept_no", filing.filing_id),))] = b"<result><status>013</status><message>No data</message></result>"
    with pytest.raises(DownloadError, match="no original"):
        filing.download()


def test_open_dart_accepts_existing_api_key_environment_name(monkeypatch):
    monkeypatch.delenv("OPENCORPFILINGS_DART_API_KEY", raising=False)
    monkeypatch.setenv("OPENDART_API_KEY", "existing-dart-key")
    provider = OpenDARTProvider()
    try:
        assert provider.api_key == "existing-dart-key"
    finally:
        provider.close()


def _edinet_provider():
    header = "EDINETコード,証券コード,提出者法人番号,提出者名,提出者名(英字)\n"
    registry = zipped("Edinetcode.csv", ("snapshot\n" + header + "E02144,72030,1180301010799,トヨタ自動車株式会社,Toyota Motor Corporation\n").encode("cp932"))
    filing = {
        "docID": "S100Y8NY", "edinetCode": "E02144", "secCode": "72030", "docTypeCode": "120",
        "docDescription": "有価証券報告書", "submitDateTime": "2025-06-25 15:00",
        "periodStart": "2024-04-01", "periodEnd": "2025-03-31",
        "withdrawalStatus": "0", "disclosureStatus": "0", "legalStatus": "1",
        "xbrlFlag": "1", "pdfFlag": "1", "attachDocFlag": "1", "englishDocFlag": "0", "csvFlag": "0",
    }
    responses = {
        (REGISTRY, ()): registry,
        (f"{EDINET_API}/documents.json", (("date", "2025-06-26"), ("type", 2))): {"metadata": {"status": "200"}, "results": []},
        (f"{EDINET_API}/documents.json", (("date", "2025-06-25"), ("type", 2))): {"metadata": {"status": "200"}, "results": [filing]},
        (f"{EDINET_API}/documents/S100Y8NY", (("type", 1),)): zipped_files({
            "XBRL/PublicDoc/report.htm": "<html><body><p>Filed revenue</p></body></html>".encode(),
            "XBRL/PublicDoc/report.xbrl": xbrl("JPY"),
        }),
        (f"{EDINET_API}/documents/S100Y8NY", (("type", 2),)): b"%PDF-1.7\n",
    }
    transport = Transport(responses)
    return EDINETProvider(api_key="private", transport=transport), transport


def test_edinet_ticker_daily_search_documents_and_text():
    provider, transport = _edinet_provider()
    company = Company("7203", market="JP", provider=provider)
    assert company.entity.entity_id == "E02144"
    filing = company.filings(form="annual", start="2025-06-25", end="2025-06-26").latest()
    assert filing.filing_id == "S100Y8NY"
    assert filing.filing_type_raw == "120"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.filing_date == date(2025, 6, 25)
    assert filing.period_end == date(2025, 3, 31)
    assert [doc.document_type for doc in filing.documents] == ["original", "pdf", "attachments"]
    assert filing.select_document(document_id="S100Y8NY:2", language="ja") is filing.documents[1]
    assert "Filed revenue" in filing.text()
    assert filing.documents[1].download().startswith(b"%PDF-")
    assert "private" not in str(filing.metadata) + str(filing.documents) + str(filing.provenance)
    assert all("private" not in str(call) for call in transport.calls)
    fact = filing.facts[0]
    assert fact.concept_raw == "gaap:Revenue"
    assert fact.unit == "iso4217:JPY"
    assert fact.context_id == "c1"
    assert fact.dimensions == {"gaap:RegionAxis": "gaap:AsiaMember"}
    assert "PublicDoc/report.xbrl" in fact.source_location
    assert sum(url.endswith("/documents/S100Y8NY") and params.get("type") == 1
               for url, params in transport.calls) == 1


def test_edinet_streams_selected_zip_and_pdf_without_buffering(tmp_path):
    provider, _ = _edinet_provider()
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26",
    ).latest()
    documents = filing.documents
    package = zipped("report.txt", b"original filing")
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.params["Subscription-Key"] == "private"
        kind = int(request.url.params["type"])
        return httpx.Response(200, content=package if kind == 1 else b"%PDF-1.7\noriginal")

    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    for document, expected in ((documents[0], package), (documents[1], b"%PDF-1.7\noriginal")):
        target = tmp_path / document.filename
        assert document.download(target) == target
        assert target.read_bytes() == expected
        assert document._cached_bytes is None
        assert document.sha256()
    assert len(requests) == 2


def test_edinet_saved_original_supports_text_and_facts_without_buffering(tmp_path, monkeypatch):
    from opencorpfilings import models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    provider, transport = _edinet_provider()
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26",
    ).latest()
    original = filing.primary_document
    original.download(tmp_path / "original.zip")
    calls = len(transport.calls)
    assert "Filed revenue" in filing.text()
    assert filing.facts[0].concept_raw == "gaap:Revenue"
    assert original._cached_bytes is None
    assert all(member._cached_bytes is None for member in original.members
               if member.entry_path.lower().endswith((".xbrl", ".xml")))
    assert len(transport.calls) == calls


def test_edinet_streamed_zip_crc_failure_keeps_existing_target(tmp_path):
    provider, _ = _edinet_provider()
    document = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26",
    ).latest().primary_document
    damaged = zipped("report.txt", b"original filing").replace(b"original filing", b"corrupted filing")
    provider.transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=damaged),
    )))
    target = tmp_path / "original.zip"
    target.write_bytes(b"existing")
    with pytest.raises(ProviderError, match="invalid ZIP"):
        document.download(target)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


def test_edinet_exposes_source_file_date_when_submission_date_differs():
    provider, transport = _edinet_provider()
    key = (f"{EDINET_API}/documents.json", (("date", "2025-06-25"), ("type", 2)))
    row = {**transport.responses[key]["results"][0], "submitDateTime": "2025-06-24 15:00"}
    transport.responses[key] = {"metadata": {"status": "200"}, "results": [row]}
    collection = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-25",
    )
    filing = collection.latest()
    assert collection.order_basis == "source_file_date"
    assert filing.filing_date == date(2025, 6, 24)
    assert filing.provider_metadata["source_file_date"] == "2025-06-25"
    assert filing.provenance.raw == row


def test_edinet_daily_list_reuses_keyed_metadata_in_memory(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"metadata": {"status": "200"}, "results": []})

    transport = HttpTransport(cache_dir=tmp_path,
                              client=httpx.Client(transport=httpx.MockTransport(handle)))
    provider = EDINETProvider(api_key="fixture-key", transport=transport)
    day = date(2025, 6, 25)
    assert provider._daily(day) == []
    assert provider._daily(day) == []
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_edinet_reuses_past_days_even_when_the_api_says_no_cache():
    # Live documents.json answers Cache-Control: no-cache, so transport caching never applied.
    calls = []

    def handle(request):
        calls.append(request.url.params["date"])
        return httpx.Response(200, json={"metadata": {"status": "200"}, "results": []},
                              headers={"Cache-Control": "no-cache", "Pragma": "no-cache", "Expires": "-1"})

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    provider = EDINETProvider(api_key="fixture-key", transport=transport)
    past = date(2025, 6, 25)
    assert provider._daily(past) == [] and provider._daily(past) == []
    assert calls == ["2025-06-25"]
    for offset in range(1, 200):
        provider._daily(date(2025, 1, 1) - timedelta(days=offset))
    assert len(provider._days) <= 90


def test_edinet_daily_discovery_prefetches_in_order_without_skipping_days():
    from datetime import timedelta
    from threading import Lock
    import time

    provider, transport = _edinet_provider()
    end = date(2025, 6, 29)
    source = transport.responses[(f"{EDINET_API}/documents.json", (("date", "2025-06-25"), ("type", 2)))]["results"][0]
    lock = Lock()
    active = 0
    peak = 0
    original = transport.get_json

    def delayed_get_json(url, *, params, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)
            return original(url, params=params, **kwargs)
        finally:
            with lock:
                active -= 1

    for offset in range(5):
        day = end - timedelta(days=offset)
        transport.responses[(f"{EDINET_API}/documents.json", (("date", day.isoformat()), ("type", 2)))] = {
            "metadata": {"status": "200"}, "results": [source] if offset == 4 else [],
        }
    transport.get_json = delayed_get_json
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-29",
    ).latest()
    assert filing.filing_id == "S100Y8NY"
    assert peak > 1
    queried = {params["date"] for url, params in transport.calls if url.endswith("documents.json")}
    assert queried == {str(end - timedelta(days=offset)) for offset in range(5)}


def test_edinet_latest_waits_for_newer_day_even_when_older_response_arrives_first():
    import time

    provider, transport = _edinet_provider()
    source = transport.responses[(f"{EDINET_API}/documents.json", (("date", "2025-06-25"), ("type", 2)))]["results"][0]
    newer = {**source, "docID": "S100Y8NZ", "submitDateTime": "2025-06-27 15:00"}
    older = {**source, "submitDateTime": "2025-06-28 15:00"}
    for day, rows in (("2025-06-29", [newer]), ("2025-06-28", [older]),
                      ("2025-06-27", []), ("2025-06-26", [])):
        transport.responses[(f"{EDINET_API}/documents.json", (("date", day), ("type", 2)))] = {
            "metadata": {"status": "200"}, "results": rows,
        }
    original = transport.get_json

    def delayed_get_json(url, *, params, **kwargs):
        if params["date"] == "2025-06-29":
            time.sleep(0.04)
        return original(url, params=params, **kwargs)

    transport.get_json = delayed_get_json
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-29",
    ).latest()
    assert filing.filing_id == "S100Y8NZ"
    assert filing.filing_date == date(2025, 6, 27)
    assert filing.provider_metadata["source_file_date"] == "2025-06-29"
    queried = [params["date"] for url, params in transport.calls if url.endswith("documents.json")]
    assert len(queried) == 4
    assert "2025-06-25" not in queried


def test_edinet_correction_event_is_not_a_second_filing():
    provider, transport = _edinet_provider()
    key = (f"{EDINET_API}/documents.json", (("date", "2025-06-25"), ("type", 2)))
    original = {**transport.responses[key]["results"][0], "docInfoEditStatus": "2",
                "periodStart": "2024-05-01"}
    event = {**original, "docInfoEditStatus": "1", "opeDateTime": "2025-06-26 09:30"}
    transport.responses[key] = {"metadata": {"status": "200"}, "results": [original]}
    transport.responses[(f"{EDINET_API}/documents.json", (("date", "2025-06-26"), ("type", 2)))] = {
        "metadata": {"status": "200"}, "results": [event],
    }
    filings = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26",
    ).head(2)
    assert [filing.filing_id for filing in filings] == ["S100Y8NY"]
    assert filings[0].period_start == date(2024, 5, 1)
    assert filings[0].provider_metadata["docInfoEditStatus"] == "2"


@pytest.mark.parametrize(("field", "event_status"), [
    ("disclosureStatus", "1"), ("disclosureStatus", "3"), ("withdrawalStatus", "1"),
])
def test_edinet_administrative_event_is_not_a_second_filing(field, event_status):
    provider, transport = _edinet_provider()
    key = (f"{EDINET_API}/documents.json", (("date", "2025-06-25"), ("type", 2)))
    original = transport.responses[key]["results"][0]
    event = {**original, field: event_status,
             "opeDateTime": "2025-06-26 09:30"}
    transport.responses[(f"{EDINET_API}/documents.json", (("date", "2025-06-26"), ("type", 2)))] = {
        "metadata": {"status": "200"}, "results": [event],
    }
    filings = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26",
    ).head(2)
    assert [filing.filing_id for filing in filings] == ["S100Y8NY"]


def test_edinet_withheld_original_keeps_source_status_without_original_documents():
    provider, transport = _edinet_provider()
    key = (f"{EDINET_API}/documents.json", (("date", "2025-06-25"), ("type", 2)))
    original = {**transport.responses[key]["results"][0], "disclosureStatus": "2"}
    transport.responses[key] = {"metadata": {"status": "200"}, "results": [original]}
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-25",
    ).latest()
    assert filing.filing_id == "S100Y8NY"
    assert filing.provider_metadata["disclosureStatus"] == "2"
    assert filing.documents == []


def test_edinet_issuer_search_matches_english_name_and_reuses_registry():
    provider, transport = _edinet_provider()
    matches = search_companies("Toyota Motor", market="JP", provider=provider)
    assert len(matches) == 1
    assert matches[0].entity_id == "E02144"
    assert matches[0].tickers == ("7203",)
    assert matches[0].provenance.source_url == REGISTRY
    assert search_companies("7203", market="JP", provider=provider, limit=1)[0].entity_id == "E02144"
    assert search_companies("ﾄﾖﾀ", market="JP", provider=provider, limit=1)[0].entity_id == "E02144"
    assert search_companies("not a listed issuer", market="JP", provider=provider) == []
    assert Company(matches[0].entity_id, market="JP", provider=provider).entity.entity_id == "E02144"
    assert [url for url, _ in transport.calls] == [REGISTRY]


def test_edinet_package_without_structured_facts_is_explicit():
    provider, transport = _edinet_provider()
    transport.responses[(f"{EDINET_API}/documents/S100Y8NY", (("type", 1),))] = zipped(
        "XBRL/PublicDoc/report.htm", b"<p>Inline-only</p>"
    )
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26"
    ).latest()
    with pytest.raises(UnsupportedCapabilityError, match="no readable classic XBRL or XML iXBRL"):
        _ = filing.facts


def test_edinet_inline_only_package_exposes_raw_tags():
    provider, transport = _edinet_provider()
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26"
    ).latest()
    transport.responses[(f"{EDINET_API}/documents/S100Y8NY", (("type", 1),))] = zipped(
        "XBRL/PublicDoc/report.xhtml", XHTML
    )
    facts = filing.facts
    assert len(facts) == 3
    assert facts[0].concept_raw == "ex:Assets"
    assert "::XBRL/PublicDoc/report.xhtml#ix-fact-" in facts[0].source_location


def test_edinet_large_inline_member_uses_bounded_common_extraction():
    provider, transport = _edinet_provider()
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26"
    ).latest()
    content = XHTML.replace(b"<head>", b"<head><!--" + b"x" * 50_000_000 + b"-->", 1)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("XBRL/PublicDoc/report.xhtml", content)
    transport.responses[(f"{EDINET_API}/documents/S100Y8NY", (("type", 1),))] = buffer.getvalue()
    assert [fact.concept_raw for fact in filing.facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]
    assert filing.primary_document.members[0]._cached_bytes is None


def test_edinet_missing_credentials(monkeypatch):
    monkeypatch.delenv("OPENCORPFILINGS_EDINET_API_KEY", raising=False)
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    with pytest.raises(AuthenticationError, match="OPENCORPFILINGS_EDINET_API_KEY"):
        EDINETProvider()


def test_edinet_accepts_existing_api_key_environment_name(monkeypatch):
    monkeypatch.delenv("OPENCORPFILINGS_EDINET_API_KEY", raising=False)
    monkeypatch.setenv("EDINET_API_KEY", "existing-edinet-key")
    provider = EDINETProvider()
    try:
        assert provider.api_key == "existing-edinet-key"
    finally:
        provider.close()


@pytest.mark.parametrize(
    ("provider_type", "namespaced", "existing"),
    [
        (OpenDARTProvider, "OPENCORPFILINGS_DART_API_KEY", "OPENDART_API_KEY"),
        (EDINETProvider, "OPENCORPFILINGS_EDINET_API_KEY", "EDINET_API_KEY"),
    ],
)
def test_api_key_precedence_is_explicit_then_namespaced_then_existing(
    monkeypatch, provider_type, namespaced, existing,
):
    monkeypatch.setenv(namespaced, "namespaced-key")
    monkeypatch.setenv(existing, "existing-key")
    provider = provider_type()
    try:
        assert provider.api_key == "namespaced-key"
    finally:
        provider.close()
    provider = provider_type(api_key="explicit-key")
    try:
        assert provider.api_key == "explicit-key"
    finally:
        provider.close()


@pytest.mark.parametrize(
    ("code", "category"),
    [("120", "annual"), ("130", "annual"), ("140", "quarterly"), ("150", "quarterly"),
     ("160", "interim"), ("170", "interim"), ("180", "current"), ("190", "current")],
)
def test_edinet_form_categories_keep_source_codes(code, category):
    assert edinet_category(code) == category


def test_open_dart_category_requests_ask_the_source_for_that_report_type_only():
    # Samsung had 3,602 disclosures since 2025-01-01; A001 returned its 2 annual reports.
    provider, transport = _dart_provider()
    company = Company("060310", market="KR", provider=provider)
    company.filings(form="annual", start="2025-01-01", end="2025-12-31").latest()
    sent = [params for url, params in transport.calls if url.endswith("/list.json")]
    assert sent and all(params["pblntf_detail_ty"] == "A001" for params in sent)
    transport.calls.clear()
    list(company.filings(start="2025-01-01", end="2025-12-31"))
    assert all("pblntf_detail_ty" not in params for url, params in transport.calls if url.endswith("/list.json"))


def test_korea_and_japan_use_fixed_utc_plus_nine_without_tz_database():
    from datetime import timedelta
    from opencorpfilings.providers import edinet, open_dart

    assert edinet._JST.utcoffset(None) == timedelta(hours=9)
    assert open_dart._KST.utcoffset(None) == timedelta(hours=9)


@pytest.mark.parametrize(("doc_type", "start", "end", "expected"), [
    ("120", "2025-04-01", "2026-03-31", ("2025-04-01", "2026-03-31")),
    ("160", "2025-04-01", "2026-03-31", ("2025-04-01", "2025-09-30")),
    ("170", "2024-01-01", "2024-12-31", ("2024-01-01", "2024-06-30")),
    ("140", "2024-04-01", "2025-03-31", (None, None)),
])
def test_edinet_report_period_is_the_report_not_the_fiscal_year(doc_type, start, end, expected):
    # Toyota's half-year report S100WYZE lists periodStart/End 2025-04-01/2026-03-31: the fiscal year.
    from opencorpfilings.providers.edinet import _report_period

    period = _report_period(doc_type, start, end)
    assert tuple(value.isoformat() if value else None for value in period) == expected


def test_edinet_opens_a_securities_code_with_a_letter():
    header = "EDINETコード,証券コード,提出者法人番号,提出者名,提出者名(英字)\n"
    registry = zipped("Edinetcode.csv", ("snapshot\n" + header + "E39999,130A0,1010001234567,株式会社ベリタス,Veritas Inc.\n").encode("cp932"))
    provider = EDINETProvider(api_key="private", transport=Transport({(REGISTRY, ()): registry}))
    company = Company("130a", market="JP", provider=provider)
    assert company.entity.entity_id == "E39999"
    assert company.entity.tickers == ("130A",)
    assert [entity.tickers for entity in provider.search_entities("130A")] == [("130A",)]


def test_edinet_repeated_scan_reuses_the_newest_days():
    calls = []

    def handle(request):
        calls.append(request.url.params["date"])
        return httpx.Response(200, json={"metadata": {"status": "200"}, "results": []},
                              headers={"Cache-Control": "no-cache"})  # as the live API answers

    provider = EDINETProvider(api_key="fixture-key", transport=HttpTransport(
        client=httpx.Client(transport=httpx.MockTransport(handle))))
    newest = date(2025, 6, 25)
    for _ in range(2):
        for offset in range(120):
            provider._daily(newest - timedelta(days=offset))
    assert len(calls) == 120 + 30


def test_edinet_text_hides_inline_xbrl_header_and_keeps_lines():
    provider, transport = _edinet_provider()
    key = (f"{EDINET_API}/documents/S100Y8NY", (("type", 1),))
    transport.responses[key] = zipped_files({"XBRL/PublicDoc/report.htm": (
        "<html><body><ix:header><ix:hidden>HIDDENFACT</ix:hidden></ix:header>"
        "<p>売上高<span>1,234</span>百万円</p><p>2025年3月期</p></body></html>").encode()})
    filing = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26").latest()
    assert filing.text() == "[XBRL/PublicDoc/report.htm]\n売上高1,234百万円\n2025年3月期"


def test_open_dart_html_text_skips_scripts():
    provider, transport = _dart_provider()
    key = (f"{DART_API}/document.xml", (("rcept_no", "20250618000208"),))
    transport.responses[key] = zipped("report.htm", "<html><script>var x;</script><p>매출액</p><p>영업이익</p></html>".encode())
    filing = Company("060310", market="KR", provider=provider).filings(
        form="annual", start="2025-01-01", end="2025-12-31", include_amendments=False).latest()
    assert filing.text() == "[report.htm]\n매출액\n영업이익"


def test_a_saved_package_is_hashed_once_while_its_members_are_read(tmp_path, monkeypatch):
    import hashlib

    provider, _ = _edinet_provider()
    original = Company("7203", market="JP", provider=provider).filings(
        form="annual", start="2025-06-25", end="2025-06-26").latest().primary_document
    original.download(tmp_path / "original.zip")
    digests = []
    real = hashlib.file_digest
    monkeypatch.setattr(hashlib, "file_digest", lambda *args, **kwargs: digests.append(1) or real(*args, **kwargs))
    for member in original.members:
        member.download()
    assert "Filed revenue" in original.members[0].text()
    assert len(digests) <= 1
    (tmp_path / "original.zip").write_bytes(b"PK\x03\x04 replaced")  # a changed file is verified again
    assert original.download(tmp_path / "original.zip") == tmp_path / "original.zip"
    assert len(digests) == 2
