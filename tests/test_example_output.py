import io
import sys

from examples.one_filing import _prepare_output


def test_live_example_prints_non_latin_names_on_a_legacy_console(monkeypatch):
    output = io.BytesIO()
    console = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    _prepare_output()
    print("주식회사")
    console.flush()
    assert b"\\uc8fc" in output.getvalue()
