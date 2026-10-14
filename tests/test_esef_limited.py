"""The ESEF index route orders by report period, names each report's language, and accepts form="annual"."""

from opencorpfilings import Company
from opencorpfilings.providers.esef import ESEFProvider, INDEX_COUNTRIES

from test_esef_provider import LEI, StubTransport, _row


def _report(number, period, language, added):
    row = _row(number, added=added)
    attrs = row["attributes"]
    attrs["fxo_id"] = f"{LEI}-{period}-ESEF-FI-{number % 2}"
    attrs["period_end"] = period
    attrs["report_url"] = f"/{LEI}/{period}/issuer-{period}-{number % 2}-{language}.xhtml"
    attrs["package_url"] = f"/{LEI}/{period}/issuer-{period}-{number % 2}-{language}.zip"
    return row


def _company(rows, **options):
    provider = ESEFProvider(market="FI", transport=StubTransport(rows=rows), **options)
    return Company(LEI, market="FI", provider=provider)


def test_latest_is_the_newest_report_period_not_the_latest_indexed():
    # Enel's FY2021 report was indexed after its FY2022 report on 2023-05-30.
    rows = [_report(1, "2021-12-31", "en", "2023-05-30 18:09:00"),
            _report(2, "2022-12-31", "en", "2023-05-30 15:29:00")]
    company = _company(rows)
    assert company.filings().latest().period_end.isoformat() == "2022-12-31"
    assert [f.period_end.isoformat() for f in company.filings()] == ["2022-12-31", "2021-12-31"]
    assert company.filings().order_basis == "report_period"


def test_language_is_read_from_the_report_name_and_english_comes_first_within_a_period():
    rows = [_report(1, "2024-12-31", "en", "2025-04-29 10:00:00"),
            _report(2, "2024-12-31", "it", "2025-04-29 10:00:05")]
    filings = list(_company(rows).filings())
    assert [f.language for f in filings] == ["en", "it"]
    assert [f.language for f in _company(rows, prefer_language="it").filings()] == ["it", "en"]


def test_annual_form_is_accepted_because_the_index_holds_annual_reports():
    rows = [_report(1, "2024-12-31", "en", "2025-04-29 10:00:00")]
    filing = _company(rows).filings(form="annual").latest()
    assert filing.filing_type_normalized == "ANNUAL"


def test_countries_whose_index_data_stopped_years_ago_are_not_offered():
    assert not INDEX_COUNTRIES & {"CZ", "CY", "RO", "LV", "PL"}
