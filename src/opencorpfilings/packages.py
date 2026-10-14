"""Find the report inside an original source package by its content, not its file name.

ESEF and national OAM packages wrap the report XHTML at different depths: a
plain ZIP, an `.xbri`/`.zip` inside it, a gzip-compressed `.xbri` inside a KNF
`.rap`, or a signed `.asice` container. Every adapter used to take the first
top-level `.xhtml`/`.html` name, which missed nested reports and decoded gzip
bytes as text. This walker sniffs each member's first bytes instead.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .errors import ParseError, UnsupportedCapabilityError
from .models import Filing, FilingArchiveMember, FilingDocument, FilingFact, _looks_like_markup as is_markup

REPORT_SUFFIXES = (".xhtml", ".html", ".htm")
MAX_PACKAGE_DEPTH = 4
_ZIP_MAGIC = b"PK\x03\x04"
_GZIP_MAGIC = b"\x1f\x8b"


def _is_package(head: bytes) -> bool:
    return head.startswith((_ZIP_MAGIC, _GZIP_MAGIC))


def _walk(members: list[FilingArchiveMember], depth: int, found: list[FilingArchiveMember]) -> None:
    for member in members:
        head = member._head()
        named_report = PurePosixPath(member.entry_path).suffix.lower() in REPORT_SUFFIXES
        if _is_package(head):
            try:
                if depth >= MAX_PACKAGE_DEPTH:
                    raise UnsupportedCapabilityError("package nesting bound reached")
                nested = member.members
            except (UnsupportedCapabilityError, ParseError):
                # Not a package after all: KNF gzips every attachment, a bare XHTML report included.
                if named_report and head.startswith(_GZIP_MAGIC) and is_markup(member._markup_head()):
                    found.append(member)
                continue
            _walk(nested, depth + 1, found)
        elif named_report and is_markup(head):
            found.append(member)


# ESEF names a report <issuer>-<period end>[-<n>]-<language>.xhtml.
_ESEF_NAME = re.compile(r"-\d{4}-\d{2}-\d{2}(?:-\d+)?-[a-z]{2}\.x?html?\Z", re.IGNORECASE)


def _rank(member: FilingArchiveMember) -> tuple[bool, bool, bool, int]:
    path = f"/{member.entry_path.lower()}"
    return ("/reports/" in path, bool(_ESEF_NAME.search(path)), path.endswith(".xhtml"), member.size)


def report_members(document: FilingDocument) -> list[FilingArchiveMember]:
    """Markup members of a package, nested packages included, in package order."""
    found: list[FilingArchiveMember] = []
    _walk(document.members, 1, found)
    return found


def best_reports(document: FilingDocument) -> list[FilingArchiveMember]:
    """Markup members best report first: under `reports/`, then XHTML, then larger."""
    return sorted(report_members(document), key=_rank, reverse=True)


def package_text(document: FilingDocument, *, label: str) -> str:
    """Text of a direct HTML/XHTML document, or of the best report inside a package."""
    if document.media_type in {"application/xhtml+xml", "text/html"}:
        return document._html_text()
    if document.media_type == "application/zip":
        reports = best_reports(document)
        if reports:
            return reports[0].text()
        raise UnsupportedCapabilityError(
            f"{label} file {document.filename} holds no HTML/XHTML report, nested packages included")
    raise UnsupportedCapabilityError(f"{label} file {document.filename} has no supported text")


def package_facts(filing: Filing, *, name: str, regulator: str, jurisdiction: str, label: str) -> list[FilingFact]:
    """Inline XBRL facts from the first document whose best XHTML report yields any."""
    from .raw_xbrl import parse_ixbrl_xhtml

    for document in filing.documents:
        if document.media_type == "application/xhtml+xml":
            candidates = [(document.filename, document)]
        elif document.media_type == "application/zip":
            candidates = [("::".join(member._path_chain) or member.entry_path, member)
                          for member in best_reports(document) if member.entry_path.lower().endswith(".xhtml")]
        else:
            continue
        for entry_path, source in candidates:
            with source._parse_content() as content:
                facts = parse_ixbrl_xhtml(content, document_url=document.source_url, entry_path=entry_path,
                                          provider=name, regulator=regulator, jurisdiction=jurisdiction,
                                          filing_id=filing.filing_id)
            if facts:
                return facts
    raise UnsupportedCapabilityError(f"{label} filing {filing.filing_id} has no parsed inline facts")
