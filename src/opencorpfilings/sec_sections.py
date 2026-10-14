"""Conservative Item navigation for SEC 10-K, 10-Q and 8-K HTML originals."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, SoupStrainer

from .errors import UnsupportedCapabilityError
from .html_text import html_encoding, html_to_text_line_offsets
from .models import FilingDocument, FilingSection, FilingSectionReference


_TOC_ITEM = re.compile(r"Item\s+(\d{1,2}[A-C]?)\.?", re.IGNORECASE)
_LISTED_BODY_ITEM_PREFIX = re.compile(r"^\s*[1-9]\d?\.\s*(?=Item\s)", re.IGNORECASE)
_GROUPED_BODY_ITEMS = re.compile(
    r"^Items\s+([1-9]\d?(?:\s*,\s*[1-9]\d?)*\s*,?\s*(?:and|&)\s+[1-9]\d?)\.\s+(.+)$", re.IGNORECASE,
)
_BODY_ITEM = re.compile(r"Item\s+(\d{1,2}[A-C]?)(?:\.\s*|\s*[—–-]\s*|\s+)(.+)", re.IGNORECASE)
_PART = re.compile(r"Part\s+(II|I)(?:\b|\.)", re.IGNORECASE)
_SIGNATURE = re.compile(r"Signatures?", re.IGNORECASE)
_NUMERIC_ITEM = re.compile(r"(?:[1-9]|1[0-6])[A-C]?\.?", re.IGNORECASE)
_FINANCIAL_PAGE_REF = re.compile(r"\bpages?\s+(F-\d{1,3})\b", re.IGNORECASE)
_EXHIBIT_REF = re.compile(r"\bexhibit\s+(\d{1,3}(?:\.\d+)?)\b", re.IGNORECASE)
_8K_ITEM = re.compile(r"Item\s+([1-9]\.\d{2})(?:\s*[.\-–—]\s*|\s+|$)(.*)", re.IGNORECASE)
_CROSS_REFERENCE_HEAD = re.compile(r"Form\s+10-K\s+Cross[- ]Reference\s+Index", re.I)
_CROSS_REFERENCE_ROW = re.compile(r"Item\s+(\d{1,2}[A-C]?)\b\.?\s+(.+)", re.I)
_INDEX_CODE = re.compile(r"(?:[1-9]|1[0-6])[A-C]?", re.I)
_NUMBERED_PAGE = re.compile(r"Page\s+([1-9]\d{0,2})(?:,\s*\([a-z]\))?", re.I)
_INDEX_PAGES = re.compile(r"[1-9]\d{0,2}(?:\s*[-–]\s*[1-9]\d{0,2})?(?:\s*,\s*[1-9]\d{0,2}(?:\s*[-–]\s*[1-9]\d{0,2})?)*(?:\s*,\s*\([a-z]\))?", re.I)
# First caption words from the SEC's Form 8-K. These verify source headings;
# returned titles remain the filing's own text, not these reference captions.
# https://www.sec.gov/files/form8-k.pdf
_8K_CAPTION_STARTS = {
    "1.01": "Entry into", "1.02": "Termination of", "1.03": "Bankruptcy or",
    "1.04": "Mine Safety", "1.05": "Material Cybersecurity",
    "2.01": "Completion of", "2.02": "Results of", "2.03": "Creation of",
    "2.04": "Triggering Events", "2.05": "Costs Associated", "2.06": "Material Impairments",
    "3.01": "Notice of", "3.02": "Unregistered Sales", "3.03": "Material Modification",
    "4.01": "Changes in", "4.02": "Non-Reliance on",
    "5.01": "Changes in", "5.02": "Departure of", "5.03": "Amendments to",
    "5.04": "Temporary Suspension", "5.05": "Amendments to", "5.06": "Change in",
    "5.07": "Submission of", "5.08": "Shareholder Director",
    "6.01": "ABS Informational", "6.02": "Change of", "6.03": "Change in",
    "6.04": "Failure to", "6.05": "Securities Act", "6.06": "Static Pool",
    "7.01": "Regulation FD", "8.01": "Other Events",
    "9.01": "Financial Statements",
}


def _item8_references(document: FilingDocument, lines: list[str], start: int, end: int
                      ) -> tuple[FilingSectionReference, ...]:
    """Retain explicit leading Item 8 pointers without following or relabelling content."""
    found = []
    for index in range(start, min(end, start + 4)):
        line = lines[index]
        for pattern, kind, prefix in ((_FINANCIAL_PAGE_REF, "page", ""), (_EXHIBIT_REF, "document", "EX-")):
            for match in pattern.finditer(line):
                found.append(FilingSectionReference(
                    kind=kind, target=prefix + match.group(1).upper(),
                    source_text=line, document_id=document.document_id,
                    source_url=document.source_url, source_line=index + 1,
                    provenance=document.provenance,
                ))
    return tuple(found)


def sec_10k_index_references(document: FilingDocument, item: str) -> tuple[FilingSectionReference, ...]:
    """Expose explicit terminal-index page pointers, without treating them as Item content."""
    lines = document.text().splitlines()
    markers = [i for i, line in enumerate(lines) if _CROSS_REFERENCE_HEAD.match(line.strip())
               and i >= len(lines) // 2]
    if (not markers or markers != list(range(markers[0], markers[-1] + 1)) or
            len({lines[i].strip().casefold() for i in markers}) != 1):
        raise UnsupportedCapabilityError("SEC 10-K has no verified cross-reference index")
    start = markers[-1]
    end = next((i for i in range(start + 1, len(lines)) if _SIGNATURE.fullmatch(lines[i].strip())), len(lines))
    entries: list[tuple[str, str | None, int, str]] = []
    consumed: set[int] = set()
    for i in range(start + 1, end):
        if i in consumed:
            continue
        match = _CROSS_REFERENCE_ROW.fullmatch(lines[i].strip())
        cells = [cell.strip() for cell in re.split(r"\t+", lines[i]) if cell.strip()]
        if match is not None:
            code = match.group(1).upper()
        elif cells and _INDEX_CODE.fullmatch(cells[0]):
            code = cells[0].upper()
        else:
            continue
        if entries and _item_order(code) <= _item_order(entries[-1][0]):
            raise UnsupportedCapabilityError("SEC 10-K cross-reference index is ambiguous")
        inline = cells[-1] if len(cells) >= 3 and _INDEX_PAGES.fullmatch(cells[-1]) else None
        page_line = i + 1 if i + 1 < end else None
        following = _NUMBERED_PAGE.fullmatch(lines[page_line].strip()) if page_line is not None else None
        split_page = None
        if match is None and len(cells) == 1 and i + 2 < end:
            title = lines[i + 1].strip()
            candidate = lines[i + 2].strip()
            if title and _INDEX_PAGES.fullmatch(candidate):
                split_page = i + 2
                consumed.update((i + 1, i + 2))
        source_line = split_page if split_page is not None else i if inline is not None else page_line if following else i
        page_value = lines[split_page].strip() if split_page is not None else inline or (following.group(1) if following else None)
        entries.append((code, page_value, source_line, lines[source_line].strip()))
    if len(entries) < 15 or entries[0][0] != "1" or entries[-1][0] not in {"15", "16"}:
        raise UnsupportedCapabilityError("SEC 10-K has no verified cross-reference index")
    matches = [entry for entry in entries if entry[0] == item]
    if not matches or matches[0][1] is None:
        raise UnsupportedCapabilityError(f"SEC 10-K index has no numbered page for Item {item}")
    _, raw_pages, source_line, source_text = matches[0]
    result = []
    for part in raw_pages.split(","):
        part = part.strip()
        if re.fullmatch(r"\([a-z]\)", part, re.I):
            continue  # Proxy incorporation stays visible in source_text.
        bounds = re.split(r"\s*[-–]\s*", part)
        first, last = int(bounds[0]), int(bounds[-1])
        if first > last:
            raise UnsupportedCapabilityError("SEC 10-K index page range is reversed")
        for number in range(first, last + 1):
            document.printed_page(str(number))
        result.append(FilingSectionReference(
            kind="page_range" if len(bounds) == 2 else "page", target=f"{first}-{last}" if len(bounds) == 2 else str(first),
            source_text=source_text, document_id=document.document_id, source_url=document.source_url,
            source_line=source_line + 1, provenance=document.provenance,
        ))
    return tuple(result)


def _title_key(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W_]+", value.casefold()))


def _minor_title_key(value: str) -> tuple[str, ...]:
    """Match only a conjunction and regular singular/plural differences."""
    return tuple(word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word
                 for word in _title_key(value) if word != "and")


def _item_order(item: str) -> int:
    return int(item.rstrip("ABC")) * 10 + (0 if item[-1].isdigit() else ord(item[-1]) - ord("A") + 1)


def _numeric_10k_contents(document: FilingDocument, lines: list[str]) -> list[tuple[str, str]]:
    """Read Item/title/page rows only when each title has one matching body heading."""
    soup = BeautifulSoup(document.download(), "html.parser", parse_only=SoupStrainer("table"))
    candidates = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not any([cell.get_text(" ", strip=True).casefold() for cell in row.find_all(["td", "th"], recursive=False)]
                   == ["item", "page"] for row in rows[:5]):
            continue
        entries = []
        for row in rows:
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"], recursive=False)]
            if (len(cells) >= 3 and _NUMERIC_ITEM.fullmatch(cells[0])
                    and cells[-2] and cells[-1].isdecimal()):
                entries.append((cells[0].rstrip(".").upper(), cells[-2]))
        if (len(entries) >= 5 and entries[0][0] == "1" and entries[-1][0] in {"15", "16"}
                and all(_item_order(a[0]) < _item_order(b[0]) for a, b in zip(entries, entries[1:]))):
            candidates.append(entries)
    if len(candidates) != 1:
        raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")

    headings = []
    for item, source_title in candidates[0]:
        key = "".join(char for char in source_title.casefold() if char.isalnum())
        matches = [match.group(2) for line in lines
                   if (match := _BODY_ITEM.fullmatch(line)) is not None
                   and match.group(1).upper() == item
                   and "".join(char for char in match.group(2).casefold() if char.isalnum()) == key]
        if len(matches) != 1:
            raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")
        headings.append((item, matches[0]))
    return headings


def _anchored_starts(
    document: FilingDocument, missing: list[tuple[str | None, str, str]],
    contents_end: int, lines: list[str], *, body_heading: bool = False,
) -> dict[tuple[str | None, str, str], int]:
    """Resolve a contents title through one verified body target in its Item row."""
    source = document.download()
    soup = BeautifulSoup(source, "html.parser")
    starts, tag_starts = {}, {}
    for entry in missing:
        _, item, title = entry
        row_item = re.compile(rf"\bItem\s+{re.escape(item)}(?:\.|\b)", re.IGNORECASE)
        links = [link for link in soup.find_all("a", href=True)
                 if link["href"].startswith("#")
                 and _title_key(link.get_text(" ", strip=True)) == _title_key(title)
                 and (row := link.find_parent("tr")) is not None
                 and row_item.search(row.get_text(" ", strip=True))]
        if len(links) != 1:
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
        target_id = links[0]["href"][1:]
        targets = soup.find_all(id=target_id)
        if len(targets) != 1:
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
        target = targets[0]
        if ((body_heading and target.name != "p")
                or (not body_heading and (target.name != "div" or target.get_text(strip=True)))):
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
        try:
            encoded_id = target_id.encode("ascii")
        except UnicodeEncodeError as exc:
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries") from exc
        attribute = re.compile(rb"\bid\s*=\s*['\"]" + re.escape(encoded_id) + rb"['\"]", re.IGNORECASE)
        positions = list(attribute.finditer(source))
        if len(positions) != 1:
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
        tag_start = source.rfind(b"<", 0, positions[0].start())
        if tag_start < 0 or b">" in source[tag_start:positions[0].start()]:
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
        tag_starts[entry] = tag_start
    encoding = html_encoding(source)
    html = source.decode(encoding, errors="replace")
    offsets = [len(source[:at].decode(encoding, errors="replace")) for at in tag_starts.values()]
    for entry, start in zip(tag_starts, html_to_text_line_offsets(html, offsets)):
        _, item, title = entry
        if not contents_end <= start < len(lines):
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
        if body_heading:
            heading = _BODY_ITEM.fullmatch(lines[start])
            if (heading is None or heading.group(1).upper() != item
                    or _title_key(heading.group(2)) != _title_key(title)):
                raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
        starts[entry] = start
    return starts


def _build_sections(
    document: FilingDocument, lines: list[str],
    contents: list[tuple[str | None, str, str]], contents_end: int,
    form: str,
) -> list[FilingSection]:
    body_lines: dict[tuple[str, tuple[str, ...]], list[int]] = {
        (item, _title_key(title)): [] for _, item, title in contents
    }
    body_candidates: list[tuple[str, str, int]] = []
    for index in range(contents_end, len(lines)):
        match = _BODY_ITEM.fullmatch(lines[index])
        if match is None and form == "10-K" and _LISTED_BODY_ITEM_PREFIX.match(lines[index]):
            match = _BODY_ITEM.fullmatch(_LISTED_BODY_ITEM_PREFIX.sub("", lines[index], count=1))
        if match is not None:
            item, title = match.group(1).upper(), match.group(2)
        elif (item := _TOC_ITEM.fullmatch(lines[index].strip())) is not None and index + 1 < len(lines):
            item, title = item.group(1).upper(), lines[index + 1].strip()
        else:
            continue
        body_candidates.append((item, title, index))
        key = (item, _title_key(title))
        if key in body_lines:
            body_lines[key].append(index)
    headings: list[tuple[str | None, str, str, int]] = []
    missing = []
    ambiguous: dict[tuple[str | None, str, str], list[int]] = {}
    for part, item, title in contents:
        matches = body_lines[(item, _title_key(title))]
        if not matches and form == "10-K":
            minor_key = _minor_title_key(title)
            matches = [index for candidate_item, candidate_title, index in body_candidates
                       if candidate_item == item
                       and _minor_title_key(re.sub(r"\s+\([^()]*\)\s*$", "", candidate_title)) == minor_key]
        if len(matches) > 1:
            if form != "10-Q":
                raise UnsupportedCapabilityError(f"SEC {form} has no verified section boundaries")
            ambiguous[(part, item, title)] = matches
            continue
        if not matches:
            missing.append((part, item, title))
        else:
            headings.append((part, item, title, matches[0]))
    if missing:
        if form != "10-Q":
            raise UnsupportedCapabilityError(f"SEC {form} has no verified section boundaries")
        anchors = _anchored_starts(document, missing, contents_end, lines)
        headings.extend((part, item, title, anchors[(part, item, title)]) for part, item, title in missing)
    if ambiguous:
        anchors = _anchored_starts(document, list(ambiguous), contents_end, lines, body_heading=True)
        for (part, item, title), matches in ambiguous.items():
            start = anchors[(part, item, title)]
            if start not in matches:
                raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
            headings.append((part, item, title, start))
    positions = {(part, item, title): start for part, item, title, start in headings}
    if len(set(positions.values())) != len(contents):
        raise UnsupportedCapabilityError(f"SEC {form} has no verified section boundaries")
    headings = [(part, item, title, positions[(part, item, title)]) for part, item, title in contents]
    if (form == "10-K" or not missing) and any(a[3] >= b[3] for a, b in zip(headings, headings[1:])):
        raise UnsupportedCapabilityError(f"SEC {form} has no verified section boundaries")
    if form == "10-Q":
        part_i = [start for part, _, _, start in headings if part == "I"]
        part_ii = [start for part, _, _, start in headings if part == "II"]
        if max(part_i) >= min(part_ii):
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
    physical = sorted(headings, key=lambda heading: heading[3])
    next_start = {heading[3]: physical[index + 1][3] if index + 1 < len(physical) else len(lines)
                  for index, heading in enumerate(physical)}

    sections = []
    for part, item, title, start in headings:
        end = next_start[start]
        if form == "10-Q" and part == "I" and item == "4":
            markers = [line_index for line_index in range(start + 1, end)
                       if (match := _PART.match(lines[line_index])) is not None
                       and match.group(1).upper() == "II"]
            if not markers:
                raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
            end = markers[0]
        elif form == "10-Q" and part == "II" and item == "6":
            markers = [line_index for line_index in range(start + 1, end)
                       if _SIGNATURE.fullmatch(lines[line_index].strip())]
            if not markers:
                raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
            end = markers[0]
        elif form == "10-K" and end == len(lines):
            markers = [line_index for line_index in range(start + 1, end)
                       if _SIGNATURE.fullmatch(lines[line_index].strip())]
            if markers:
                end = markers[0]
        sections.append(FilingSection(
            item=item, title=title, text="\n".join(lines[start:end]),
            document_id=document.document_id, source_url=document.source_url,
            start_line=start + 1, end_line=end, provenance=document.provenance,
            part=part,
            references=_item8_references(document, lines, start, end) if form == "10-K" and item == "8" else (),
        ))
    return sections


def sec_10k_sections(document: FilingDocument) -> list[FilingSection]:
    """Require a contents entry and one matching body heading per returned item."""
    if document.media_type != "text/html":
        raise UnsupportedCapabilityError("SEC 10-K verified section boundaries require an HTML original")
    lines = document.text().splitlines()
    contents: list[tuple[str, str]] = []
    contents_end = 0
    for index, line in enumerate(lines[: min(250, len(lines) - 1)]):
        match = _TOC_ITEM.fullmatch(line.strip())
        if match is None:
            continue
        item = match.group(1).upper()
        if contents and _item_order(item) <= _item_order(contents[-1][0]):
            break  # Running page labels after the contents are not new entries.
        title = lines[index + 1].strip()
        if not title:
            raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")
        contents.append((item, title))
        contents_end = index + 2
    try:
        if len(contents) < 5 or contents[0][0] != "1" or contents[-1][0] not in {"15", "16"}:
            contents = _numeric_10k_contents(document, lines)
            contents_end = 0
        return _build_sections(document, lines, [(None, item, title) for item, title in contents],
                               contents_end, "10-K")
    except UnsupportedCapabilityError:
        return _body_10k_sections(document, lines)


def _body_10k_sections(document: FilingDocument, lines: list[str]) -> list[FilingSection]:
    """Use source-order body headings when a complete 10-K contents match is unavailable."""
    from .sec_body import _ITEM, blocks, item_headings

    source = document.download()
    html = source.decode(html_encoding(source), errors="replace")  # as text() decodes it, so lines align
    source_blocks = blocks(html)
    headings = item_headings(source_blocks)
    if len(headings) < 15 or headings[0][0] != "1" or headings[-1][0] not in {"15", "16"}:
        raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")
    if (all(source_blocks[index].in_table for _, index in headings)
            and all(next_index - index <= 2 for (_, index), (_, next_index) in zip(headings, headings[1:]))
            and not any(not block.in_table for block in source_blocks[headings[0][1]:headings[-1][1] + 1])):
        # Adjacent rows in one index table are references, not report bodies.
        raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")

    starts = html_to_text_line_offsets(html, [source_blocks[index].start for _, index in headings])
    positioned = []
    for (code, block_index), start in zip(headings, starts):
        block = source_blocks[block_index]
        match = _ITEM.match(block.text)
        if match is None or match.group(1).upper() != code:
            raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")
        group = _GROUPED_BODY_ITEMS.fullmatch(block.text)
        items = (code,)
        if group is not None:
            numbers = tuple(int(number) for number in re.findall(r"\d{1,2}", group.group(1)))
            if (not block.bold or block.in_table or numbers[0] != int(code)
                    or numbers != tuple(range(numbers[0], numbers[-1] + 1)) or numbers[-1] > 16):
                raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")
            items = tuple(str(number) for number in numbers)
        title = group.group(2) if group is not None else block.text[match.end():].strip(" .:\u2014\u2013-")
        if not title and block_index + 1 < len(source_blocks):
            title = source_blocks[block_index + 1].text
        if not title or (group is None and len(title) > 180):
            raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")
        if start >= len(lines) or " ".join(lines[start].split()) != " ".join(block.text.split()):
            raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")
        positioned.append((code, title, start, items))
    if any(a[2] >= b[2] for a, b in zip(positioned, positioned[1:])):
        raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")
    if any(any(other[0] in entry[3][1:] for other in positioned[index + 1:])
           for index, entry in enumerate(positioned) if len(entry[3]) > 1):
        raise UnsupportedCapabilityError("SEC 10-K has no verified section boundaries")

    sections = []
    for index, (code, title, start, items) in enumerate(positioned):
        end = positioned[index + 1][2] if index + 1 < len(positioned) else len(lines)
        if index + 1 == len(positioned):
            end = next((i for i in range(start + 1, end) if _SIGNATURE.fullmatch(lines[i].strip())), end)
        sections.append(FilingSection(
            item=f"{items[0]}-{items[-1]}" if len(items) > 1 else code,
            items=items, title=title, text="\n".join(lines[start:end]),
            document_id=document.document_id, source_url=document.source_url,
            start_line=start + 1, end_line=end, provenance=document.provenance,
            references=_item8_references(document, lines, start, end) if code == "8" else (),
        ))
    return sections


def sec_10q_sections(document: FilingDocument) -> list[FilingSection]:
    """Verify both Part I and Part II Item headings against the original contents."""
    if document.media_type != "text/html":
        raise UnsupportedCapabilityError("SEC 10-Q verified section boundaries require an HTML original")
    lines = document.text().splitlines()
    contents: list[tuple[str, str, str]] = []
    part: str | None = None
    contents_end = 0
    for index, line in enumerate(lines[: min(250, len(lines) - 1)]):
        part_match = _PART.match(line.strip())
        if part_match is not None:
            next_part = part_match.group(1).upper()
            if part == "II" and next_part == "I":
                break  # Body restarts at Part I after the contents.
            part = next_part
            continue
        match = _TOC_ITEM.fullmatch(line.strip())
        inline = None if match is not None else _BODY_ITEM.fullmatch(line.strip())
        if (match is None and inline is None) or part is None:
            continue
        item = (match or inline).group(1).upper()
        if contents and contents[-1][0] == part and _item_order(item) <= _item_order(contents[-1][1]):
            break
        title = lines[index + 1].strip() if match is not None else inline.group(2).strip()
        if not title:
            raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
        contents.append((part, item, title))
        contents_end = index + (2 if match is not None else 1)
    part_i = [item for section_part, item, _ in contents if section_part == "I"]
    part_ii = [item for section_part, item, _ in contents if section_part == "II"]
    if (len(contents) < 6 or not part_i or not part_ii
            or part_i[0] != "1" or part_i[-1] != "4"
            or part_ii[0] != "1" or part_ii[-1] != "6"):
        raise UnsupportedCapabilityError("SEC 10-Q has no verified section boundaries")
    return _build_sections(document, lines, contents, contents_end, "10-Q")


def _8k_headings(lines: list[str], start: int, end: int) -> list[tuple[str, str, int]]:
    headings = []
    seen = set()
    for index in range(start, end):
        line = lines[index]
        match = _8K_ITEM.fullmatch(line.strip())
        if match is None or match.group(1) not in _8K_CAPTION_STARTS:
            continue
        code, title = match.group(1), match.group(2).strip()
        if not title and index + 1 < end:
            title = lines[index + 1].strip()
        if _title_key(title)[:2] != _title_key(_8K_CAPTION_STARTS[code]):
            continue
        if code in seen:
            raise UnsupportedCapabilityError("SEC 8-K has no verified section boundaries")
        seen.add(code)
        headings.append((code, title, index))
    return headings


def sec_8k_sections(document: FilingDocument) -> list[FilingSection]:
    """Expose only source-captioned 8-K Items with a visible signature boundary."""
    if document.media_type != "text/html":
        raise UnsupportedCapabilityError("SEC 8-K verified section boundaries require an HTML original")
    lines = document.text().splitlines()
    signatures = [index for index, line in enumerate(lines) if _SIGNATURE.fullmatch(line.strip())]
    if len(signatures) == 1:
        signature = signatures[0]
        headings = _8k_headings(lines, 0, signature)
    elif len(signatures) == 2:
        contents = [index for index, line in enumerate(lines[:signatures[0]])
                    if line.strip().casefold() == "table of contents"]
        if len(contents) != 1:
            raise UnsupportedCapabilityError("SEC 8-K has no verified section boundaries")
        toc = _8k_headings(lines, contents[0] + 1, signatures[0])
        signature = signatures[1]
        headings = _8k_headings(lines, signatures[0] + 1, signature)
        if [(code, _title_key(title)) for code, title, _ in toc] != [
            (code, _title_key(title)) for code, title, _ in headings
        ]:
            raise UnsupportedCapabilityError("SEC 8-K has no verified section boundaries")
    else:
        raise UnsupportedCapabilityError("SEC 8-K has no verified section boundaries")
    if not headings:
        raise UnsupportedCapabilityError("SEC 8-K has no verified section boundaries")
    return [FilingSection(
        item=code, title=title, text="\n".join(lines[start:end]),
        document_id=document.document_id, source_url=document.source_url,
        start_line=start + 1, end_line=end, provenance=document.provenance,
    ) for (code, title, start), end in zip(headings, [entry[2] for entry in headings[1:]] + [signature])]
