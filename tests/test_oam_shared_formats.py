"""What the national OAM routes share: one file-extension table and aware publication times."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from opencorpfilings import Company
from opencorpfilings.providers.denmark_oam import DenmarkOAMProvider
from opencorpfilings.providers.finland_oam import FinlandOAMProvider
from opencorpfilings.providers.france_oam import FranceOAMProvider
from opencorpfilings.providers.netherlands_oam import NetherlandsOAMProvider
import test_netherlands_oam
from test_denmark_oam import _DOC, DenmarkTransport
from test_europe_oam import _NOTICE, FR_LEI, FinlandTransport, FranceTransport
from test_netherlands_oam import AFMTransport

_EXPECTED = {
    ".zip": "application/zip", ".xbri": "application/zip", ".pdf": "application/pdf",
    ".xhtml": "application/xhtml+xml", ".html": "text/html", ".htm": "text/html",
    ".xml": "application/xml",
}


def _france(suffix: str):
    transport = FranceTransport()
    transport.rows[0]["url_de_recuperation"] = transport.rows[0]["url_de_recuperation"].replace(".zip", suffix)
    return Company(FR_LEI, market="FR", provider=FranceOAMProvider(transport=transport)).filings(form="annual").latest()


def _finland(suffix: str):
    class Transport(FinlandTransport):
        def get(self, url, **kwargs):
            content = super().get(url, **kwargs)
            return _NOTICE.replace(b".zip", suffix.encode()) if content == _NOTICE else content

    return Company("KONE Oyj", market="FI", provider=FinlandOAMProvider(
        transport=Transport())).filings(form="annual", limit=1).latest()


def _netherlands(suffix: str, monkeypatch):
    monkeypatch.setattr(test_netherlands_oam, "_DETAIL",
                        test_netherlands_oam._DETAIL.replace(b".xbri", suffix.encode()))
    return Company("ASML Holding N.V.", market="NL", provider=NetherlandsOAMProvider(
        transport=AFMTransport())).filings(form="annual").latest()


def _denmark(suffix: str):
    class Transport(DenmarkTransport):
        def get_json(self, url, **kwargs):
            data = super().get_json(url, **kwargs)
            if url.endswith("/details/300003388"):
                data["sections"][0]["elements"][2]["value"]["url"] = _DOC.replace(".zip", suffix)
            return data

    return Company("DK-61056416", market="DK", provider=DenmarkOAMProvider(
        transport=Transport())).filings(form="annual").latest()


@pytest.mark.parametrize("suffix,media_type", sorted(_EXPECTED.items()))
@pytest.mark.parametrize("market", ["FR", "FI", "NL", "DK"])
def test_every_oam_route_reads_file_extensions_alike(market, suffix, media_type, monkeypatch):
    filing = {"FR": lambda: _france(suffix), "FI": lambda: _finland(suffix),
              "NL": lambda: _netherlands(suffix, monkeypatch), "DK": lambda: _denmark(suffix)}[market]()
    assert filing.documents[0].media_type == media_type


def test_denmark_publication_time_is_copenhagen_time():
    filing = _denmark(".zip")
    assert filing.published_at.utcoffset() == timedelta(hours=1)
    assert filing.published_at.replace(tzinfo=None) == datetime(2026, 2, 4, 14, 55, 23)


def test_netherlands_publication_time_is_amsterdam_time():
    provider = NetherlandsOAMProvider(transport=AFMTransport())
    company = Company("ASML Holding N.V.", market="NL", provider=provider)
    annual = company.filings(form="annual").latest()
    interim = company.filings(form="interim").latest()
    assert annual.published_at.utcoffset() == timedelta(hours=1)
    assert interim.published_at.utcoffset() == timedelta(hours=2)  # summer time
    assert interim.published_at.replace(tzinfo=None) == datetime(2026, 7, 15, 9, 19, 28)


def test_publication_times_sort_across_routes():
    times = [_france(".zip").published_at, _finland(".zip").published_at, _denmark(".zip").published_at,
             Company("ASML Holding N.V.", market="NL", provider=NetherlandsOAMProvider(
                 transport=AFMTransport())).filings(form="annual").latest().published_at]
    assert sorted(times)[0] == times[1]
