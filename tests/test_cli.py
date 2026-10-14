"""The CLI follows the same one-company, one-filing public workflow."""

from datetime import date
import json

from opencorpfilings import Company, Entity, Filing, FilingDocument, FilingProvider, Provenance


class CLIProvider(FilingProvider):
    name = "fixture"
    market = "US"
    regulator = "Fixture Commission"
    capabilities = frozenset({"entity_lookup", "filing_discovery", "direct_filing_lookup", "document_download"})

    def resolve_entity(self, identifier):
        return Entity(identifier, "Fixture Inc", "US", self.name, "https://example.test/company")

    def _filing(self, entity):
        url = "https://example.test/filing"
        return Filing("f1", entity.entity_id, "US", self.name, self.regulator, url,
                      Provenance(self.name, self.regulator, "US", url, "f1"),
                      filing_type_raw="10-K", filing_type_normalized="ANNUAL",
                      filing_date=date(2024, 2, 1))

    def iter_filings(self, entity, *, form=None, start=None, end=None, include_amendments=True, limit=None):
        if form not in (None, "annual") or (start and start > date(2024, 2, 1)):
            return
        yield self._filing(entity)

    def get_filing(self, entity, filing_id):
        assert filing_id == "f1"
        return self._filing(entity)

    def list_documents(self, filing):
        url = "https://example.test/annual.htm"
        return [FilingDocument("d1", filing.filing_id, "annual.htm", url,
                               Provenance(self.name, self.regulator, "US", url, "d1"),
                               media_type="text/html", is_primary=True)]

    def download_document(self, document):
        return b"<p>Original filing</p>"


def test_cli_company_and_filings_use_one_market_scoped_api(monkeypatch, capsys):
    from opencorpfilings import cli

    provider = CLIProvider()
    monkeypatch.setattr(cli, "Company", lambda identifier, **kwargs: Company(
        identifier, market=kwargs["market"], provider=provider,
    ))
    assert cli.main(["company", "FIX", "--market", "US"]) == 0
    company = json.loads(capsys.readouterr().out)
    assert company["entity_id"] == "FIX"
    assert company["source_url"] == "https://example.test/company"

    assert cli.main(["filings", "FIX", "--market", "US", "--form", "annual", "--limit", "1"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["order_basis"] == "filing_date"
    assert listing["filings"] == [{
        "filing_id": "f1", "filing_date": "2024-02-01", "filing_type_raw": "10-K",
        "filing_type_normalized": "ANNUAL", "source_url": "https://example.test/filing",
    }]


def test_cli_search_preserves_source_candidate_and_options(monkeypatch, capsys):
    from opencorpfilings import cli

    provenance = Provenance("fixture", "Fixture Commission", "US",
                            "https://example.test/search", "source-7")
    candidate = Entity("selector:7", "Example Issuer", "US", "fixture",
                       "https://example.test/issuer/7", provenance=provenance,
                       requires_resolution=True)
    calls = []

    def find(query, **options):
        calls.append((query, options))
        return [candidate]

    monkeypatch.setattr(cli, "search_companies", find)
    assert cli.main(["search", "Example", "--market", "US", "--limit", "3",
                     "--user-agent", "Fixture Analyst analyst@example.test"]) == 0
    assert calls == [("Example", {"market": "US", "limit": 3, "cache_dir": None,
                                   "user_agent": "Fixture Analyst analyst@example.test"})]
    assert json.loads(capsys.readouterr().out) == {"market": "US", "results": [{
        "entity_id": "selector:7", "name": "Example Issuer", "jurisdiction": "US",
        "provider": "fixture", "source_url": "https://example.test/issuer/7",
        "search_source_url": "https://example.test/search", "source_id": "source-7",
        "requires_resolution": True,
    }]}


def test_cli_download_one_original_without_overwriting(monkeypatch, capsys, tmp_path):
    from opencorpfilings import cli

    provider = CLIProvider()
    monkeypatch.setattr(cli, "Company", lambda identifier, **kwargs: Company(
        identifier, market=kwargs["market"], provider=provider,
    ))
    monkeypatch.chdir(tmp_path)
    args = ["download", "FIX", "--market", "US", "--latest"]
    assert cli.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["document_id"] == "d1"
    assert output["source_url"] == "https://example.test/annual.htm"
    assert (tmp_path / "annual.htm").read_bytes() == b"<p>Original filing</p>"

    assert cli.main(args) == 2
    assert "already exists" in capsys.readouterr().err
    assert (tmp_path / "annual.htm").read_bytes() == b"<p>Original filing</p>"

    other = tmp_path / "selected.htm"
    assert cli.main(["download", "FIX", "--market", "US", "--filing-id", "f1",
                     "--output", str(other)]) == 0
    assert other.read_bytes() == b"<p>Original filing</p>"


def test_cli_passes_one_command_sec_user_agent_to_provider(monkeypatch, capsys):
    from opencorpfilings import cli

    supplied = []

    def make_company(identifier, **kwargs):
        supplied.append(kwargs)
        return Company(identifier, market=kwargs["market"], provider=CLIProvider())

    monkeypatch.setattr(cli, "Company", make_company)
    assert cli.main(["company", "FIX", "--market", "US",
                     "--user-agent", "Fixture Analyst analyst@example.test"]) == 0
    assert supplied == [{"market": "US", "cache_dir": None,
                         "user_agent": "Fixture Analyst analyst@example.test"}]
    assert json.loads(capsys.readouterr().out)["entity_id"] == "FIX"


def test_cli_rejects_invalid_options_before_contacting_provider(monkeypatch, capsys):
    from opencorpfilings import cli

    monkeypatch.setattr(cli, "search_companies", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("provider was contacted")))
    monkeypatch.setattr(cli, "Company", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("provider was contacted")))
    assert cli.main(["search", "Fixture", "--market", "US", "--limit", "0"]) == 2
    assert "--limit must be positive" in capsys.readouterr().err
    assert cli.main(["filings", "FIX", "--market", "US", "--limit", "0"]) == 2
    assert "--limit must be positive" in capsys.readouterr().err
    assert cli.main(["download", "FIX", "--market", "US", "--filing-id", "f1",
                     "--form", "annual"]) == 2
    assert "--form applies to --latest" in capsys.readouterr().err
    assert cli.main(["company", "FIX", "--market", "UK",
                     "--user-agent", "Fixture Analyst analyst@example.test"]) == 2
    assert "--user-agent applies to US" in capsys.readouterr().err


