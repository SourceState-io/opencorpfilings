"""Finanscentralen's public issuer-name search."""

import pytest

from opencorpfilings import search_companies
from opencorpfilings.errors import ParseError, UnsupportedCapabilityError
from opencorpfilings.providers.sweden_oam import SwedenOAMProvider


LANDING = b"<form><input name='__VIEWSTATE' type='hidden' value='v'><input name='__EVENTVALIDATION' type='hidden' value='e'></form>"


def results(rows, *, next_page=False):
    body = "".join(
        f"<tr><td><a id='ctl00_main_dgrInstitutes_ctl{i + 2:02d}_lnkInstitute' href='#'>{name}</a></td><td>{org}</td></tr>"
        for i, (name, org) in enumerate(rows)
    )
    pager = ("<tr><td colspan='2'><a href=\"javascript:__doPostBack('ctl00$main$dgrInstitutes','Page$Next')\">Next</a></td></tr>"
             if next_page else "")
    return ("<form><input name='__VIEWSTATE' type='hidden' value='next'>"
            "<input name='__EVENTVALIDATION' type='hidden' value='e2'></form>"
            f"<table id='ctl00_main_dgrInstitutes'><tr><th>Name</th><th>Org</th></tr>{body}{pager}</table>").encode()


class SearchTransport:
    def __init__(self, pages):
        self.pages = pages
        self.posts = []
        self.gets = 0

    def get(self, url, **kwargs):
        self.gets += 1
        return LANDING

    def post_form(self, url, *, data):
        self.posts.append(data)
        return self.pages[len(self.posts) - 1]


def test_sweden_name_search_returns_source_identifiers_and_follows_next_page():
    first = [(f"Bank {i}", f"{i:06d}-1234") for i in range(10)]
    second = [(f"Bank {i}", f"{i:06d}-1234") for i in range(10, 15)]
    transport = SearchTransport([results(first, next_page=True), results(second)])
    matches = search_companies("bank", market="SE", limit=15,
                               provider=SwedenOAMProvider(transport=transport))
    assert len(matches) == 15
    assert matches[0].entity_id == "000000-1234"
    assert matches[-1].name == "Bank 14"
    assert matches[0].source_url == "https://finanscentralen.fi.se/search/Search.aspx"
    assert matches[0].provenance.source_id == matches[0].entity_id
    assert transport.gets == 1
    assert len(transport.posts) == 2
    assert transport.posts[0]["ctl00$main$txtCompanyName"] == "bank"
    assert transport.posts[1]["__EVENTTARGET"] == "ctl00$main$dgrInstitutes"
    assert transport.posts[1]["__EVENTARGUMENT"] == "Page$Next"


def test_sweden_name_search_no_match_and_changed_markup():
    no_match = ("<table id='ctl00_main_dgrInstitutes'><tr><td>"
                "S\u00f6kningen gav ingen tr\u00e4ff."
                "</td></tr></table>").encode()
    transport = SearchTransport([no_match])
    assert search_companies("nothing", market="SE", provider=SwedenOAMProvider(transport=transport)) == []
    with pytest.raises(ParseError):
        search_companies("bank", market="SE", provider=SwedenOAMProvider(
            transport=SearchTransport([b"<html>changed</html>"])))


def test_sweden_name_search_page_bound_is_explicit():
    transport = SearchTransport([results([("Bank", "000001-1234")], next_page=True)])
    with pytest.raises(UnsupportedCapabilityError, match="page"):
        search_companies("bank", market="SE", limit=5,
                         provider=SwedenOAMProvider(transport=transport, max_search_pages=1))


def test_sweden_unique_name_search_returns_direct_company_detail():
    detail = b"""<form>
      <span id='ctl00_main_lblOrganizationNumberValue'>556016-0680</span>
      <span id='ctl00_main_lblCompanyName'>Telefonaktiebolaget LM Ericsson</span>
      <span id='ctl00_main_lblLEIValue'>549300W9JLPW15XIFM52</span>
    </form>"""
    transport = SearchTransport([detail])
    matches = search_companies("Ericsson", market="SE", limit=5,
                               provider=SwedenOAMProvider(transport=transport))
    assert [(match.entity_id, match.name) for match in matches] == [
        ("556016-0680", "Telefonaktiebolaget LM Ericsson")
    ]
    assert matches[0].identifiers[-1].value == "549300W9JLPW15XIFM52"
    assert matches[0].provenance.source_id == "556016-0680"
    assert len(transport.posts) == 1
