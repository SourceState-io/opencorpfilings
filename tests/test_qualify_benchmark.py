"""Route qualification labels must not count a source outage or a text gap as a pass."""

from benchmarks.qualify import label

OK = {"status": "ok", "provenance": True, "original_bytes": 10, "media_type": "application/zip",
      "text_status": "available"}


def test_complete_workflow_with_text_from_a_text_bearing_original_passes():
    assert label(OK) == "pass"


def test_pdf_without_extractable_text_is_not_a_text_gap():
    assert label({**OK, "media_type": "application/pdf", "text_status": "empty"}) == "pass"


def test_text_bearing_original_without_text_is_a_gap():
    assert label({**OK, "text_status": "empty"}) == "text_gap"
    assert label({**OK, "media_type": "text/html", "text_status": "unsupported"}) == "text_gap"


def test_missing_provenance_or_bytes_fails():
    assert label({**OK, "provenance": False}) == "fail_provenance"
    assert label({**OK, "original_bytes": 0}) == "fail_provenance"


def test_errors_are_split_by_cause_and_stage():
    assert label({"status": "error", "error_type": "FilingNotFoundError", "failed_stage": "latest"}) == "no_filing"
    assert label({"status": "error", "error_type": "SourceUnavailableError", "failed_stage": "download"}) == "source_unavailable"
    assert label({"status": "error", "error_type": "ParseError", "failed_stage": "documents"}) == "fail_documents"


from datetime import date

FULL = {**OK, "form": "annual", "role": "report", "amendment": False, "printable_ratio": 0.999,
        "text_characters": 500_000, "period_end": "2025-12-31"}
RUN = date(2026, 10, 9)


def test_complete_current_original_report_passes():
    assert label(FULL, today=RUN) == "pass"


def test_wrong_content_that_used_to_pass_is_labelled():
    # Each case passed the first run's non-empty-text rule.
    assert label({**FULL, "amendment": True}, today=RUN) == "amendment_selected"
    assert label({**FULL, "role": "announcement"}, today=RUN) == "wrong_document"
    assert label({**FULL, "printable_ratio": 0.46}, today=RUN) == "unreadable_text"
    assert label({**FULL, "text_characters": 8_000}, today=RUN) == "text_small"
    assert label({**FULL, "period_end": "2024-12-31"}, today=RUN) == "stale"
    assert label({**FULL, "form": "interim", "period_end": "2025-06-30"}, today=RUN) == "stale"
    assert label({**FULL, "form": "interim", "period_end": "2025-09-30"}, today=RUN) == "pass"


def test_unknown_period_or_role_is_not_a_failure_by_itself():
    assert label({**FULL, "period_end": None, "role": None}, today=RUN) == "pass"
    assert label({**FULL, "media_type": "application/pdf", "text_characters": 3_000}, today=RUN) == "pass"
