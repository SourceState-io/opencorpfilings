"""Every document says what it is, and the primary document is the report, not a cover note."""

from datetime import date

import pytest

from opencorpfilings import FilingDocument, Provenance
from opencorpfilings.models import DOCUMENT_ROLES, _choose_primary
from opencorpfilings.providers.companies_house import _made_up_to
from opencorpfilings.providers.sec import _document_role


def _doc(name, *, media_type=None, role=None, primary=False):
    url = f"https://example.test/{name}"
    return FilingDocument(name, "f1", name, url, Provenance("fixture", "Registry", "DK", url, name),
                          media_type=media_type, role=role, is_primary=primary)


def test_role_vocabulary_is_closed():
    assert set(DOCUMENT_ROLES) == {"report", "exhibit", "annex", "announcement", "data", "generated", "other"}
    with pytest.raises(ValueError, match="role"):
        _doc("x.pdf", role="press")


def test_one_source_flagged_primary_wins():
    flagged = _doc("notice.html", media_type="text/html", role="announcement", primary=True)
    assert _choose_primary([_doc("report.pdf", media_type="application/pdf", role="report"), flagged]) is flagged


def test_without_a_unique_flag_the_report_role_and_format_decide():
    cover = _doc("notice.html", media_type="text/html", primary=True)
    report = _doc("annual.pdf", media_type="application/pdf", role="report", primary=True)
    assert _choose_primary([cover, report]) is report
    html, pdf, package = (_doc("a.html", media_type="text/html"), _doc("b.pdf", media_type="application/pdf"),
                          _doc("c.zip", media_type="application/zip"))
    assert _choose_primary([html, pdf, package]) is package
    assert _choose_primary([html, pdf]) is pdf


@pytest.mark.parametrize(("filename", "index_type", "expected"), [
    ("aapl-20250927.htm", "10-K", "report"),
    ("a10-kexhibit2111.htm", "EX-21.1", "exhibit"),
    ("aapl-20250927_htm.xml", "EX-101.INS", "data"),
    ("aapl-20250927_cal.xml", "EX-101.CAL", "data"),
    ("aapl-20250927.xsd", None, "data"),
    ("R2.htm", None, "generated"),
    ("0000320193-25-000079-index.html", None, "generated"),
    ("0000320193-25-000079-index-headers.html", None, "generated"),
    ("0000320193-25-000079.txt", None, "generated"),
    ("0000320193-25-000079-xbrl.zip", None, "generated"),
    ("FilingSummary.xml", None, "generated"),
    ("MetaLinks.json", None, "generated"),
    ("Financial_Report.xlsx", None, "generated"),
    ("aapl-20250927_g1.jpg", None, "other"),
])
def test_sec_document_roles(filename, index_type, expected):
    assert _document_role(filename, index_type, primary="aapl-20250927.htm", form="10-K") == expected


def test_sec_report_without_a_primary_filename_is_the_document_of_the_filing_form():
    assert _document_role("aapl-20240928.htm", "10-K", primary=None, form="10-K") == "report"
    assert _document_role("aapl-ex21.htm", "EX-21", primary=None, form="10-K") == "exhibit"


def test_uk_accounts_period_comes_from_the_made_up_date():
    assert _made_up_to({"description": "Group of companies' accounts made up to 27 December 2025"}) == date(2025, 12, 27)
    assert _made_up_to({"description_values": {"made_up_date": "2025-03-31"},
                        "description": "accounts-with-accounts-type-full"}) == date(2025, 3, 31)
    assert _made_up_to({"description": "Confirmation statement made on 1 May 2026"}) is None
