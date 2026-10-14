"""The docs site's company list is the index find_company() builds, and a list that fails stops the build."""

import json

import pytest

from scripts import build_find_index
from test_find_company import _rows


def test_the_list_holds_each_row_with_the_identifier_its_route_accepts(tmp_path, monkeypatch):
    monkeypatch.setattr(build_find_index, "_fetch_rows", lambda transport: (_rows(), {"sec": {"ok": True}}))
    build_find_index.main(str(tmp_path / "companies.json"))
    data = json.loads((tmp_path / "companies.json").read_text(encoding="utf-8"))
    rows = [dict(zip(data["fields"], values)) for values in data["rows"]]
    toyota = next(row for row in rows if row["market"] == "JP")
    assert (toyota["identifier"], toyota["tier"], toyota["source"]) == ("7203", "supported", None)
    assert {row["source"] for row in rows if row["market"] == "IT"} == {"esef_index"}
    assert all(source["url"].startswith("https://") for source in data["sources"])


def test_a_list_that_failed_to_download_is_not_published(tmp_path, monkeypatch):
    monkeypatch.setattr(build_find_index, "_fetch_rows", lambda transport: (
        _rows(), {"edinet": {"ok": False, "error": "ConnectError: unreachable"}}))
    with pytest.raises(SystemExit, match="edinet"):
        build_find_index.main(str(tmp_path / "companies.json"))
    assert not (tmp_path / "companies.json").exists()
