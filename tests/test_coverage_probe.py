"""A coverage probe must retain per-issuer failures without fetching originals."""

import json
import sys
from types import SimpleNamespace

import pytest

from benchmarks import coverage_probe
from opencorpfilings import EntityNotFoundError, FilingNotFoundError


def test_probe_reports_each_stage_and_never_downloads(monkeypatch, capsys) -> None:
    class Document:
        source_url = "https://example.test/original"
        media_type = None

        def download(self):
            raise AssertionError("metadata probe must not download")

    class Filing:
        filing_id = "filing-1"
        source_url = "https://example.test/filing"
        filing_date = None
        documents = [Document(), SimpleNamespace(
            source_url="https://example.test/other", media_type="application/pdf"
        )]

    class Company:
        provider = SimpleNamespace(supports=lambda capability: False)

        def __init__(self, identifier, *, market, **kwargs):
            self.identifier = identifier

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @property
        def entity(self):
            if self.identifier == "missing":
                raise EntityNotFoundError("not found")
            return SimpleNamespace(entity_id="entity-1", name="Test Issuer",
                                   source_url="https://example.test/issuer")

        def filings(self, **kwargs):
            if self.identifier == "empty":
                def absent():
                    raise FilingNotFoundError("no matching filing")

                return SimpleNamespace(latest=absent)
            return SimpleNamespace(latest=lambda: Filing())

    monkeypatch.setattr(coverage_probe, "Company", Company)
    monkeypatch.setattr(sys, "argv", ["coverage_probe.py", "US", "good", "missing", "empty"])

    assert coverage_probe.main() == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["status"] for row in rows] == ["ok", "error", "no_filing", "summary"]
    assert rows[0]["document_count"] == 2
    assert rows[0]["document_media_types"] == ["application/pdf", "unknown"]
    assert rows[0]["unknown_media_count"] == 1
    assert rows[0]["provenance"] is True
    assert rows[0]["entity_name"] == "Test Issuer"
    assert rows[0]["entity_source_url"] == "https://example.test/issuer"
    assert rows[0]["filing_source_url"] == "https://example.test/filing"
    assert rows[1]["failed_stage"] == "entity"
    assert rows[1]["error_type"] == "EntityNotFoundError"
    assert rows[2]["entity_id"] == "entity-1"
    assert rows[-1]["counts"] == {"ok": 1, "error": 1, "no_filing": 1}


def test_probe_rejects_unbounded_issuer_list(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["coverage_probe.py", "US", *[str(i) for i in range(21)]])
    with pytest.raises(SystemExit, match="2"):
        coverage_probe.main()


def test_probe_skips_document_listing_when_source_embeds_originals(monkeypatch, capsys) -> None:
    class Filing:
        filing_id = "source-1"
        filing_date = None
        source_url = "https://example.test/filing"

        @property
        def documents(self):
            raise AssertionError("listing would fetch original bytes")

    class Company:
        provider = SimpleNamespace(supports=lambda capability: capability == "document_listing_embeds_originals")
        entity = SimpleNamespace(entity_id="issuer-1", name="Issuer", source_url="https://example.test/issuer")

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def filings(self, **kwargs):
            return SimpleNamespace(latest=lambda: Filing())

    monkeypatch.setattr(coverage_probe, "Company", Company)
    monkeypatch.setattr(sys, "argv", ["coverage_probe.py", "CY", "issuer-1"])

    assert coverage_probe.main() == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[0]["status"] == "document_listing_requires_originals"
    assert rows[0]["filing_id"] == "source-1"
    assert "document_count" not in rows[0]
    assert rows[1]["counts"] == {"document_listing_requires_originals": 1}
