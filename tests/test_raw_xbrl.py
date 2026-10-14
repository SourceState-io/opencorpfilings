from datetime import date

import pytest

from opencorpfilings.errors import ParseError
from opencorpfilings.raw_xbrl import parse_xbrl_instance


INSTANCE = b'''<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:ex="https://example.test/taxonomy"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <context id="c1"><entity><identifier scheme="lei">ABC</identifier>
    <segment><xbrldi:explicitMember dimension="ex:RegionAxis">ex:EuropeMember</xbrldi:explicitMember></segment>
  </entity><period><startDate>2024-01-01</startDate><endDate>2024-12-31</endDate></period></context>
  <unit id="u1"><measure>iso4217:EUR</measure></unit>
  <ex:Sales contextRef="c1" unitRef="u1" decimals="0">123</ex:Sales>
  <ex:Sales contextRef="c1" unitRef="u1" decimals="0">124</ex:Sales>
</xbrl>'''


def test_raw_occurrences_keep_context_dimensions_and_source():
    facts = parse_xbrl_instance(
        INSTANCE, document_url="https://example.test/report.zip", entry_path="report.xbrl",
        provider="fixture", regulator="Fixture", jurisdiction="FI", filing_id="f1",
    )
    assert len(facts) == 2
    assert [fact.value for fact in facts] == ["123", "124"]
    assert facts[0].concept_raw == "ex:Sales"
    assert facts[0].unit == "iso4217:EUR"
    assert facts[0].period_start == date(2024, 1, 1)
    assert facts[0].period_end == date(2024, 12, 31)
    assert facts[0].dimensions == {"ex:RegionAxis": "ex:EuropeMember"}
    assert facts[1].source_location.endswith("#fact-3")


def test_classic_xbrl_file_matches_byte_occurrences(tmp_path) -> None:
    source = tmp_path / "report.xbrl"
    source.write_bytes(INSTANCE)
    kwargs = dict(
        document_url="https://example.test/report.zip", entry_path="report.xbrl",
        provider="fixture", regulator="Fixture", jurisdiction="FI", filing_id="f1",
    )

    assert parse_xbrl_instance(source, **kwargs) == parse_xbrl_instance(INSTANCE, **kwargs)


def test_classic_xbrl_streams_direct_children_without_full_tree(tmp_path, monkeypatch) -> None:
    import opencorpfilings.raw_xbrl as raw_xbrl

    source = tmp_path / "late-context.xbrl"
    content = b'''<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:ex="https://example.test/taxonomy">
      <ex:Sales contextRef="later" unitRef="money"><ex:part>12</ex:part>3</ex:Sales>
      <context id="later"><entity><identifier scheme="lei">ABC</identifier></entity>
        <period><instant>2025-12-31</instant></period></context>
      <unit id="money"><measure>iso4217:EUR</measure></unit>
    </xbrl>'''
    source.write_bytes(content)

    def full_tree_forbidden(*_args, **_kwargs):
        raise AssertionError("classic XBRL should parse completed children incrementally")

    monkeypatch.setattr(raw_xbrl.ET, "parse", full_tree_forbidden)
    monkeypatch.setattr(raw_xbrl.ET, "fromstring", full_tree_forbidden)
    kwargs = dict(document_url="https://example.test/report.xbrl", entry_path="report.xbrl",
                  provider="fixture", regulator="Fixture", jurisdiction="US", filing_id="f1")
    for original in (source, content):
        facts = raw_xbrl.parse_xbrl_instance(original, **kwargs)
        assert [(fact.concept_raw, fact.value, fact.unit, fact.context_id) for fact in facts] == [
            ("ex:Sales", "123", "iso4217:EUR", "later"),
        ]
        assert facts[0].source_location.endswith("#fact-0")


def test_classic_xbrl_file_respects_parser_limit(tmp_path, monkeypatch) -> None:
    import opencorpfilings.raw_xbrl as raw_xbrl

    source = tmp_path / "report.xbrl"
    source.write_bytes(INSTANCE)
    monkeypatch.setattr(raw_xbrl, "MAX_XBRL_INSTANCE_BYTES", len(INSTANCE) - 1)
    with pytest.raises(ParseError, match="parser limit"):
        raw_xbrl.parse_xbrl_instance(
            source, document_url="https://example.test/report.zip", entry_path="report.xbrl",
            provider="fixture", regulator="Fixture", jurisdiction="FI", filing_id="f1",
        )


def test_non_instance_is_rejected():
    with pytest.raises(ParseError):
        parse_xbrl_instance(
            b"<other/>", document_url="https://example.test/one", entry_path="one.xml",
            provider="fixture", regulator="Fixture", jurisdiction="FI", filing_id="f1",
        )


@pytest.mark.parametrize("tag", ["context", "unit"])
def test_duplicate_xbrl_reference_ids_cannot_change_fact_attribution(tag):
    opening = f"<{tag} ".encode()
    start = INSTANCE.index(opening)
    end = INSTANCE.index(f"</{tag}>".encode(), start) + len(f"</{tag}>")
    duplicate = INSTANCE[start:end]
    content = INSTANCE[:end] + duplicate + INSTANCE[end:]
    with pytest.raises(ParseError, match=f"duplicate XBRL {tag} id"):
        parse_xbrl_instance(
            content, document_url="https://example.test/report.zip", entry_path="report.xbrl",
            provider="fixture", regulator="Fixture", jurisdiction="FI", filing_id="f1",
        )


@pytest.mark.parametrize(("unit_xml", "expected"), [
    (b"<unit id='u1'><measure>iso4217:EUR</measure><measure>xbrli:shares</measure></unit>",
     "iso4217:EUR * xbrli:shares"),
    (b"<unit id='u1'><divide><unitNumerator><measure>iso4217:EUR</measure>"
     b"<measure>xbrli:shares</measure></unitNumerator><unitDenominator>"
     b"<measure>ex:month</measure><measure>ex:region</measure></unitDenominator>"
     b"</divide></unit>", "(iso4217:EUR * xbrli:shares) / (ex:month * ex:region)"),
])
def test_xbrl_unit_retains_product_and_division_structure(unit_xml, expected):
    original = b'<unit id="u1"><measure>iso4217:EUR</measure></unit>'
    facts = parse_xbrl_instance(
        INSTANCE.replace(original, unit_xml), document_url="https://example.test/report.zip",
        entry_path="report.xbrl", provider="fixture", regulator="Fixture",
        jurisdiction="FI", filing_id="f1",
    )
    assert facts[0].unit == expected


def test_xbrl_unit_without_measures_is_rejected():
    content = INSTANCE.replace(
        b'<unit id="u1"><measure>iso4217:EUR</measure></unit>', b'<unit id="u1"/>',
    )
    with pytest.raises(ParseError, match="invalid XBRL unit"):
        parse_xbrl_instance(
            content, document_url="https://example.test/report.zip", entry_path="report.xbrl",
            provider="fixture", regulator="Fixture", jurisdiction="FI", filing_id="f1",
        )
