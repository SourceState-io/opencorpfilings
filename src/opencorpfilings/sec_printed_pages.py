"""Locate SEC printed pages only when HTML breaks verify the footer sequence."""

from __future__ import annotations

import re

from .errors import UnsupportedCapabilityError
from .html_text import html_to_text_line_offsets
from .models import FilingDocument, FilingPrintedPage, Provenance


_BREAK = re.compile(r"page-break-(?:before|after)\s*:\s*always|break-(?:before|after)\s*:\s*page", re.I)
_LABEL = re.compile(r"F-(\d{1,3})", re.I)
_NUMBERED_AFTER = re.compile(r"(.+?\b(?:Annual Report|FORM 10-K))\s+(\d{1,3})", re.I)
_NUMBERED_BEFORE = re.compile(r"(\d{1,3})\s+(.+?\b(?:Annual Report|FORM 10-K))", re.I)
_NUMBERED_TITLE = re.compile(r".+?\b(?:Annual Report|FORM 10-K)", re.I)


def _numbered_footer(footer: str) -> tuple[int, str] | None:
    after = _NUMBERED_AFTER.fullmatch(footer)
    before = _NUMBERED_BEFORE.fullmatch(footer) if after is None else None
    if after is None and before is None:
        return None
    number, prefix = (after.group(2), after.group(1)) if after else (before.group(1), before.group(2))
    return int(number), " ".join(prefix.casefold().split())


def _numbered_tail(lines: list[str], start: int, end: int) -> tuple[int, str] | None:
    result = _numbered_footer(lines[end - 1].strip())
    if result is not None or end - start < 2:
        return result
    first, second = lines[end - 2].strip(), lines[end - 1].strip()
    for number, title in ((first, second), (second, first)):
        if re.fullmatch(r"[1-9]\d{0,2}", number) and _NUMBERED_TITLE.fullmatch(title):
            return int(number), " ".join(title.casefold().split())
    return None


def verified_pages(document: FilingDocument, label: str) -> dict[str, FilingPrintedPage]:
    """Return one verified run; index labels and unverified layouts fail closed."""
    financial = _LABEL.fullmatch(label)
    numbered = re.fullmatch(r"[1-9]\d{0,2}", label)
    if (financial is None and numbered is None) or document.media_type not in {"text/html", "application/xhtml+xml"}:
        raise UnsupportedCapabilityError("SEC printed page requires an F-page or numbered label in an HTML original")

    html = document.html()
    lines = document.text().splitlines()
    offsets = [match.start() for match in _BREAK.finditer(html)]
    ends = sorted(set(html_to_text_line_offsets(html, offsets))) if offsets else []
    candidates: list[tuple[int, int, int, int, str]] = []
    start = 0
    for segment_index, end in enumerate(ends):
        if start < end <= len(lines):
            footer = lines[end - 1].strip()
            if financial is not None and (match := _LABEL.fullmatch(footer)):
                candidates.append((segment_index, int(match.group(1)), start, end, "F-"))
            elif numbered is not None and (numbered_footer := _numbered_tail(lines, start, end)):
                candidates.append((segment_index, numbered_footer[0], start, end, numbered_footer[1]))
        start = end

    runs: list[list[tuple[int, int, int, int, str]]] = []
    for candidate in candidates:
        if financial is not None and candidate[1] == 1:
            runs.append([candidate])
        elif (runs and candidate[0] == runs[-1][-1][0] + 1
              and candidate[1] == runs[-1][-1][1] + 1
              and candidate[4] == runs[-1][-1][4]):
            runs[-1].append(candidate)
        elif numbered is not None:
            runs.append([candidate])
    if not runs:
        raise UnsupportedCapabilityError("SEC printed page has no verified page sequence")
    longest = max(len(run) for run in runs)
    if longest < 3:
        raise UnsupportedCapabilityError("SEC printed page has no verified page sequence")
    selected = [run for run in runs if len(run) == longest]
    if len(selected) != 1:
        raise UnsupportedCapabilityError("SEC printed page sequence is ambiguous")
    pages = {}
    for _, number, start, end, _ in selected[0]:
        page_label = f"F-{number}" if financial is not None else str(number)
        pages[page_label] = FilingPrintedPage(
            label=page_label, text="\n".join(lines[start:end]), document_id=document.document_id,
            source_url=document.source_url, start_line=start + 1, end_line=end,
            provenance=Provenance(
                document.provenance.provider, document.provenance.regulator,
                document.provenance.jurisdiction, document.source_url,
                f"{document.document_id}:printed-page:{page_label}", document.provenance.retrieved_at,
                {"document_id": document.document_id, "printed_page": page_label,
                 "start_line": start + 1, "end_line": end},
            ),
        )
    return pages
