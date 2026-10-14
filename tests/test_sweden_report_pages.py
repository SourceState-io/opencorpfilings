"""Source report-table pages remain available through the shared collection."""

import pytest

from opencorpfilings import Company
from opencorpfilings.errors import ProviderError, UnsupportedCapabilityError
from opencorpfilings.providers.sweden_oam import SwedenOAMProvider


LANDING = b"<form><input name='__VIEWSTATE' type='hidden' value='v'><input name='__EVENTVALIDATION' type='hidden' value='e'></form>"


def company_page(years, *, next_page=False, org="502017-7753"):
    rows = "".join(
        f"<tr><td>{entry[0] if isinstance(entry, tuple) else entry}</td>"
        f"<td><a href='/search/GetFile.aspx?fid={entry[2] if isinstance(entry, tuple) else entry}'>"
        f"{entry[1] if isinstance(entry, tuple) else 'Engelska'}</a></td></tr>"
        for entry in years
    )
    pager = ("<tr><td colspan='2'><a href=\"javascript:__doPostBack('ctl00$main$gvwYearReports','Page$Next')\">&gt;</a></td></tr>"
             if next_page else "")
    return ("<form action='ViewCompany2.aspx'><input name='__VIEWSTATE' type='hidden' value='next'>"
            "<input name='__EVENTVALIDATION' type='hidden' value='e2'></form>"
            f"<span id='ctl00_main_lblCompanyName'>Swedbank AB</span>"
            f"<span id='ctl00_main_lblOrganizationNumberValue'>{org}</span>"
            f"<table id='ctl00_main_gvwYearReports'>{rows}{pager}</table>").encode()


class ReportTransport:
    def __init__(self, second, *, first=None):
        self.second = second
        self.first = first or company_page(range(2025, 2015, -1), next_page=True)
        self.posts = []

    def get(self, url, **kwargs):
        return LANDING

    def post_form(self, url, *, data):
        self.posts.append((url, data))
        if len(self.posts) == 1:
            return self.first
        return self.second


def test_sweden_report_paging_is_demand_driven_and_keeps_older_rows():
    transport = ReportTransport(company_page([2015, 2014]))
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(transport=transport))
    assert company.filings(form="annual").latest().filing_id.endswith(":2025")
    assert len(transport.posts) == 1
    filings = company.filings(form="annual").head(12)
    assert [item.provider_metadata["report_period_raw"] for item in filings] == [str(year) for year in range(2025, 2013, -1)]
    assert len(transport.posts) == 2
    assert transport.posts[1][0] == "https://finanscentralen.fi.se/search/ViewCompany2.aspx"
    assert transport.posts[1][1]["__EVENTTARGET"] == "ctl00$main$gvwYearReports"
    assert transport.posts[1][1]["__EVENTARGUMENT"] == "Page$Next"


def test_sweden_report_paging_bound_and_wrong_issuer_fail_explicitly():
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(
        transport=ReportTransport(company_page([2015])), max_report_pages=1))
    with pytest.raises(UnsupportedCapabilityError, match="page"):
        company.filings(form="annual").head(12)
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(
        transport=ReportTransport(company_page([2015], org="000000-0000"))))
    with pytest.raises(ProviderError, match="different company"):
        company.filings(form="annual").head(12)


def test_sweden_split_language_rows_are_one_period_filing():
    first = company_page([(2025, "Engelska", 700), (2021, "Svenska", 701),
                          (2021, "Engelska", 702)])
    transport = ReportTransport(b"", first=first)
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(transport=transport))
    filings = company.filings(form="annual").head(2)
    assert [item.provider_metadata["report_period_raw"] for item in filings] == ["2025", "2021"]
    assert [item.document_id for item in filings[1].documents] == ["701", "702"]
    assert filings[1].provider_metadata["source_file_ids"] == ["701", "702"]
    assert len(transport.posts) == 1


def test_sweden_latest_collects_languages_split_across_page_boundary():
    first = company_page([(2025, "Engelska", 700)], next_page=True)
    second = company_page([(2025, "Svenska", 701), (2024, "Engelska", 702)])
    transport = ReportTransport(second, first=first)
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(transport=transport))

    filing = company.filings(form="annual").latest()

    assert filing.provider_metadata["source_file_ids"] == ["700", "701"]
    assert [document.document_id for document in filing.documents] == ["700", "701"]
    assert len(transport.posts) == 2


def test_sweden_head_collects_last_selected_period_across_page_boundary():
    first = company_page([(2025, "Engelska", 700), (2024, "Engelska", 701)], next_page=True)
    second = company_page([(2024, "Svenska", 702), (2023, "Engelska", 703)])
    transport = ReportTransport(second, first=first)
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(transport=transport))

    filings = company.filings(form="annual").head(2)

    assert [filing.provider_metadata["report_period_raw"] for filing in filings] == ["2025", "2024"]
    assert filings[1].provider_metadata["source_file_ids"] == ["701", "702"]
    assert len(transport.posts) == 2


def test_sweden_same_language_duplicate_is_kept_as_a_separate_flagged_record():
    first = company_page([(2021, "Engelska", 701), (2021, "Engelska", 702)])
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(
        transport=ReportTransport(b"", first=first)))
    filings = list(company.filings(form="annual"))
    assert [filing.filing_id for filing in filings] == ["502017-7753:annual:2021", "502017-7753:annual:2021:2"]
    assert [filing.provider_metadata["source_file_ids"] for filing in filings] == [["701"], ["702"]]
    assert all(filing.provider_metadata["repeated_period"] for filing in filings)


def test_sweden_same_language_duplicate_across_page_boundary_is_kept_separate():
    first = company_page([(2025, "Engelska", 700)], next_page=True)
    second = company_page([(2025, "Engelska", 701), (2024, "Engelska", 702)])
    company = Company("502017-7753", market="SE", provider=SwedenOAMProvider(
        transport=ReportTransport(second, first=first)))

    filings = company.filings(form="annual").head(3)
    assert [filing.filing_id for filing in filings][:2] == ["502017-7753:annual:2025", "502017-7753:annual:2025:2"]
