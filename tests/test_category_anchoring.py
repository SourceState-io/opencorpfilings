"""A category is the report itself, never a notice that only mentions the report."""

import pytest

from opencorpfilings.providers.open_dart import _category


@pytest.mark.parametrize(("title", "expected"), [
    ("사업보고서 (2025.12)", "annual"),
    ("[기재정정]사업보고서 (2024.12)", "annual"),
    ("[정정] 사업보고서 (2025.03)", "annual"),
    ("반기보고서 (2025.06)", "interim"),
    ("분기보고서 (2025.09)", "quarterly"),
    ("Annual Report (2025.12)", "annual"),
    ("Semi-annual Report (2025.09)", "interim"),
    ("Quarterly Report (2025.09)", "quarterly"),
    ("사업보고서제출기한연장신고서", "other"),
    ("반기보고서제출기한연장신고서", "other"),
    ("Report on Extension of Business Report Submission Deadline", "other"),
    ("기업설명회(IR)개최(안내공시)", "other"),
])
def test_korean_category_requires_the_report_title(title, expected):
    assert _category(title)[0] == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("10-K405", "ANNUAL"), ("10-KSB", "ANNUAL"), ("10-KSB40", "ANNUAL"), ("10-KT405", "ANNUAL"),
    ("10-QSB", "QUARTERLY"), ("10-KSB/A", "ANNUAL"), ("NT 10-K", "OTHER"),
])
def test_sec_pre_2009_small_business_annual_and_quarterly_forms(raw, expected):
    from opencorpfilings.providers.sec import _form_category

    assert _form_category(raw) == expected
