"""One company's filings download into a resumable, source-linked folder, never unbounded."""

from datetime import date
import hashlib
import json

import pytest

from opencorpfilings import (
    Company, DownloadError, Entity, Filing, FilingDocument, FilingProvider, Provenance,
)


class Provider(FilingProvider):
    name = "fixture"
    market = "US"
    regulator = "Fixture Commission"
    capabilities = frozenset({"entity_lookup", "filing_discovery", "document_download"})
    identifies_amendments = True

    def __init__(self, broken=()):
        self.downloads = 0
        self.broken = set(broken)

    def resolve_entity(self, identifier):
        return Entity(identifier, "Fixture Inc", "US", self.name, "https://example.test/company")

    def iter_filings(self, entity, *, form=None, start=None, end=None, include_amendments=True, limit=None):
        for year in (2025, 2024, 2023):
            filing_id = f"0000-{year}:annual"
            filed = date(year + 1, 2, 1)
            if (start and filed < start) or (end and filed > end):
                continue
            url = f"https://example.test/{year}"
            yield Filing(filing_id, entity.entity_id, "US", self.name, self.regulator, url,
                         Provenance(self.name, self.regulator, "US", url, filing_id),
                         filing_type_raw="10-K", filing_type_normalized="ANNUAL", filing_date=filed,
                         period_end=date(year, 12, 31), amendment=False)

    def list_documents(self, filing):
        documents = []
        for name, role, primary in (("report.htm", "report", True), ("ex21.htm", "exhibit", False)):
            url = f"{filing.source_url}/{name}"
            documents.append(FilingDocument(f"{filing.filing_id}:{name}", filing.filing_id, name, url,
                                            Provenance(self.name, self.regulator, "US", url, name),
                                            media_type="text/html", role=role, is_primary=primary))
        return documents

    def download_document(self, document):
        if document.filing_id in self.broken:
            raise DownloadError("source returned HTTP 503")
        self.downloads += 1
        return f"<p>{document.document_id}</p>".encode()


def test_an_unbounded_history_is_refused(tmp_path):
    collection = Company("FIX", market="US", provider=Provider()).filings(form="annual")
    with pytest.raises(ValueError, match="all_history=True"):
        collection.download(tmp_path)


def test_bounded_download_saves_primary_reports_with_a_manifest(tmp_path):
    provider = Provider()
    result = Company("FIX", market="US", provider=provider).filings(form="annual", limit=2).download(tmp_path)
    assert result["downloaded"] == 2 and result["failed"] == 0 and result["skipped"] == 0
    saved = tmp_path / "0000-2025_annual" / "report.htm"
    assert saved.read_bytes() == b"<p>0000-2025:annual:report.htm</p>"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["filings"][0]
    assert entry["filing"]["filing_id"] == "0000-2025:annual"
    assert entry["filing"]["period_end"] == "2025-12-31"
    document = entry["documents"][0]
    assert document["source_url"] == "https://example.test/2025/report.htm"
    assert document["sha256"] == hashlib.sha256(saved.read_bytes()).hexdigest()
    assert document["path"] == "0000-2025_annual/report.htm" and document["role"] == "report"


def test_rerun_skips_verified_files_and_resumes(tmp_path):
    provider = Provider()
    company = Company("FIX", market="US", provider=provider)
    company.filings(form="annual", limit=2).download(tmp_path)
    result = company.filings(form="annual").download(tmp_path, all_history=True)
    assert result["skipped"] == 2 and result["downloaded"] == 1
    assert provider.downloads == 3


def test_one_failed_filing_is_recorded_and_the_rest_continue(tmp_path):
    provider = Provider(broken={"0000-2024:annual"})
    result = Company("FIX", market="US", provider=provider).filings(
        form="annual", start="2024-01-01").download(tmp_path)
    assert result["downloaded"] == 2 and result["failed"] == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    failed = [entry for entry in manifest["filings"] if entry["status"] == "failed"]
    assert failed[0]["filing"]["filing_id"] == "0000-2024:annual"
    assert "503" in failed[0]["error"]


def test_documents_can_be_widened_to_all_or_selected_roles(tmp_path):
    company = Company("FIX", market="US", provider=Provider())
    assert company.filings(form="annual", limit=1).download(tmp_path / "all", documents="all")["downloaded"] == 2
    roles = company.filings(form="annual", limit=1).download(tmp_path / "ex", documents=("exhibit",))
    assert roles["downloaded"] == 1
    assert (tmp_path / "ex" / "0000-2025_annual" / "ex21.htm").exists()
    with pytest.raises(ValueError, match="documents"):
        company.filings(form="annual", limit=1).download(tmp_path, documents="everything")


def test_file_types_select_documents_by_extension_across_all_documents(tmp_path):
    company = Company("FIX", market="US", provider=Provider())
    result = company.filings(form="annual", limit=1).download(tmp_path / "html", file_types=("htm",))
    assert result["downloaded"] == 2
    exhibits = company.filings(form="annual", limit=1).download(tmp_path / "ex", documents=("exhibit",),
                                                                file_types=(".HTM",))
    assert exhibits["downloaded"] == 1 and (tmp_path / "ex" / "0000-2025_annual" / "ex21.htm").exists()
    assert company.filings(form="annual", limit=1).download(tmp_path / "pdf", file_types=(".pdf",))["downloaded"] == 0


def test_the_summary_counts_this_runs_filings_not_the_manifests(tmp_path):
    company = Company("FIX", market="US", provider=Provider())
    company.filings(form="annual", limit=3).download(tmp_path)
    assert company.filings(form="annual", limit=1).download(tmp_path)["filings"] == 1


def test_names_differing_only_in_case_get_separate_files(tmp_path):
    class CaseProvider(Provider):
        def list_documents(self, filing):
            return [FilingDocument(f"{filing.filing_id}:{name}", filing.filing_id, name, f"{filing.source_url}/{name}",
                                   Provenance(self.name, self.regulator, "US", f"{filing.source_url}/{name}", name),
                                   media_type="text/html", role="report", is_primary=name == "Report.htm")
                    for name in ("Report.htm", "report.htm")]

    company = Company("FIX", market="US", provider=CaseProvider())
    first = company.filings(form="annual", limit=1).download(tmp_path, documents="all")
    assert first["downloaded"] == 2
    assert sorted(path.name for path in (tmp_path / "0000-2025_annual").iterdir()) == ["Report.htm", "report-2.htm"]
    assert company.filings(form="annual", limit=1).download(tmp_path, documents="all")["skipped"] == 2
