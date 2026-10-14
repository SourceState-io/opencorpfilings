"""The single-filing benchmark must distinguish source outages from completed runs."""

import json
import sys
from datetime import date
from types import SimpleNamespace

from benchmarks import provider_workflow
from opencorpfilings import SourceUnavailableError


def test_benchmark_reports_download_stage_and_selected_source_ids(monkeypatch, capsys) -> None:
    class Document:
        document_id = "original-1"
        media_type = None
        role = None

        def download(self):
            raise SourceUnavailableError("maintenance")

    class Filing:
        filing_id = "filing-1"
        filing_type_raw = None
        filing_type_normalized = None
        filing_date = None
        period_end = None
        amendment = None
        documents = [Document()]
        primary_document = documents[0]

    class Company:
        entity = SimpleNamespace(entity_id="entity-1", name="Entity", source_url="https://example.test/e")

        def __init__(self, identifier, *, market):
            assert (identifier, market) == ("005930", "KR")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def filings(self, **kwargs):
            assert kwargs["form"] == "annual"
            return SimpleNamespace(latest=lambda: Filing())

    monkeypatch.setattr(provider_workflow, "Company", Company)
    monkeypatch.setattr(sys, "argv", ["provider_workflow.py", "KR", "005930"])

    assert provider_workflow.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "error"
    assert report["failed_stage"] == "download"
    assert report["error_type"] == "SourceUnavailableError"
    assert report["entity_id"] == "entity-1"
    assert report["filing_id"] == "filing-1"
    assert report["document_id"] == "original-1"
    assert report["elapsed_seconds"] >= 0


def test_benchmark_reports_entity_failure_without_fabricating_ids(monkeypatch, capsys) -> None:
    def unavailable(*args, **kwargs):
        raise SourceUnavailableError("maintenance")

    monkeypatch.setattr(provider_workflow, "Company", unavailable)
    monkeypatch.setattr(sys, "argv", ["provider_workflow.py", "KR", "005930"])

    assert provider_workflow.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["failed_stage"] == "entity"
    assert "entity_id" not in report
    assert "filing_id" not in report


def test_benchmark_reports_empty_pdf_text_and_page_coverage(monkeypatch, capsys) -> None:
    class Document:
        document_id = "scanned-pdf"
        media_type = "application/pdf"
        role = "report"
        source_url = "https://example.test/original.pdf"
        provenance = SimpleNamespace(source_url=source_url)
        pages = (SimpleNamespace(text=""), SimpleNamespace(text=""))

        def download(self):
            return b"%PDF-fixture"

    class Filing:
        filing_id = "annual-1"
        filing_type_raw = None
        filing_type_normalized = None
        filing_date = None
        period_end = None
        amendment = None
        source_url = "https://example.test/annual-1"
        documents = (Document(),)
        primary_document = documents[0]

        def text(self):
            return ""

    class Company:
        entity = SimpleNamespace(entity_id="issuer-1", name="Issuer", source_url="https://example.test/i")

        def __init__(self, identifier, *, market):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def filings(self, **kwargs):
            return SimpleNamespace(latest=lambda: Filing())

    monkeypatch.setattr(provider_workflow, "Company", Company)
    monkeypatch.setattr(sys, "argv", ["provider_workflow.py", "UK", "issuer-1"])
    assert provider_workflow.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["text_status"] == "empty"
    assert report["pdf_page_count"] == 2
    assert report["pdf_pages_with_text"] == 0


def test_benchmark_records_selected_filing_identity_for_route_qualification(monkeypatch, capsys) -> None:
    class Document:
        document_id = "annual.zip"
        media_type = "application/zip"
        role = "report"
        source_url = "https://example.test/annual.zip"
        provenance = SimpleNamespace(source_url=source_url)

        def download(self):
            return b"PK\x03\x04fixture"

    class Filing:
        filing_id = "annual-2025"
        source_url = "https://example.test/annual-2025"
        filing_type_raw = "AFR"
        filing_type_normalized = "ANNUAL"
        filing_date = date(2026, 3, 31)
        period_end = date(2025, 12, 31)
        amendment = False
        documents = (Document(),)
        primary_document = documents[0]

        def text(self):
            return "Annual report"

    class Company:
        entity = SimpleNamespace(entity_id="issuer-1", name="Issuer One", source_url="https://example.test/issuer-1")

        def __init__(self, identifier, *, market):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def filings(self, **kwargs):
            return SimpleNamespace(latest=lambda: Filing())

    monkeypatch.setattr(provider_workflow, "Company", Company)
    monkeypatch.setattr(sys, "argv", ["provider_workflow.py", "FR", "issuer-1"])
    assert provider_workflow.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["entity_name"] == "Issuer One"
    assert report["entity_source_url"] == "https://example.test/issuer-1"
    assert report["filing_type_raw"] == "AFR"
    assert report["filing_type_normalized"] == "ANNUAL"
    assert report["filing_date"] == "2026-03-31"
    assert report["media_type"] == "application/zip"
    assert report["role"] == "report" and report["period_end"] == "2025-12-31"
    assert report["amendment"] is False and report["form"] == "annual"
    assert report["printable_ratio"] == 1.0


def test_benchmark_error_keeps_a_bounded_source_message(monkeypatch, capsys) -> None:
    def unavailable(*args, **kwargs):
        raise SourceUnavailableError("status 800: " + "x" * 1000)

    monkeypatch.setattr(provider_workflow, "Company", unavailable)
    monkeypatch.setattr(sys, "argv", ["provider_workflow.py", "KR", "005930"])
    assert provider_workflow.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["error"].startswith("status 800: ")
    assert len(report["error"]) <= 300
