"""The Item headings of an SEC 10-K body, read from the source HTML.

`blocks` splits a document into runs of text with their source offsets; `item_headings` finds the body's Item
headings among them, setting aside a contents page and a cross-reference list.
"""

from __future__ import annotations

import dataclasses
import re
from html.parser import HTMLParser

#: elements that begin a new run of text; a table row is one block, its cells joined by a space
_BLOCK = {"p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "body", "center", "blockquote",
          "ul", "ol", "dl", "dt", "dd", "section", "article", "title"}
_CELL = {"td", "th"}
#: inline XBRL's header holds hidden facts and resources, not the page
_SKIP = {"ix:header", "script", "style", "head"}
_BOLD_STYLE = re.compile(r"font-weight\s*:\s*(bold|[6-9]00)", re.I)
_SPACE = re.compile(r"[\s  -​　]+")


@dataclasses.dataclass
class Block:
    start: int              # offset of the tag that opened the block, in the source HTML
    end: int                # offset of the tag that closed it
    text: str
    bold: bool              # most of its characters are set bold
    in_table: bool


class _Parser(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.lines = [0]
        for i, ch in enumerate(html):
            if ch == "\n":
                self.lines.append(i + 1)
        self.out: list[Block] = []
        self.stack: list[tuple[str, bool]] = []          # (tag, bold) of open elements
        self.skip = 0
        self.tables = 0
        self.start = 0
        self.parts: list[tuple[str, bool]] = []

    def _at(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def _flush(self, at: int) -> None:
        text = _SPACE.sub(" ", "".join(t for t, _ in self.parts)).strip()
        if text:
            bold = sum(len(t.strip()) for t, b in self.parts if b)
            self.out.append(Block(self.start, at, text, bold * 2 >= len(text.replace(" ", "")), self.tables > 0))
        self.parts = []
        self.start = at

    def _bold(self) -> bool:
        return bool(self.stack) and self.stack[-1][1]

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        at = self._at()
        if tag in _BLOCK:
            self._flush(at)
        if tag == "table":
            self.tables += 1
        if tag in _CELL and self.parts:
            self.parts.append((" ", False))
        if tag == "br":
            self.parts.append((" ", False))
            return
        style = dict(attrs).get("style") or ""
        bold = self._bold() or tag in ("b", "strong") or bool(_BOLD_STYLE.search(style))
        if tag not in ("img", "hr", "meta", "link", "input", "col", "wbr"):
            self.stack.append((tag, bold))

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        at = self._at()
        if tag in _BLOCK:
            self._flush(at)
        if tag == "table":
            self.tables = max(0, self.tables - 1)
        for i in range(len(self.stack) - 1, -1, -1):          # a stray end tag closes back to its own element
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.skip and data:
            if not self.parts and not data.strip():
                return
            self.parts.append((data, self._bold()))


def blocks(html: str) -> list[Block]:
    """The document as blocks of text in order, each with the source offsets of the tags around it."""
    p = _Parser(html)
    p.feed(html)
    p.close()
    p._flush(len(html))
    return p.out


ITEMS = ["1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8", "9", "9A", "9B", "9C",
         "10", "11", "12", "13", "14", "15", "16"]
_RANK = {code: i for i, code in enumerate(ITEMS)}
#: `Item 7.`, `ITEM 7A:`, `Item 8 - Financial`, `PART II, Item 5.`, a bare `Item 1` cell; not `Item 1, Business of this
#: Form 10-K` or `Item 7 of this report` - a reference in prose names an Item and runs on in lower case or a comma
_ITEM = re.compile(r"^\s*(?:part\s+[iv]+\W{0,3})?items?\s*(\d{1,2}[a-z]?)"
                   r"(?=\s*[.:\u2014\u2013-]|\s*$|\s+(?-i:[A-Z(\[])|\s+(?:and|&)\s|\s*,\s*\d)", re.I)
_RESERVED = re.compile(r"^\W*reserved\W*$", re.I)
def _item_code(raw: str) -> str | None:
    """Map a heading to a known 10-K Item code, including lettered variants."""
    code = raw.upper()
    if code in _RANK:
        return code
    return code[:-1] if code[-1:].isalpha() and code[:-1] in _RANK else None
#: Dense, ordered Item runs may be a contents page or cross-reference list.
RUN_MIN, RUN_GAP = 5, 300
#: A non-recurring run near the start can also be contents over an unlabelled body.
CONTENTS_AFTER = 0.9


def _candidates(blocks: list[Block]) -> list[tuple[int, str]]:
    """Every block opening with an Item, as `(block index, item)`."""
    cands = []
    for i, b in enumerate(blocks):
        m = _ITEM.match(b.text)
        #: A reserved placeholder is not a content boundary.
        if m and _item_code(m.group(1)) and not _RESERVED.match(b.text[m.end():]):
            cands.append((i, _item_code(m.group(1))))
    return cands


def _dense_runs(blocks: list[Block], cands: list[tuple[int, str]]) -> list[tuple[range, bool, bool]]:
    """The dense runs of candidates - at least `RUN_MIN` in Item order, each under `RUN_GAP` characters from the next - as
    `(candidate positions, recurs, whole document follows)`: whether most of its Items appear again later, and whether
    `CONTENTS_AFTER` of the document's characters follow it."""
    gaps = [sum(len(b.text) for b in blocks[i + 1:(cands[k + 1][0] if k + 1 < len(cands) else i + 1)])
            for k, (i, _) in enumerate(cands)]
    total = sum(len(b.text) for b in blocks) or 1
    out, k = [], 0
    while k < len(cands):
        j, top, seen = k, _RANK[cands[k][1]], {cands[k][1]}
        #: A repeated contents entry can remain in the same run if the next code advances.
        def resumes(q: int) -> bool:
            return (cands[q][1] in seen and q + 1 < len(cands) and gaps[q] < RUN_GAP
                    and _RANK[cands[q + 1][1]] > top)
        while j + 1 < len(cands) and gaps[j] < RUN_GAP and (_RANK[cands[j + 1][1]] > top or resumes(j + 1)):
            j += 1
            top, seen = max(top, _RANK[cands[j][1]]), seen | {cands[j][1]}
        run = range(k, j + 1)
        if len(run) >= RUN_MIN:
            later = {code for _, code in cands[j + 1:]}
            recurs = sum(cands[r][1] in later for r in run) * 2 >= len(run)
            after = sum(len(b.text) for b in blocks[cands[j][0] + 1:]) / total
            out.append((run, recurs, after >= CONTENTS_AFTER))
        k = j + 1
    return out


#: A contents entry may list subsections before its dense run begins.
CONTENTS_LEAD = 2000


def _lead(blocks: list[Block], cands: list[tuple[int, str]], k: int) -> int:
    """A set-aside run's first candidate, extended back over the in-order entries before it whose listed subsections
    kept them out of the dense run - the contents page's own entries, never a body heading."""
    while k > 0 and _RANK[cands[k - 1][1]] < _RANK[cands[k][1]] and \
            sum(len(b.text) for b in blocks[cands[k - 1][0] + 1:cands[k][0]]) < CONTENTS_LEAD:
        k -= 1
    return k


def item_headings(blocks: list[Block]) -> list[tuple[str, int]]:
    """The body's Item headings as `(item, block index)`, in document order.

    A candidate is a block opening with an Item (a heading may open its own paragraph: `Item 8. ... incorporated by
    reference to Exhibit 13`). A contents page and a cross-reference list are dense runs of candidates - at least
    `RUN_MIN` in order, each under `RUN_GAP` characters apart - whose Items appear AGAIN later, where the body prints
    them; those are set aside. A dense run whose Items do not recur is the body (Items incorporated from the proxy,
    one sentence each) - unless the whole 10-K follows it (`CONTENTS_AFTER`): then it is a contents page over a body
    that prints no Item heading. Of the rest, the Items are the longest chain in Item
    order, ties to the later candidates. A heading the body lacks is absent, never borrowed from the contents page."""
    cands = _candidates(blocks)
    #: Include lead entries of each set-aside contents run.
    out_of_running = {k for run, recurs, whole in _dense_runs(blocks, cands) if recurs or whole
                      for k in range(_lead(blocks, cands, run[0]), run[-1] + 1)}
    pool = [c for k, c in enumerate(cands) if k not in out_of_running]
    #: longest chain in Item order; among equals, the one whose headings sit latest
    best: list[tuple[int, int, int]] = []                       # (length, sum of block indices, previous)
    for k, (i, code) in enumerate(pool):
        options = [(best[q][0] + 1, best[q][1] + i, q) for q in range(k) if _RANK[pool[q][1]] < _RANK[code]]
        best.append(max(options) if options else (1, i, -1))
    if not best:
        return []
    k = max(range(len(pool)), key=lambda q: best[q][:2])
    chain = []
    while k >= 0:
        chain.append((pool[k][1], pool[k][0]))
        k = best[k][2]
    chain = chain[::-1]
    #: A repeated heading within one Item starts at its first occurrence.
    for n, (code, at) in enumerate(chain):
        after = chain[n - 1][1] if n else -1
        chain[n] = (code, min(i for i, c in pool if c == code and after < i <= at))
    return chain
