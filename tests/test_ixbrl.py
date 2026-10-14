from datetime import date

import pytest

from opencorpfilings.errors import ParseError
from opencorpfilings.raw_xbrl import parse_ixbrl_xhtml


XHTML = b'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:ex="https://example.test/taxonomy">
  <head><title>Example accounts</title></head>
  <body>
    <ix:header><ix:resources>
      <xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="x">E</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:unit id="u1"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    </ix:resources></ix:header>
    <p><ix:nonFraction name="ex:Assets" contextRef="c1" unitRef="u1" scale="3" format="ixt:numdotdecimal">1,234</ix:nonFraction></p>
    <p><ix:nonNumeric name="ex:Note" contextRef="c1" continuedAt="more">Part A<ix:exclude>page footer</ix:exclude></ix:nonNumeric></p>
    <p><ix:fraction name="ex:Ratio" contextRef="c1" unitRef="u1"><ix:numerator>1</ix:numerator><ix:denominator>2</ix:denominator></ix:fraction></p>
    <ix:continuation id="more"> Part B</ix:continuation>
  </body>
</html>'''


def parse(content=XHTML):
    return parse_ixbrl_xhtml(content, document_url="https://example.test/report.xhtml",
                            entry_path="report.xhtml", provider="fixture", regulator="Registry",
                            jurisdiction="UK", filing_id="f1")


def test_raw_inline_facts_preserve_display_and_transformation_attributes():
    facts = parse()
    assert len(facts) == 3
    assert facts[0].concept_raw == "ex:Assets"
    assert facts[0].value == "1,234"
    assert facts[0].unit == "iso4217:USD"
    assert facts[0].period_end == date(2025, 12, 31)
    assert facts[0].taxonomy == "https://example.test/taxonomy"
    assert facts[0].provider_metadata["attributes"]["scale"] == "3"
    assert facts[0].provider_metadata["value_kind"] == "inline_display_text_untransformed"
    assert "::report.xhtml#ix-fact-" in facts[0].source_location
    assert facts[1].value == "Part A Part B"
    assert facts[2].concept_raw == "ex:Ratio"
    assert facts[2].value == "1/2"


def test_inline_parser_accepts_file_without_changing_occurrences(tmp_path):
    source = tmp_path / "report.xhtml"
    source.write_bytes(XHTML)

    expected = parse(XHTML)
    actual = parse_ixbrl_xhtml(source, document_url="https://example.test/report.xhtml",
                              entry_path="report.xhtml", provider="fixture", regulator="Registry",
                              jurisdiction="UK", filing_id="f1")
    assert actual == expected


def test_inline_parser_file_respects_size_limit(tmp_path, monkeypatch):
    import opencorpfilings.raw_xbrl as raw_xbrl

    source = tmp_path / "report.xhtml"
    source.write_bytes(XHTML)
    monkeypatch.setattr(raw_xbrl, "MAX_STREAMED_MEMBER_BYTES", len(XHTML) - 1)
    with pytest.raises(ParseError, match="parser limit"):
        raw_xbrl.parse_ixbrl_xhtml(
            source, document_url="https://example.test/report.xhtml",
            entry_path="report.xhtml", provider="fixture", regulator="Registry",
            jurisdiction="UK", filing_id="f1",
        )
    monkeypatch.setattr(raw_xbrl, "MAX_ARCHIVE_MEMBER_BYTES", len(XHTML) - 1)
    with pytest.raises(ParseError, match="parser limit"):
        raw_xbrl.parse_ixbrl_xhtml(
            XHTML, document_url="https://example.test/report.xhtml",
            entry_path="report.xhtml", provider="fixture", regulator="Registry",
            jurisdiction="UK", filing_id="f1",
        )


def test_inline_parser_rejects_invalid_xml_and_context():
    with pytest.raises(ParseError, match="invalid iXBRL XHTML"):
        parse(b"<html>")
    with pytest.raises(ParseError, match="valid concept/context"):
        parse(XHTML.replace(b'contextRef="c1"', b'contextRef="missing"', 1))


@pytest.mark.parametrize("tag", ["context", "unit"])
def test_duplicate_inline_reference_ids_cannot_change_fact_attribution(tag):
    opening = f"<xbrli:{tag} ".encode()
    start = XHTML.index(opening)
    end = XHTML.index(f"</xbrli:{tag}>".encode(), start) + len(f"</xbrli:{tag}>")
    duplicate = XHTML[start:end]
    with pytest.raises(ParseError, match=f"duplicate iXBRL {tag} id"):
        parse(XHTML[:end] + duplicate + XHTML[end:])


def test_duplicate_inline_continuation_id_cannot_replace_displayed_text():
    duplicate = b'<ix:continuation id="more">Replaced</ix:continuation>'
    with pytest.raises(ParseError, match="duplicate iXBRL continuation id"):
        parse(XHTML.replace(b"</body>", duplicate + b"</body>"))


@pytest.mark.parametrize(("unit_xml", "expected"), [
    (b"<xbrli:unit id='u1'><xbrli:measure>iso4217:USD</xbrli:measure>"
     b"<xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>",
     "iso4217:USD * xbrli:shares"),
    (b"<xbrli:unit id='u1'><xbrli:divide><xbrli:unitNumerator>"
     b"<xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>"
     b"<xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure>"
     b"</xbrli:unitDenominator></xbrli:divide></xbrli:unit>",
     "iso4217:USD / xbrli:shares"),
])
def test_inline_unit_retains_product_and_division_structure(unit_xml, expected):
    original = b'<xbrli:unit id="u1"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
    assert parse(XHTML.replace(original, unit_xml))[0].unit == expected


def test_large_inline_document_keeps_raw_facts_and_locations():
    content = XHTML.replace(b"<head>", b"<head><!--" + b"x" * 50_000_000 + b"-->", 1)
    assert len(content) > 50_000_000
    facts = parse(content)
    assert [fact.concept_raw for fact in facts] == ["ex:Assets", "ex:Note", "ex:Ratio"]
    assert facts[1].value == "Part A Part B"
    assert [fact.source_location for fact in facts] == [fact.source_location for fact in parse()]