def test_cli_documents_lists_the_values_download_selects_by(monkeypatch, capsys):
    from opencorpfilings import cli

    class CountingDownloads(CLIProvider):
        downloads = 0

        def download_document(self, document):
            self.downloads += 1
            return super().download_document(document)

    provider = CountingDownloads()
    monkeypatch.setattr(cli, "Company", lambda identifier, **kwargs: Company(
        identifier, market=kwargs["market"], provider=provider,
    ))
    assert cli.main(["documents", "FIX", "--market", "US", "--filing-id", "f1"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["filing_id"] == "f1"
    assert listing["documents"] == [{
        "document_id": "d1", "filing_id": "f1", "filename": "annual.htm", "document_type": None, "role": None,
        "media_type": "text/html", "description": None, "is_primary": True,
        "language": None, "source_url": "https://example.test/annual.htm",
    }]
    assert provider.downloads == 0
    assert cli.main(["documents", "FIX", "--market", "US", "--filing-id", "f1", "--form", "annual"]) == 2


def test_cli_downloads_one_companys_bounded_filings_into_a_folder(monkeypatch, capsys, tmp_path):
    from opencorpfilings import cli

    provider = CLIProvider()
    monkeypatch.setattr(cli, "Company", lambda identifier, **kwargs: Company(
        identifier, market=kwargs["market"], provider=provider,
    ))
    target = tmp_path / "fix"
    assert cli.main(["download", "FIX", "--market", "US", "--form", "annual",
                     "--output-dir", str(target)]) == 2
    assert "all-history" in capsys.readouterr().err
    assert cli.main(["download", "FIX", "--market", "US", "--form", "annual", "--limit", "1",
                     "--output-dir", str(target)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["downloaded"] == 1 and result["failed"] == 0
    assert (target / "manifest.json").exists() and (target / "f1" / "annual.htm").exists()
    assert cli.main(["download", "FIX", "--market", "US", "--filing-id", "f1",
                     "--output-dir", str(target)]) == 2


def test_version_is_exposed_and_the_default_user_agent_carries_it(capsys):
    import opencorpfilings
    from opencorpfilings import cli
    from opencorpfilings.transport import HttpTransport

    assert opencorpfilings.__version__
    try:
        cli.main(["--version"])
    except SystemExit as exit_:
        assert exit_.code == 0
    assert opencorpfilings.__version__ in capsys.readouterr().out
    transport = HttpTransport()
    try:
        assert transport.user_agent == f"OpenCorpFilings/{opencorpfilings.__version__}"
    finally:
        transport.close()


def test_cli_find_prints_market_and_identifier(monkeypatch, capsys):
    from opencorpfilings import cli
    from opencorpfilings.directory import CompanyMatch

    calls = {}

    def fake_find(query, **options):
        calls.update(options, query=query)
        return [CompanyMatch(name="TOYOTA MOTOR CORPORATION", market="JP", identifier="7203", source=None,
                             tier="supported", tickers=("7203",), listed_by="EDINET code list")]

    monkeypatch.setattr(cli, "find_company", fake_find)
    assert cli.main(["find", "toyota", "--market", "JP", "--limit", "3"]) == 0
    result = json.loads(capsys.readouterr().out)["results"][0]
    assert result["market"] == "JP" and result["identifier"] == "7203" and result["tier"] == "supported"
    assert calls == {"query": "toyota", "markets": ["JP"], "limit": 3, "live": True, "refresh": False}
