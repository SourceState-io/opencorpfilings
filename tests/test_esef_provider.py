"""Offline checks for the bounded FR/FI filings.xbrl.org adapter."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from opencorpfilings import Company, DownloadError, EntityNotFoundError, FilingNotFoundError, ParseError, ProviderError, UnsupportedCapabilityError
from opencorpfilings.providers.esef import ESEFProvider, INDEX_COUNTRIES


LEI = "2138001CNF45JP5XZK38"
FR_LEI = "2138004KW8BV57III342"
BASE = "https://filings.xbrl.org"


def _original_zip() -> bytes:
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("original.txt", "source bytes")
    return payload.getvalue()


ORIGINAL_ZIP = _original_zip()


def _row(number: int, *, lei: str = LEI, country: str = "FI", added: str = "2024-01-30 09:48:32.830438") -> dict:
    return {
        "type": "filing",
        "id": str(number),
        "attributes": {
            "fxo_id": f"{lei}-2023-12-31-ESEF-{country}-{number}",
            "country": country,
            "period_end": "2023-12-31",
            "date_added": added,
            "processed": "2024-01-30 11:01:50.290927",
            "sha256": "88b0277f7a722087c72ba22479e136a061bc9837d95e9b1ec6100cfe0d22308e",
            "report_url": f"/{lei}/report-{number}.xhtml",
            "package_url": f"/{lei}/package-{number}.zip",
            "json_url": f"/{lei}/facts-{number}.json",
            "viewer_url": f"/{lei}/viewer-{number}.html",
        },
        "relationships": {"entity": {"links": {"related": f"/api/entities/{lei}"}}},
        "links": {"self": f"/api/filings/{number}"},
    }


class StubTransport:
    def __init__(self, *, lei: str = LEI, name: str = "KONE OYJ", rows: list[dict] | None = None) -> None:
        self.lei = lei
        self.name = name
        self.rows = rows if rows is not None else [_row(12309, lei=lei)]
        self.calls: list[tuple[str, dict | None]] = []

    def get_json(self, url: str, *, params: dict | None = None) -> dict:
        self.calls.append((url, params))
        if url == f"{BASE}/api/entities/{self.lei}":
            return {"data": {"id": "2499", "type": "entity", "attributes": {"name": self.name, "identifier": self.lei}}}
        if url == f"{BASE}/api/entities/{self.lei}/filings":
            size = int(params["page[size]"])
            number = int(params["page[number]"])
            start = (number - 1) * size
            return {
                "data": self.rows[start : start + size],
                "meta": {"count": len(self.rows)},
                "links": {"next": f"{BASE}/api/filings?page%5Bnumber%5D={number + 1}"},
            }
        if url.startswith(f"{BASE}/api/filings/"):
            filing_id = url.rsplit("/", 1)[-1]
            for row in self.rows:
                if row["id"] == filing_id:
                    return {"data": row}
            raise ProviderError(f"source returned HTTP 404 for {url}")
        raise AssertionError(f"unexpected JSON request: {url}")

    def get(self, url: str, **_: object) -> bytes:
        self.calls.append((url, None))
        if url.endswith(".zip"):
            return ORIGINAL_ZIP
        if url.endswith(".xhtml"):
            return b"<html><body><h1>KONE annual report</h1><p>Facts &amp; notes.</p><script>ignored()</script></body></html>"
        if url.endswith(".json"):
            return json.dumps({
                "documentInfo": {"taxonomy": ["https://example.com/taxonomy.xsd"]},
                "facts": {
                    "f1": {
                        "value": "100",
                        "dimensions": {
                            "concept": "ifrs-full:Revenue",
                            "entity": f"lei:{LEI}",
                            "period": "2023-01-01T00:00:00/2024-01-01T00:00:00",
                            "unit": "iso4217:EUR",
                            "ifrs-full:SegmentsAxis": "issuer:Europe",
                        },
                    },
                },
            }).encode()
        raise AssertionError(f"unexpected binary request: {url}")


def test_kone_workflow_keeps_index_time_distinct_from_filing_date() -> None:
    transport = StubTransport()
    transport.rows[0]["attributes"]["sha256"] = hashlib.sha256(ORIGINAL_ZIP).hexdigest()
    provider = ESEFProvider(market="FI", transport=transport)
    company = Company(LEI, market="FI", provider=provider)

    assert company.entity.entity_id == LEI
    assert company.entity.identifiers[0].kind == "LEI"
    collection = company.filings()
    assert collection.order_basis == "report_period"
    filing = collection.latest()
    assert filing.filing_id == "12309"
    assert filing.filing_date is None
    assert filing.filing_type_raw == "ESEF"
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.index_added_at == datetime(2024, 1, 30, 9, 48, 32, 830438)
    assert filing.period_end == date(2023, 12, 31)
    assert filing.provider_metadata["sha256"] == hashlib.sha256(ORIGINAL_ZIP).hexdigest()
    assert filing.provenance.source_url == f"{BASE}/api/filings/12309"

    assert [document.document_type for document in filing.documents] == ["report_xhtml", "source_package", "derived_xbrl_json"]
    assert filing.primary_document.media_type == "application/xhtml+xml"
    assert filing.documents[1].download() == ORIGINAL_ZIP
    assert filing.text() == "KONE annual report\nFacts & notes."
    fact = filing.facts[0]
    assert fact.concept_raw == "ifrs-full:Revenue"
    assert fact.value == "100"
    assert fact.unit == "iso4217:EUR"
    assert fact.period_start == date(2023, 1, 1)
    assert fact.period_end == date(2023, 12, 31)
    assert fact.dimensions["ifrs-full:SegmentsAxis"] == "issuer:Europe"
    assert fact.source_location == f"{BASE}/{LEI}/facts-12309.json#/facts/f1"


def test_pagination_stays_entity_scoped_and_filters_country() -> None:
    transport = StubTransport(rows=[_row(3, added="2025-01-01 00:00:00"), _row(2, country="FR"), _row(1)])
    provider = ESEFProvider(market="FI", transport=transport, page_size=2)
    filings = list(Company(LEI, market="FI", provider=provider).filings())
    assert [filing.filing_id for filing in filings] == ["3", "1"]
    page_calls = [call for call in transport.calls if call[0].endswith("/filings")]
    assert len(page_calls) == 2
    assert all(call[0] == f"{BASE}/api/entities/{LEI}/filings" for call in page_calls)
    assert page_calls[0][1]["sort"] == "-date_added"


def test_esef_listing_has_an_explicit_page_bound_without_harming_limited_reads() -> None:
    class UncountedTransport(StubTransport):
        def get_json(self, url: str, *, params: dict | None = None) -> dict:
            response = super().get_json(url, params=params)
            if url.endswith("/filings"):
                response.pop("meta")
            return response

    transport = UncountedTransport(rows=[_row(3), _row(2), _row(1)])
    # Ordering by report period reads the issuer's whole bounded listing first.
    bounded = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=transport, page_size=1, max_pages=4))
    assert [filing.filing_id for filing in bounded.filings().head(2)] == ["3", "2"]
    company = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=transport, page_size=1, max_pages=2))
    with pytest.raises(UnsupportedCapabilityError, match="2-page safety bound"):
        list(company.filings())
    with pytest.raises(ValueError, match="max_pages"):
        ESEFProvider(market="FI", max_pages=0)


def test_publicis_french_index_record_has_the_same_source_preserving_shape() -> None:
    transport = StubTransport(lei=FR_LEI, name="PUBLICIS GROUPE SA", rows=[_row(3750, lei=FR_LEI, country="FR")])
    filing = Company(FR_LEI, market="FR", provider=ESEFProvider(market="FR", transport=transport)).filings().latest()
    assert filing.jurisdiction == "FR"
    assert filing.filing_id == "3750"
    assert filing.filing_date is None
    assert filing.filing_type_normalized == "ANNUAL"
    assert filing.source_url.startswith(f"{BASE}/filing/{FR_LEI}-")


def test_captured_kone_jsonapi_record_is_read_offline() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "esef_kone_12309.json"
    captured = json.loads(fixture_path.read_text(encoding="utf-8"))["data"]
    filing = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=StubTransport(rows=[captured]))).filings().latest()
    assert filing.filing_id == "12309"
    assert filing.source_url == f"{BASE}/filing/{LEI}-2023-12-31-ESEF-FI-1"
    assert filing.index_added_at == datetime(2024, 1, 30, 9, 48, 32, 830438)
    assert filing.filing_date is None
    assert [document.document_type for document in filing.documents] == ["report_xhtml", "source_package", "derived_xbrl_json"]


def test_missing_json_representation_is_explicitly_unsupported() -> None:
    row = _row(12309)
    row["attributes"].pop("json_url")
    row["attributes"].pop("package_url")
    filing = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=StubTransport(rows=[row]))).filings().latest()
    with pytest.raises(UnsupportedCapabilityError, match="structured facts"):
        _ = filing.facts
    assert filing.text() == "KONE annual report\nFacts & notes."


def test_package_only_index_record_uses_original_report_for_text_and_raw_facts() -> None:
    row = _row(441, lei="31570010000000004460", country="SI")
    row["attributes"].pop("report_url")
    row["attributes"].pop("json_url")
    xhtml = b'''<html xmlns="http://www.w3.org/1999/xhtml"
        xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
        xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ex="https://example.test">
      <body><ix:header><ix:resources><xbrli:context id="c1"><xbrli:entity>
        <xbrli:identifier scheme="lei">31570010000000004460</xbrli:identifier>
      </xbrli:entity><xbrli:period><xbrli:instant>2020-12-31</xbrli:instant>
      </xbrli:period></xbrli:context></ix:resources></ix:header>
      <p>Original annual report <ix:nonNumeric name="ex:Note" contextRef="c1">Hello</ix:nonNumeric></p>
    </body></html>'''
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr("issuer/META-INF/catalog.xml", "<catalog/>")
        archive.writestr("issuer/reports/annual.xhtml", xhtml)
    row["attributes"]["sha256"] = hashlib.sha256(package.getvalue()).hexdigest()

    class PackageTransport(StubTransport):
        def get(self, url: str, **_: object) -> bytes:
            assert url.endswith("package-441.zip")
            return package.getvalue()

    lei = "31570010000000004460"
    provider = ESEFProvider(market="SI", transport=PackageTransport(lei=lei, rows=[row]))
    filing = Company(lei, market="SI", provider=provider).filings().latest()
    assert [document.document_type for document in filing.documents] == ["source_package"]
    assert "Original annual report Hello" in filing.text()
    assert len(filing.facts) == 1
    assert filing.facts[0].concept_raw == "ex:Note"
    assert "::issuer/reports/annual.xhtml#ix-fact-" in filing.facts[0].source_location


def test_package_only_record_keeps_facts_from_every_report_xhtml(monkeypatch) -> None:
    from opencorpfilings import models

    monkeypatch.setattr(models, "_STREAM_PARSE_MEMBER_BYTES", 1)
    row = _row(442, lei="31570010000000004460", country="SI")
    row["attributes"].pop("report_url")
    row["attributes"].pop("json_url")
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        for filename, concept in (("main.xhtml", "Main"), ("notes.xhtml", "Notes")):
            archive.writestr(f"issuer/reports/{filename}", f'''<html xmlns="http://www.w3.org/1999/xhtml"
                xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
                xmlns:xbrli="http://www.xbrl.org/2003/instance">
                <body><ix:header><ix:resources><xbrli:context id="c1"><xbrli:entity>
                <xbrli:identifier scheme="lei">31570010000000004460</xbrli:identifier>
                </xbrli:entity><xbrli:period><xbrli:instant>2020-12-31</xbrli:instant>
                </xbrli:period></xbrli:context></ix:resources></ix:header>
                <ix:nonNumeric name="ex:{concept}" contextRef="c1">{concept}</ix:nonNumeric>
                </body></html>''')
    row["attributes"]["sha256"] = hashlib.sha256(package.getvalue()).hexdigest()

    class PackageTransport(StubTransport):
        def get(self, url: str, **_: object) -> bytes:
            assert url.endswith("package-442.zip")
            return package.getvalue()

    lei = "31570010000000004460"
    filing = Company(lei, market="SI", provider=ESEFProvider(
        market="SI", transport=PackageTransport(lei=lei, rows=[row]))).filings().latest()
    assert [(fact.concept_raw, fact.provider_metadata["entry_path"]) for fact in filing.facts] == [
        ("ex:Main", "issuer/reports/main.xhtml"),
        ("ex:Notes", "issuer/reports/notes.xhtml"),
    ]
    assert all(member._cached_bytes is None for member in filing.primary_document.members)
    assert "Main" in filing.text()
    assert "Notes" in filing.text()


def test_source_package_rejects_index_checksum_mismatch() -> None:
    row = _row(12309)
    filing = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=StubTransport(rows=[row]))).filings().latest()
    with pytest.raises(DownloadError, match="SHA-256"):
        filing.select_document(document_type="source_package").download()


def test_source_package_saves_through_stream_with_index_checksum(tmp_path: Path) -> None:
    body = b"PK\x03\x04source-package"
    row = _row(441)
    row["attributes"]["sha256"] = hashlib.sha256(body).hexdigest()

    class StreamingTransport(StubTransport):
        stream_calls: list[tuple[str, bytes | None, str | None]] = []

        def get(self, url: str, **_: object) -> bytes:
            raise AssertionError("streamed save must not buffer the source ZIP")

        def get_to_file(self, url: str, path: Path, *, expected_prefix: bytes | None = None,
                        expected_sha256: str | None = None) -> Path:
            self.stream_calls.append((url, expected_prefix, expected_sha256))
            path.write_bytes(body)
            return path

    transport = StreamingTransport(rows=[row])
    filing = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=transport)).get_filing("441")
    document = filing.select_document(document_type="source_package")
    target = tmp_path / "source.zip"
    assert document.download(target) == target
    assert target.read_bytes() == body
    assert document._cached_bytes is None
    assert transport.stream_calls == [(document.source_url, b"PK\x03\x04", row["attributes"]["sha256"])]


@pytest.mark.parametrize("country", sorted(INDEX_COUNTRIES))
def test_captured_index_country_record_uses_common_document_contract(country: str) -> None:
    path = Path(__file__).parent / "fixtures" / "esef_index_country_samples.json"
    samples = {sample["country"]: sample for sample in json.loads(path.read_text(encoding="utf-8"))["samples"]}
    assert INDEX_COUNTRIES <= set(samples)
    sample = samples[country]
    lei = sample["lei"]
    transport = StubTransport(lei=lei, name=sample["name"], rows=[sample["filing"]])
    filing = Company(lei, market=country, provider=ESEFProvider(market=country, transport=transport)).filings().latest()
    assert filing.filing_id == sample["filing"]["id"]
    assert filing.entity_id == lei
    assert filing.jurisdiction == country
    assert filing.provenance.source_url == f"{BASE}/api/filings/{filing.filing_id}"
    package = filing.select_document(document_type="source_package")
    assert package.source_url.startswith(f"{BASE}/{lei}/")
    assert package.provider_metadata["index_sha256"] == sample["filing"]["attributes"]["sha256"]


def test_direct_index_filing_lookup_uses_one_record_request() -> None:
    transport = StubTransport(rows=[_row(441)])
    company = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=transport))
    filing = company.get_filing("441")
    assert filing.filing_id == "441"
    assert filing.entity_id == LEI
    assert [url for url, _ in transport.calls if url.endswith("/filings/441")] == [f"{BASE}/api/filings/441"]
    assert not any(url.endswith(f"/entities/{LEI}/filings") for url, _ in transport.calls)


@pytest.mark.parametrize("row", [_row(441, country="FR"), _row(441, lei=FR_LEI)])
def test_direct_index_lookup_rejects_another_country_or_issuer(row: dict) -> None:
    company = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=StubTransport(rows=[row])))
    with pytest.raises(FilingNotFoundError):
        company.get_filing("441")


def test_direct_index_lookup_rejects_invalid_or_absent_id() -> None:
    company = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=StubTransport(rows=[_row(441)])))
    with pytest.raises(FilingNotFoundError):
        company.get_filing("../../441")
    with pytest.raises(FilingNotFoundError):
        company.get_filing("999")


def test_direct_index_lookup_reports_missing_source_identity_as_parse_error() -> None:
    row = _row(441)
    row["attributes"].pop("fxo_id")
    company = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=StubTransport(rows=[row])))
    with pytest.raises(ParseError, match="fxo_id"):
        company.get_filing("441")


def test_issuer_mismatch_is_rejected() -> None:
    wrong = _row(12309)
    wrong["attributes"]["fxo_id"] = "OTHER-2023-12-31-ESEF-FI-1"
    provider = ESEFProvider(market="FI", transport=StubTransport(rows=[wrong]))
    with pytest.raises(ProviderError, match="issuer"):
        list(Company(LEI, market="FI", provider=provider).filings())


@pytest.mark.parametrize("kwargs", [{"form": "interim"}, {"start": "2024-01-01"}, {"end": "2024-12-31"}, {"include_amendments": False}])
def test_unsupported_source_semantics_fail_explicitly(kwargs: dict) -> None:
    company = Company(LEI, market="FI", provider=ESEFProvider(market="FI", transport=StubTransport()))
    with pytest.raises(UnsupportedCapabilityError):
        list(company.filings(**kwargs))


def test_invalid_lei_does_not_guess_identity() -> None:
    provider = ESEFProvider(market="FI", transport=StubTransport())
    with pytest.raises(EntityNotFoundError):
        provider.resolve_entity("KONE")
