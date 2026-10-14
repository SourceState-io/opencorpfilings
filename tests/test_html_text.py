from opencorpfilings.html_text import html_to_text
from opencorpfilings import html_text
from test_ixbrl import XHTML


def test_readable_text_keeps_rows_and_hides_scripts():
    html = b"<h1>Report</h1><table><tr><th>Sales</th><td>10</td></tr></table><script>bad()</script>"
    result = html_to_text(html)
    assert "Report" in result
    assert "Sales\t10" in result
    assert "bad()" not in result


def test_readable_ixbrl_text_excludes_header_metadata_but_keeps_visible_facts():
    result = html_to_text(XHTML)
    assert "1,234" in result
    assert "Part Apage footer" in result
    assert "Example accounts" not in result
    assert "2025-12-31" not in result
    assert "iso4217:USD" not in result


def test_readable_text_skips_nested_hidden_html_and_ixbrl_containers():
    html = b'''<h1>Visible</h1>
    <div style="display: none"><div>Secret nested</div>Secret tail</div>
    <div>Shown after hidden</div>
    <section hidden><span>Secret attribute</span></section>
    <ix:hidden>Secret inline fact</ix:hidden>
    <p style="visibility: hidden">Secret style</p><p>Visible end</p>'''
    result = html_to_text(html)
    assert result == "Visible\nShown after hidden\nVisible end"


def test_readable_text_skips_header_with_nonstandard_inline_xbrl_prefix():
    html = b'''<html xmlns:inl="http://www.xbrl.org/2013/inlineXBRL"><body>
    <inl:header><inl:resources>Secret context</inl:resources></inl:header>
    <p>Visible report</p></body></html>'''
    assert html_to_text(html) == "Visible report"


def test_readable_text_skips_fragment_backlinks_to_table_of_contents():
    html = b'''<h2>Table of Contents</h2>
    <a href="#contents"><span>Table of Contents</span></a>
    <a href="#business">Business</a><p>Business description</p>
    <a href="https://example.org/contents">Table of Contents</a>'''
    result = html_to_text(html)
    assert result.count("Table of Contents") == 2
    assert "Business\nBusiness description" in result


def test_large_html_is_fed_incrementally_across_utf8_and_entity_boundaries(monkeypatch):
    chunks = []
    original = html_text._TextParser

    class TrackingParser(original):
        def feed(self, data):
            chunks.append(len(data))
            super().feed(data)

    monkeypatch.setattr(html_text, "_TextParser", TrackingParser)
    html = b"<p>" + b"a" * 1_999_991 + "é".encode() + b"&amp;end</p>"
    result = html_to_text(html)
    assert result.endswith("é&end")
    assert len([size for size in chunks if size]) >= 2
    assert max(chunks) <= 1_000_000


def test_readable_text_accepts_a_saved_source_path(tmp_path):
    source = tmp_path / "report.xhtml"
    source.write_bytes(b"<p>Before &amp; after</p>")
    assert html_to_text(source) == "Before & after"


def test_text_reads_a_declared_legacy_charset_instead_of_replacing_it():
    source = '<meta charset="windows-1252"><p>ITEM\xa07.\xa0MANAGEMENT\u2019S DISCUSSION</p>'.encode("cp1252")
    assert html_to_text(source) == "ITEM 7. MANAGEMENT\u2019S DISCUSSION"


def test_text_keeps_utf8_bytes_that_are_mislabelled_as_latin1():
    source = '<meta charset="iso-8859-1"><p>Company\u2019s r\u00e9sum\u00e9</p>'.encode("utf-8")
    assert html_to_text(source) == "Company\u2019s r\u00e9sum\u00e9"


def test_text_from_a_saved_legacy_charset_file(tmp_path):
    path = tmp_path / "report.htm"
    path.write_bytes('<?xml version="1.0" encoding="cp1252"?><p>caf\u00e9 \u2014 fees</p>'.encode("cp1252"))
    assert html_to_text(path) == "caf\u00e9 \u2014 fees"


def test_line_offsets_match_prefix_parses_with_a_removed_contents_backlink():
    from opencorpfilings.html_text import html_to_text_line_offsets

    html = ("<div><p>One</p><p>Two <a href='#toc'>Table of Contents</a></p><table><tr><td>a</td><td>b</td></tr>"
            "</table>" + "".join(f"<p>Para {n}</p><div><a href='#toc'>Table of Contents</a></div>" for n in range(40))
            + "</div>")
    offsets = [index for index, char in enumerate(html) if char == "<"]
    expected = [len(html_to_text(html[:offset].encode()).splitlines()) for offset in offsets]
    assert html_to_text_line_offsets(html, offsets) == expected
