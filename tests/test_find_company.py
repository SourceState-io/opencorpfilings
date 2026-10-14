"""find_company: one search across markets, answering which market and which identifier to use."""

import json

import pytest

from opencorpfilings import directory
from opencorpfilings.directory import CompanyMatch, build_rows, find_company, search_rows

SEC = {"fields": ["cik", "name", "ticker", "exchange"],
       "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"], [1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"],
                [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"], [1018724, "AMAZON COM INC", "AMZN", "Nasdaq"]]}
EDINET = [
    {"EDINETコード": "E02144", "提出者名": "トヨタ自動車株式会社", "提出者名(英字)": "TOYOTA MOTOR CORPORATION",
     "上場区分": "上場", "証券コード": "72030"},
    {"EDINETコード": "E99999", "提出者名": "非上場株式会社", "提出者名(英字)": "UNLISTED KK", "上場区分": "非上場", "証券コード": ""},
]
FR_LEI = [{"identificationsociete_iso_cd_lei": "969500XXRPGD7HCAFA90", "identificationsociete_iso_nom_soc": "LEGRAND"}]
FR_ISIN = [{"identificationsociete_iso_cd_isi": "FR0010307819", "identificationsociete_iso_nom_soc": "LEGRAND"},
           {"identificationsociete_iso_cd_isi": "0000066607", "identificationsociete_iso_nom_soc": "LACROIX SA"}]
ESEF = [{"country": "IT", "lei": "WOCMU6HCI0OJWNPRZS33", "name": "ENEL - SPA"},
        {"country": "FR", "lei": "969500XXRPGD7HCAFA90", "name": "LEGRAND"}]


def _rows():
    return build_rows(sec=SEC, edinet=EDINET, france_lei=FR_LEI, france_isin=FR_ISIN, esef=ESEF)


def test_rows_carry_the_identifier_each_route_accepts():
    rows = {(row["market"], row["identifier"], row["source"]): row for row in _rows()}
    apple = rows[("US", "320193", None)]
    assert apple["tickers"] == ["AAPL"] and apple["exchange"] == "Nasdaq"
    assert rows[("US", "1652044", None)]["tickers"] == ["GOOGL", "GOOG"]
    toyota = rows[("JP", "7203", None)]
    assert toyota["name"] == "TOYOTA MOTOR CORPORATION" and toyota["aliases"] == ["トヨタ自動車株式会社", "E02144"]
    assert not any(key[1] == "E99999" for key in rows)  # unlisted EDINET filers stay out of the default index
    legrand = rows[("FR", "969500XXRPGD7HCAFA90", None)]
    assert legrand["isins"] == ["FR0010307819"] and legrand["lei"] == "969500XXRPGD7HCAFA90"
    assert ("IT", "WOCMU6HCI0OJWNPRZS33", "esef_index") in rows


@pytest.mark.parametrize(("query", "market", "identifier"), [
    ("AAPL", "US", "320193"),
    ("apple", "US", "320193"),
    ("toyota", "JP", "7203"),
    ("トヨタ", "JP", "7203"),
    ("7203", "JP", "7203"),
    ("E02144", "JP", "7203"),
    ("FR0010307819", "FR", "969500XXRPGD7HCAFA90"),
    ("enel", "IT", "WOCMU6HCI0OJWNPRZS33"),
])
def test_search_finds_by_name_ticker_code_isin_or_lei(query, market, identifier):
    best = search_rows(_rows(), query)[0]
    assert (best.market, best.identifier) == (market, identifier)


def test_a_supported_national_route_ranks_ahead_of_the_index_for_the_same_company():
    matches = search_rows(_rows(), "Legrand")
    assert [(m.market, m.source) for m in matches[:2]] == [("FR", None), ("FR", "esef_index")]
    assert matches[0].tier == "supported" and matches[1].tier == "limited"


def test_match_opens_the_right_route(monkeypatch):
    monkeypatch.setenv("OPENCORPFILINGS_SEC_USER_AGENT", "Example Contact contact@example.com")
    enel = search_rows(_rows(), "enel")[0]
    company = enel.company()
    assert company.market == "IT" and company.provider.name == "esef_index"
    company.close()


def test_index_is_cached_and_rebuilt_only_when_stale_or_asked(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(transport):
        calls.append(1)
        return _rows(), {"sec": {"rows": 3}}

    monkeypatch.setattr(directory, "_fetch_rows", fake_fetch)
    first = find_company("apple", cache_dir=tmp_path, live=False)
    again = find_company("toyota", cache_dir=tmp_path, live=False)
    assert first[0].identifier == "320193" and again[0].market == "JP" and len(calls) == 1
    find_company("apple", cache_dir=tmp_path, live=False, refresh=True)
    assert len(calls) == 2
    stored = json.loads((tmp_path / directory.INDEX_FILE).read_text(encoding="utf-8"))
    stored["built_at"] = "2000-01-01T00:00:00+00:00"
    (tmp_path / directory.INDEX_FILE).write_text(json.dumps(stored), encoding="utf-8")
    find_company("apple", cache_dir=tmp_path, live=False)
    assert len(calls) == 3


def test_index_built_without_the_sec_contact_is_rebuilt_once_it_is_set(tmp_path, monkeypatch):
    # The README's first example passes user_agent= rather than the variable; an index built
    # then had no US companies and was reused for a week after the variable was set.
    calls = []

    def fake_fetch(transport):
        calls.append(1)
        skipped = {"ok": False, "error": "OPENCORPFILINGS_SEC_USER_AGENT is not set; the US list was skipped"}
        return _rows(), {"sec": {"ok": True} if directory.os.getenv("OPENCORPFILINGS_SEC_USER_AGENT") else skipped}

    monkeypatch.setattr(directory, "_fetch_rows", fake_fetch)
    with pytest.warns(UserWarning, match="US list was skipped"):
        find_company("toyota", cache_dir=tmp_path, live=False)
    with pytest.warns(UserWarning, match="US list was skipped"):
        find_company("toyota", cache_dir=tmp_path, live=False)
    assert len(calls) == 1
    stored = json.loads((tmp_path / directory.INDEX_FILE).read_text(encoding="utf-8"))
    stored["built_at"] = (directory.datetime.now(directory.timezone.utc) - directory.timedelta(days=2)).isoformat()
    (tmp_path / directory.INDEX_FILE).write_text(json.dumps(stored), encoding="utf-8")
    with pytest.warns(UserWarning, match="US list was skipped"):
        find_company("toyota", cache_dir=tmp_path, live=False)
    assert len(calls) == 1, "without the contact, a retry cannot help, so the week-long life applies"
    monkeypatch.setenv("OPENCORPFILINGS_SEC_USER_AGENT", "Example Contact contact@example.com")
    find_company("toyota", cache_dir=tmp_path, live=False)
    find_company("toyota", cache_dir=tmp_path, live=False)
    assert len(calls) == 2


@pytest.mark.filterwarnings("ignore:company index")
def test_index_missing_a_list_is_retried_after_an_hour(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(transport):
        calls.append(1)
        return _rows(), {"esef": {"ok": False, "error": "ConnectError: unreachable"}}

    monkeypatch.setattr(directory, "_fetch_rows", fake_fetch)
    find_company("enel", cache_dir=tmp_path, live=False)
    find_company("enel", cache_dir=tmp_path, live=False)
    assert len(calls) == 1
    stored = json.loads((tmp_path / directory.INDEX_FILE).read_text(encoding="utf-8"))
    stored["built_at"] = (directory.datetime.now(directory.timezone.utc) - directory.timedelta(hours=2)).isoformat()
    (tmp_path / directory.INDEX_FILE).write_text(json.dumps(stored), encoding="utf-8")
    find_company("enel", cache_dir=tmp_path, live=False)
    assert len(calls) == 2


def test_markets_filter_and_repr(tmp_path, monkeypatch):
    monkeypatch.setattr(directory, "_fetch_rows", lambda transport: (_rows(), {}))
    matches = find_company("legrand", cache_dir=tmp_path, live=False, markets=("IT", "FR"))
    assert {m.market for m in matches} == {"FR"}
    assert repr(matches[0]) == "<CompanyMatch FR 969500XXRPGD7HCAFA90 'LEGRAND' supported>"
    assert isinstance(matches[0], CompanyMatch)


def test_live_uk_hits_rank_below_an_equally_named_listed_issuer(tmp_path, monkeypatch):
    # Live Companies House search returns any registered company: "TOYOTA LIMITED"
    # outranked Toyota Motor once legal suffixes were dropped.
    from opencorpfilings import Entity

    monkeypatch.setattr(directory, "_fetch_rows", lambda transport: (_rows(), {}))
    import opencorpfilings.company as company_module
    monkeypatch.setattr(company_module, "search_companies", lambda query, market, limit: [
        Entity("14217182", "TOYOTA LIMITED", "UK", "companies_house", "https://example.test/14217182")])
    matches = find_company("toyota", cache_dir=tmp_path)
    assert [m.market for m in matches[:2]] == ["JP", "UK"]


@pytest.mark.filterwarnings("ignore:company index")
def test_a_rebuild_that_fails_keeps_the_previous_copy_of_each_failed_list(tmp_path, monkeypatch):
    monkeypatch.setattr(directory, "_fetch_rows", lambda transport: (_rows(), {}))
    find_company("toyota", cache_dir=tmp_path, live=False)
    path = tmp_path / directory.INDEX_FILE
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["built_at"] = (directory.datetime.now(directory.timezone.utc) - directory.timedelta(days=8)).isoformat()
    path.write_text(json.dumps(stored), encoding="utf-8")
    directory._LOADED.clear()
    down = {"ok": False, "error": "ConnectError: unreachable"}
    without_edinet = build_rows(sec=SEC, france_lei=FR_LEI, france_isin=FR_ISIN, esef=ESEF)
    monkeypatch.setattr(directory, "_fetch_rows", lambda transport: (without_edinet, {"edinet": down}))
    with pytest.warns(UserWarning, match="edinet list could not be refreshed"):
        assert find_company("toyota", cache_dir=tmp_path, live=False)[0].identifier == "7203"
    assert {row["market"] for row in json.loads(path.read_text(encoding="utf-8"))["rows"]} >= {"US", "JP", "FR", "IT"}

    monkeypatch.setattr(directory, "_fetch_rows", lambda transport: ([], dict.fromkeys(
        ("sec", "edinet", "france_lei", "france_isin", "esef"), down)))
    assert find_company("apple", cache_dir=tmp_path, live=False, refresh=True)[0].identifier == "320193"
    assert find_company("toyota", cache_dir=tmp_path, live=False)[0].identifier == "7203"
