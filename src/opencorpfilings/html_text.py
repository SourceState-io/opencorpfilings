"""Minimal readable text from HTML/XHTML source bytes."""

from __future__ import annotations

import codecs
import re
from html.parser import HTMLParser
from pathlib import Path

from .errors import ParseError


_XML_ENCODING = re.compile(br'<\?xml\b[^>]*\bencoding\s*=\s*["\']([A-Za-z0-9._-]+)["\']', re.I)
_HTML_CHARSET = re.compile(br'<meta\b[^>]*\bcharset\s*=\s*["\']?([A-Za-z0-9._-]+)', re.I)
#: browsers decode these labels as windows-1252, which differs from Latin-1 in 0x80-0x9F
_WINDOWS_1252 = {"iso-8859-1", "iso8859-1", "latin1", "latin-1", "l1", "us-ascii", "ascii"}
_BLOCK_TAGS = {"p", "div", "tr", "li", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}
_HIDDEN_TAGS = {"head", "script", "style", "noscript", "template", "ix:header", "ix:hidden"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_HIDDEN_STYLE = re.compile(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b", re.IGNORECASE)
_INLINE_XBRL_NS = {"http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2008/inlineXBRL"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0
        self.stack: list[tuple[str, bool, int | None]] = []
        self.inline_prefixes = {"ix"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.inline_prefixes.update(name.split(":", 1)[1] for name, value in attrs
                                    if name.startswith("xmlns:") and value in _INLINE_XBRL_NS)
        prefix, separator, local = tag.partition(":")
        hidden = (tag in _HIDDEN_TAGS or (bool(separator) and prefix in self.inline_prefixes
                                           and local in {"header", "hidden"}) or "hidden" in attributes
                  or bool(_HIDDEN_STYLE.search(attributes.get("style") or "")))
        if self.hidden_depth == 0 and not hidden and (tag == "br" or tag in _BLOCK_TAGS):
            self.parts.append("\n")
        elif self.hidden_depth == 0 and not hidden and tag in {"td", "th"}:
            self.parts.append("\t")
        if tag not in _VOID_TAGS:
            href = attributes.get("href") or ""
            link_start = len(self.parts) if tag == "a" and href.startswith("#") else None
            self.stack.append((tag, hidden, link_start))
            if hidden:
                self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.hidden_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                link_start = self.stack[index][2]
                if tag == "a" and link_start is not None:
                    label = " ".join("".join(self.parts[link_start:]).split()).casefold()
                    if label == "table of contents":
                        del self.parts[link_start:]
                self.hidden_depth -= sum(hidden for _, hidden, _ in self.stack[index:])
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.hidden_depth == 0:
            self.parts.append(data)


def _is_utf8(content: bytes | Path) -> bool:
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        if isinstance(content, Path):
            with content.open("rb") as source:
                while chunk := source.read(1_000_000):
                    decoder.decode(chunk)
        else:
            decoder.decode(content)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    return True


def html_encoding(content: bytes | Path, encoding: str | None = None) -> str:
    """The encoding to read HTML/XHTML with: the caller's, else a byte-order mark's, else UTF-8 when the bytes are
    valid UTF-8 (filers mislabel UTF-8 as Latin-1), else the declared charset, else UTF-8 - which then fails
    or replaces, so an undeclared legacy encoding is never guessed."""
    if encoding is not None:
        return encoding
    if isinstance(content, Path):
        with content.open("rb") as source:
            header = source.read(4096)
    else:
        header = content[:4096]
    if header.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if header.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if _is_utf8(content):
        return "utf-8"
    match = _XML_ENCODING.search(header) or _HTML_CHARSET.search(header)
    declared = match.group(1).decode("ascii").lower() if match else "utf-8"
    declared = "windows-1252" if declared in _WINDOWS_1252 else declared
    try:
        codecs.lookup(declared)
    except LookupError:
        return "utf-8"
    return declared


def read_html(content: bytes | Path, encoding: str | None = None) -> str:
    """Decode a whole HTML/XHTML source, failing as a ParseError rather than a UnicodeDecodeError."""
    encoding = html_encoding(content, encoding)
    try:
        if isinstance(content, Path):
            with content.open("r", encoding=encoding, newline="") as source:
                return source.read()
        return content.decode(encoding)
    except (LookupError, UnicodeError) as exc:
        raise ParseError(f"HTML source cannot be decoded as {encoding}; pass encoding=... explicitly") from exc


def html_to_text(content: bytes | Path, *, encoding: str | None = None) -> str:
    parser = _TextParser()
    try:
        decoder = codecs.getincrementaldecoder(html_encoding(content, encoding))(errors="replace")
    except LookupError as exc:
        raise ParseError(f"unknown encoding {encoding!r}") from exc
    if isinstance(content, Path):
        with content.open("rb") as source:
            while chunk := source.read(1_000_000):
                parser.feed(decoder.decode(chunk))
    else:
        for offset in range(0, len(content), 1_000_000):
            parser.feed(decoder.decode(content[offset:offset + 1_000_000]))
    parser.feed(decoder.decode(b"", final=True))
    parser.close()
    lines = [re.sub(r"[^\S\t]+", " ", part).strip() for part in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def html_to_text_line_offsets(html: str, source_offsets: list[int]) -> list[int]:
    """Map decoded HTML character offsets to zero-based lines in ``html_to_text``.

    Parse the source once; repeated prefix parses are quadratic for long reports.
    Offsets should point to tag boundaries, as SEC body-heading blocks do.
    """
    line_starts = [0] + [index + 1 for index, char in enumerate(html) if char == "\n"]
    targets = sorted(enumerate(source_offsets), key=lambda item: item[1])
    positions = [0] * len(targets)

    class _OffsetParser(_TextParser):
        def __init__(self) -> None:
            super().__init__()
            self.next_target = 0
            self.counted = 0        # parts already folded into `lines`
            self.lines = 0          # nonblank lines completed before `tail`
            self.tail = ""          # the line still open

        def _record(self, at: int) -> None:
            if self.next_target >= len(targets) or targets[self.next_target][1] > at:
                return
            *complete, self.tail = (self.tail + "".join(self.parts[self.counted:])).split("\n")
            self.counted = len(self.parts)
            self.lines += sum(bool(line.strip()) for line in complete)
            count = self.lines + bool(self.tail.strip())
            while self.next_target < len(targets) and targets[self.next_target][1] <= at:
                positions[targets[self.next_target][0]] = count
                self.next_target += 1

        def _at(self) -> int:
            line, column = self.getpos()
            return line_starts[line - 1] + column

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self._record(self._at())
            super().handle_starttag(tag, attrs)

        def handle_endtag(self, tag: str) -> None:
            self._record(self._at())
            super().handle_endtag(tag)
            if len(self.parts) < self.counted:  # a contents backlink was removed after it was counted
                self.counted = self.lines = 0
                self.tail = ""

        def handle_data(self, data: str) -> None:
            self._record(self._at())
            super().handle_data(data)

    parser = _OffsetParser()
    parser.feed(html)
    parser.close()
    parser._record(len(html))
    return positions
