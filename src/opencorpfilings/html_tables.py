"""Extract literal HTML table structure without inferring financial meaning."""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import re

from .errors import ParseError
from .html_text import html_encoding
from .models import (MAX_ARCHIVE_MEMBER_BYTES, FilingTable, FilingTableCell,
                     Provenance)


def _decode_html(content: bytes, encoding: str | None) -> str:
    encoding = html_encoding(content, encoding)
    try:
        return content.decode(encoding)
    except (LookupError, UnicodeError) as exc:
        raise ParseError(f"HTML table source cannot be decoded as {encoding}; pass encoding=... explicitly") from exc


def _text(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", "".join(parts)).strip()


@dataclass(slots=True)
class _Cell:
    tag: str
    rowspan: str | None
    colspan: str | None
    parts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Table:
    index: int
    caption: list[str] = field(default_factory=list)
    caption_open: bool = False
    rows: list[tuple[FilingTableCell, ...]] = field(default_factory=list)
    row: list[FilingTableCell] | None = None
    cell: _Cell | None = None


class _TableParser(HTMLParser):
    def __init__(self, parent: Provenance, source_location: str) -> None:
        super().__init__(convert_charrefs=True)
        self.parent = parent
        self.source_location = source_location
        self.stack: list[_Table] = []
        self.tables: list[FilingTable] = []
        self.count = 0
        self.hidden_depth = 0

    @staticmethod
    def _finish_cell(table: _Table) -> None:
        if table.cell is not None and table.row is not None:
            cell = table.cell
            table.row.append(FilingTableCell(
                text=_text(cell.parts), tag=cell.tag,
                rowspan=cell.rowspan, colspan=cell.colspan,
            ))
        table.cell = None

    @classmethod
    def _finish_row(cls, table: _Table) -> None:
        cls._finish_cell(table)
        if table.row is not None:
            table.rows.append(tuple(table.row))
        table.row = None

    def _finish_table(self) -> None:
        table = self.stack.pop()
        self._finish_row(table)
        caption = _text(table.caption) or None
        index = table.index
        raw = {"parent_source_id": self.parent.source_id, "table_index": index}
        provenance = Provenance(
            self.parent.provider, self.parent.regulator, self.parent.jurisdiction,
            self.parent.source_url, f"{self.parent.source_id}:table:{index}",
            self.parent.retrieved_at, raw,
        )
        self.tables.append(FilingTable(
            index=index, caption=caption, rows=tuple(table.rows),
            source_url=self.parent.source_url,
            source_location=f"{self.source_location}#table={index}",
            provenance=provenance,
        ))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden_depth += 1
            return
        if self.hidden_depth:
            return
        if tag == "table":
            self.count += 1
            self.stack.append(_Table(self.count))
            return
        if not self.stack:
            return
        table = self.stack[-1]
        if tag == "caption":
            table.caption_open = True
        elif tag == "tr":
            self._finish_row(table)
            table.row = []
        elif tag in {"td", "th"} and table.row is not None:
            self._finish_cell(table)
            attributes = dict(attrs)
            table.cell = _Cell(tag, attributes.get("rowspan"), attributes.get("colspan"))
        elif tag in {"br", "p", "div", "li"} and table.cell is not None:
            table.cell.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
            return
        if self.hidden_depth or not self.stack:
            return
        table = self.stack[-1]
        if tag == "table":
            self._finish_table()
        elif tag == "caption":
            table.caption_open = False
        elif tag == "tr":
            self._finish_row(table)
        elif tag in {"td", "th"}:
            self._finish_cell(table)
        elif tag in {"p", "div", "li"} and table.cell is not None:
            table.cell.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self.hidden_depth or not self.stack:
            return
        table = self.stack[-1]
        if table.caption_open:
            table.caption.append(data)
        elif table.cell is not None:
            table.cell.parts.append(data)


def extract_html_tables(content: bytes | Path, *, provenance: Provenance,
                        source_location: str, encoding: str | None = None) -> tuple[FilingTable, ...]:
    """Return source-ordered table tags, keeping their literal rows and spans."""
    if (content.stat().st_size if isinstance(content, Path) else len(content)) > MAX_ARCHIVE_MEMBER_BYTES:
        raise ParseError("HTML table source exceeds the 100 MB inspection limit")
    parser = _TableParser(provenance, source_location)
    if isinstance(content, Path):
        encoding = html_encoding(content, encoding)
        with content.open("rb") as source:
            try:
                decoder = codecs.getincrementaldecoder(encoding)()
                total = 0
                while chunk := source.read(1_000_000):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_MEMBER_BYTES:
                        raise ParseError("HTML table source exceeds the 100 MB inspection limit")
                    parser.feed(decoder.decode(chunk))
                parser.feed(decoder.decode(b"", final=True))
            except (LookupError, UnicodeError) as exc:
                raise ParseError(
                    f"HTML table source cannot be decoded as {encoding}; pass encoding=... explicitly"
                ) from exc
    else:
        parser.feed(_decode_html(content, encoding))
    parser.close()
    while parser.stack:
        parser._finish_table()
    return tuple(sorted(parser.tables, key=lambda table: table.index))
