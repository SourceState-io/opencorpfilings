"""Source-preserving public objects."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from itertools import islice
from io import BytesIO
import gzip
import hashlib
import json
import html as html_lib
import os
from pathlib import Path
import re
import tempfile
import weakref
import zlib
from typing import Any, Literal, TYPE_CHECKING
import zipfile

from .errors import (DownloadError, FilingNotFoundError, ParseError, ProviderError, OpenCorpFilingsError,
                     UnsupportedCapabilityError)

if TYPE_CHECKING:
    from .provider import FilingProvider


FILING_CATEGORIES = frozenset({
    "ANNUAL", "QUARTERLY", "INTERIM", "CURRENT", "PROSPECTUS", "OWNERSHIP", "OTHER",
})
MAX_ARCHIVE_MEMBER_BYTES = 100_000_000
_STREAM_PARSE_MEMBER_BYTES = 16_000_000
# A member above the in-memory bound is parsed from a temporary file. Large
# ESEF reports are real (Repsol FY2025: 131.8 MB XHTML, 1.9x compression), so
# the file path allows up to 2 GB when the compression ratio is plausible.
MAX_STREAMED_MEMBER_BYTES = 2_000_000_000
_MAX_COMPRESSION_RATIO = 200
_BINARY_PREFIXES = {"application/pdf": b"%PDF-", "application/zip": b"PK\x03\x04"}
# What a document is within its filing. "report" is the filed report or
# statement itself (or its package); "generated" is a file the source system
# produced (indexes, renderings, full-submission text).
DOCUMENT_ROLES = ("report", "exhibit", "annex", "announcement", "data", "generated", "other")
_ROLE_RANK = {"report": 0, None: 1, "annex": 2, "exhibit": 3, "announcement": 4, "other": 5, "data": 6, "generated": 7}
_FORMAT_RANK = {"application/zip": 0, "application/xhtml+xml": 1, "application/pdf": 2, "text/html": 3}
_FACT_COLUMNS = ("concept_raw", "value", "unit", "period_start", "period_end", "context_id",
                 "dimensions", "taxonomy", "source_location", "source_url", "provider")


def _file_stat(path: Path) -> tuple[int, int]:
    status = path.stat()
    return status.st_size, status.st_mtime_ns


def _check_binary_original(content: bytes, media_type: str | None, source_url: str) -> None:
    if not content:
        raise DownloadError(f"source returned an empty document for {source_url}")
    prefix = _BINARY_PREFIXES.get(media_type)
    if prefix is not None and not content.startswith(prefix):
        raise DownloadError(f"source bytes do not match {media_type} for {source_url}")
    if media_type == "application/zip":
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                archive.infolist()
        except zipfile.BadZipFile as exc:
            raise DownloadError(f"source returned an invalid ZIP for {source_url}") from exc


def _choose_primary(documents: list[FilingDocument]) -> FilingDocument:
    """One source-flagged document wins; otherwise the report role, then format, then source order."""
    flagged = [document for document in documents if document.is_primary]
    if len(flagged) == 1:
        return flagged[0]
    pool = flagged or documents
    return min(enumerate(pool), key=lambda item: (
        _ROLE_RANK.get(item[1].role, 5), _FORMAT_RANK.get(item[1].media_type, 4), item[0],
    ))[1]


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _looks_like_markup(head: bytes) -> bool:
    """True when bytes begin like an HTML/XHTML/XML document, after a BOM and whitespace."""
    return head.removeprefix(b"\xef\xbb\xbf").lstrip().startswith(b"<")


def _json_safe(value: Any) -> Any:
    """Source values as JSON types: dates as ISO strings, sequences as lists, nothing converted to numbers."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _pandas():
    try:
        import pandas
    except ImportError as exc:
        raise UnsupportedCapabilityError(
            "DataFrames require the optional 'pandas' extra (the pandas package)"
        ) from exc
    return pandas


def _html_table(title: str, rows: list[tuple[str, Any]], source_url: str | None) -> str:
    """A small escaped key/value table for notebook display."""
    cells = "".join(
        f"<tr><th style='text-align:left'>{html_lib.escape(key)}</th>"
        f"<td style='text-align:left'>{html_lib.escape(str(value))}</td></tr>"
        for key, value in rows if value is not None
    )
    if source_url:
        link = html_lib.escape(source_url, quote=True)
        cells += (f"<tr><th style='text-align:left'>source</th><td style='text-align:left'>"
                  f'<a href="{link}" target="_blank" rel="noopener">{html_lib.escape(source_url)}</a></td></tr>')
    return f"<table><caption style='text-align:left'><b>{html_lib.escape(title)}</b></caption>{cells}</table>"


@dataclass(frozen=True, slots=True)
class Identifier:
    kind: str
    value: str
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class Provenance:
    provider: str
    regulator: str
    jurisdiction: str
    source_url: str
    source_id: str
    retrieved_at: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Entity:
    entity_id: str
    name: str
    jurisdiction: str
    provider: str
    source_url: str
    identifiers: tuple[Identifier, ...] = ()
    tickers: tuple[str, ...] = ()
    exchanges: tuple[str, ...] = ()
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
    requires_resolution: bool = False

    def __repr__(self) -> str:
        return f"<Entity {self.entity_id} {self.name!r} {self.jurisdiction}/{self.provider}>"

    def _repr_html_(self) -> str:
        return _html_table(f"Entity {self.name}", [
            ("entity_id", self.entity_id), ("market", self.jurisdiction), ("provider", self.provider),
            ("tickers", ", ".join(self.tickers) or None),
        ], self.source_url)


@dataclass(frozen=True, slots=True)
class FilingFact:
    concept_raw: str
    value: str
    unit: str | None
    period_start: date | None
    period_end: date | None
    context_id: str | None
    dimensions: Mapping[str, str]
    taxonomy: str | None
    source_location: str | None
    provenance: Provenance
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        period = f"{self.period_start or ''}..{self.period_end}" if self.period_end else ""
        parts = [f"{self.concept_raw}={self.value!r}", self.unit or "", period,
                 f"dims={len(self.dimensions)}" if self.dimensions else ""]
        return "<FilingFact " + " ".join(part for part in parts if part) + ">"

    def to_dict(self) -> dict[str, Any]:
        """One JSON-safe row; `value` stays the filed string, never a converted number."""
        return {
            "concept_raw": self.concept_raw, "value": self.value, "unit": self.unit,
            "period_start": _json_safe(self.period_start), "period_end": _json_safe(self.period_end),
            "context_id": self.context_id, "dimensions": _json_safe(self.dimensions),
            "taxonomy": self.taxonomy, "source_location": self.source_location,
            "source_url": self.provenance.source_url, "provider": self.provenance.provider,
        }


@dataclass(frozen=True, slots=True)
class FilingPage:
    """Text from one original PDF page, retaining its document source."""

    number: int
    text: str
    document_id: str
    source_url: str
    provenance: Provenance

    @property
    def source_location(self) -> str:
        """Document URL with the page anchor, for citation."""
        return f"{self.source_url}#page={self.number}"


@dataclass(frozen=True, slots=True)
class FilingPrintedPage:
    """A verified HTML printed page, retaining its original text-line span."""

    label: str
    text: str
    document_id: str
    source_url: str
    start_line: int
    end_line: int
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class FilingSectionReference:
    """As-filed pointer near a section heading; the target is not parsed content."""

    kind: Literal["page", "page_range", "document"]
    target: str
    source_text: str
    document_id: str
    source_url: str
    source_line: int
    provenance: Provenance

    def resolve(self, filing: Filing) -> FilingDocument | FilingPrintedPage | tuple[FilingPrintedPage, ...]:
        """Follow a verified source pointer without merging it into section text."""
        original = filing.primary_document
        if original.document_id != self.document_id or original.source_url != self.source_url:
            raise UnsupportedCapabilityError("section reference does not belong to this filing's primary document")
        if self.kind == "document":
            return filing.select_document(document_type=self.target)
        if self.kind == "page_range":
            first, last = map(int, self.target.split("-", 1))
            return tuple(original.printed_page(str(number)) for number in range(first, last + 1))
        return original.printed_page(self.target)


@dataclass(frozen=True, slots=True)
class FilingSection:
    """Source-linked Item span; ``items`` names every Item in a shared heading."""

    item: str
    title: str
    text: str
    document_id: str
    source_url: str
    start_line: int
    end_line: int
    provenance: Provenance
    part: str | None = None
    references: tuple[FilingSectionReference, ...] = ()
    items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.items:
            object.__setattr__(self, "items", (self.item,))


@dataclass(frozen=True, slots=True)
class FilingTableCell:
    """One literal HTML cell; spans are source attribute strings."""

    text: str
    tag: str
    rowspan: str | None = None
    colspan: str | None = None


@dataclass(frozen=True, slots=True)
class FilingTable:
    """One HTML table tag in document order, without inferred column alignment."""

    index: int
    caption: str | None
    rows: tuple[tuple[FilingTableCell, ...], ...]
    source_url: str
    source_location: str
    provenance: Provenance


@dataclass(slots=True)
class FilingDocument:
    document_id: str
    filing_id: str
    filename: str
    source_url: str
    provenance: Provenance
    media_type: str | None = None
    document_type: str | None = None
    language: str | None = None
    is_primary: bool = False
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)
    description: str | None = None
    role: str | None = None
    _provider: FilingProvider | None = field(default=None, repr=False, compare=False)
    _cached_bytes: bytes | None = field(default=None, repr=False, compare=False)
    _saved_path: Path | None = field(default=None, repr=False, compare=False)
    _saved_sha256: str | None = field(default=None, repr=False, compare=False)
    _saved_stat: tuple[int, int] | None = field(default=None, repr=False, compare=False)  # size, mtime when verified
    _content_sha256: str | None = field(default=None, repr=False, compare=False)
    _source_at_cache: str | None = field(default=None, repr=False, compare=False)
    _text_cache: str | None = field(default=None, repr=False, compare=False)
    _markdown_cache: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    _pages_cache: tuple[FilingPage, ...] | None = field(default=None, repr=False, compare=False)
    _single_pages_cache: dict[int, FilingPage] = field(default_factory=dict, repr=False, compare=False)
    _printed_pages_cache: dict[str, FilingPrintedPage] = field(default_factory=dict, repr=False, compare=False)
    _members_cache: list[FilingArchiveMember] | None = field(default=None, repr=False, compare=False)
    _tables_cache: dict[str | None, tuple[FilingTable, ...]] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.role is not None and self.role not in DOCUMENT_ROLES:
            raise ValueError(f"role must be one of {DOCUMENT_ROLES} or None, not {self.role!r}")

    def __repr__(self) -> str:
        parts = [self.filename, self.media_type or "", self.document_type or "", self.role or "",
                 "primary" if self.is_primary else ""]
        return "<FilingDocument " + " ".join(part for part in parts if part) + ">"

    def _repr_html_(self) -> str:
        return _html_table(f"Document {self.filename}", [
            ("document_id", self.document_id), ("filing_id", self.filing_id),
            ("document_type", self.document_type), ("role", self.role), ("media_type", self.media_type),
            ("description", self.description), ("language", self.language), ("primary", self.is_primary),
        ], self.source_url)

    def to_dict(self) -> dict[str, Any]:
        """One JSON-safe row describing the source document, without its content."""
        return {
            "document_id": self.document_id, "filing_id": self.filing_id, "filename": self.filename,
            "document_type": self.document_type, "role": self.role, "media_type": self.media_type,
            "description": self.description, "is_primary": self.is_primary,
            "language": self.language, "source_url": self.source_url,
        }

    def _check_cached_source(self) -> None:
        if (self.source_url != self.provenance.source_url
                or (self._source_at_cache is not None and self.source_url != self._source_at_cache)):
            raise DownloadError("document source URL changed after selection")

    def download(self, path: str | Path | None = None) -> bytes | Path:
        """Original bytes, or stream them to `path` and return it; verified against the source."""
        self._check_cached_source()
        if self._provider is None:
            raise RuntimeError("document is not bound to a provider")
        target = Path(path) if path is not None else None
        if self._cached_bytes is None and self._saved_path is not None:
            if target is not None and target.resolve() != self._saved_path:
                if self._copy_saved_to(target):
                    return target
                self._saved_path = self._saved_sha256 = None
            else:
                try:
                    if target is not None:
                        # A package's members each read it through here; hash it again only once it changes.
                        if self._saved_stat is not None and self._saved_stat == _file_stat(self._saved_path):
                            return target
                        with self._saved_path.open("rb") as saved:
                            digest = hashlib.file_digest(saved, "sha256").hexdigest()
                        if digest == self._saved_sha256:
                            self._saved_stat = _file_stat(self._saved_path)
                            return target
                    else:
                        content = self._saved_path.read_bytes()
                        if hashlib.sha256(content).hexdigest() == self._saved_sha256:
                            self._cached_bytes = content
                except OSError:
                    pass
                if self._cached_bytes is None:
                    self._saved_path = self._saved_sha256 = None
        if target is not None and self._cached_bytes is None and self._provider.supports("streamed_download"):
            saved = self._provider.save_document(self, target)
            self._saved_path = saved.resolve()
            with saved.open("rb") as content:
                self._saved_sha256 = hashlib.file_digest(content, "sha256").hexdigest()
            self._saved_stat = _file_stat(self._saved_path)
            self._source_at_cache = self.source_url
            return saved
        if self._cached_bytes is None:
            content = self._provider.download_document(self)
            _check_binary_original(content, self.media_type, self.source_url)
            self._cached_bytes = content
            self._source_at_cache = self.source_url
        else:
            content = self._cached_bytes
            _check_binary_original(content, self.media_type, self.source_url)
        if target is None:
            return content
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(content)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def sha256(self) -> str:
        """Hash the selected original bytes, reusing a verified saved copy."""
        self._check_cached_source()
        if self._cached_bytes is not None:
            return hashlib.sha256(self.download()).hexdigest()
        if self._cached_bytes is None and self._saved_path is not None:
            self.download(self._saved_path)
            if self._saved_sha256 is not None:
                return self._saved_sha256
        if self._content_sha256 is not None:
            return self._content_sha256
        if self._provider is None:
            raise RuntimeError("document is not bound to a provider")
        if self._provider.supports("streamed_download"):
            with tempfile.TemporaryDirectory(prefix="ocf-hash-") as temporary:
                saved = self._provider.save_document(self, Path(temporary) / "original")
                with saved.open("rb") as content:
                    digest = hashlib.file_digest(content, "sha256").hexdigest()
            self._content_sha256 = digest
            self._source_at_cache = self.source_url
            return digest
        return hashlib.sha256(self.download()).hexdigest()

    def _copy_saved_to(self, target: Path) -> bool:
        """Verify and atomically copy a prior streamed save without buffering it."""
        assert self._saved_path is not None
        try:
            source = self._saved_path.open("rb")
        except OSError:
            return False
        with source:
            fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
            try:
                digest = hashlib.sha256()
                with os.fdopen(fd, "wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != self._saved_sha256:
                    return False
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        self._saved_path = target.resolve()
        return True

    def _archive_source(self) -> Path | BytesIO:
        """Open a verified saved ZIP directly, avoiding a full package byte buffer."""
        if self._cached_bytes is None and self._saved_path is not None:
            return self.download(self._saved_path)
        return BytesIO(self.download())

    @contextmanager
    def _parse_content(self) -> Iterator[bytes | Path]:
        """Return a verified saved original or its requested byte content."""
        self._check_cached_source()
        if self._cached_bytes is None and self._saved_path is not None:
            yield self.download(self._saved_path)
        else:
            yield self.download()

    def html(self, *, encoding: str | None = None) -> str:
        """Decode the selected original HTML/XHTML."""
        self._check_cached_source()
        if self.provider_metadata.get("format_discovered_on_download"):
            self.download()
        if self.media_type not in {"text/html", "application/xhtml+xml"}:
            raise UnsupportedCapabilityError(
                f"HTML/XHTML is unavailable for {self.media_type or self.filename}; "
                "select an HTML/XHTML archive member when the source is a ZIP"
            )
        from .html_text import read_html

        with self._parse_content() as content:
            return read_html(content, encoding)

    def _html_text(self, *, encoding: str | None = None) -> str:
        """Read HTML text from a verified saved original when available."""
        from .html_text import html_to_text

        with self._parse_content() as content:
            return html_to_text(content, encoding=encoding)

    def markdown(self, *, encoding: str | None = None) -> str:
        """Render one selected HTML/XHTML original as Markdown on demand."""
        self._check_cached_source()
        if self.provider_metadata.get("format_discovered_on_download"):
            self.download()
        if self.media_type not in {"text/html", "application/xhtml+xml"}:
            raise UnsupportedCapabilityError(
                f"HTML/XHTML Markdown is unavailable for {self.media_type or self.filename}; "
                "select an HTML/XHTML archive member when the source is a ZIP"
            )
        if encoding not in self._markdown_cache:
            from .markdown_text import html_to_markdown

            with self._parse_content() as content:
                self._markdown_cache[encoding] = html_to_markdown(content, encoding=encoding)
        return self._markdown_cache[encoding]

    def text(self) -> str:
        """Extracted text where the format supports it; PDFs without a text layer give empty text."""
        self._check_cached_source()
        if self._provider is None:
            raise RuntimeError("document is not bound to a provider")
        if self._text_cache is not None:
            return self._text_cache
        if self.media_type == "application/pdf":
            if self._saved_path is None or self._cached_bytes is not None:
                self.download()  # An unsaved source may resolve its listed PDF link to XHTML.
            if self.media_type == "application/pdf":
                pages = self.pages
                self._text_cache = "\n\n".join(page.text for page in pages) if any(page.text.strip() for page in pages) else ""
                self._source_at_cache = self.source_url
                return self._text_cache
        self._text_cache = self._provider.extract_text(self)
        self._source_at_cache = self.source_url
        return self._text_cache

    @property
    def pages(self) -> tuple[FilingPage, ...]:
        """Every PDF page with its original page number (optional `pdf` extra)."""
        self._check_cached_source()
        if self.media_type != "application/pdf":
            raise UnsupportedCapabilityError(f"PDF pages are not available for {self.media_type or self.filename}")
        if self._pages_cache is None:
            from .pdf_text import extract_pdf_pages

            with self._parse_content() as content:
                if self.media_type != "application/pdf":
                    raise UnsupportedCapabilityError(f"PDF pages are not available for {self.media_type or self.filename}")
                self._pages_cache = tuple(
                    self._make_page(number, body)
                    for number, body in enumerate(extract_pdf_pages(content), start=1)
                )
        return self._pages_cache

    def page(self, number: int) -> FilingPage:
        """Extract one original PDF page by its one-based number."""
        self._check_cached_source()
        if self.media_type != "application/pdf":
            raise UnsupportedCapabilityError(f"PDF pages are not available for {self.media_type or self.filename}")
        if number < 1:
            raise ValueError("PDF page number must be positive")
        if self._pages_cache is not None:
            if number > len(self._pages_cache):
                raise IndexError(f"PDF page {number} is out of range (1-{len(self._pages_cache)})")
            return self._pages_cache[number - 1]
        if number not in self._single_pages_cache:
            from .pdf_text import extract_pdf_page

            with self._parse_content() as content:
                if self.media_type != "application/pdf":
                    raise UnsupportedCapabilityError(f"PDF pages are not available for {self.media_type or self.filename}")
                self._single_pages_cache[number] = self._make_page(number, extract_pdf_page(content, number))
        return self._single_pages_cache[number]

    def printed_page(self, label: str) -> FilingPrintedPage:
        """Read one SEC HTML page verified by consecutive printed footers."""
        self._check_cached_source()
        if self.provenance.provider != "sec":
            raise UnsupportedCapabilityError("printed-page navigation is available for SEC HTML originals only")
        from .sec_printed_pages import _LABEL, verified_pages

        financial = _LABEL.fullmatch(label)
        key = f"F-{int(financial.group(1))}" if financial is not None else label
        if key not in self._printed_pages_cache:
            self._printed_pages_cache.update(verified_pages(self, label))
        if key not in self._printed_pages_cache:
            raise UnsupportedCapabilityError(f"SEC printed page {label} is unavailable in the verified sequence")
        return self._printed_pages_cache[key]

    def _make_page(self, number: int, body: str) -> FilingPage:
        return FilingPage(
            number=number, text=body, document_id=self.document_id,
            source_url=self.source_url,
            provenance=Provenance(
                self.provenance.provider, self.provenance.regulator,
                self.provenance.jurisdiction, self.source_url,
                f"{self.document_id}:page:{number}", self.provenance.retrieved_at,
                {"document_id": self.document_id, "page_number": number},
            ),
        )

    def tables(self, *, encoding: str | None = None) -> list[FilingTable]:
        """Inspect literal table tags in one HTML/XHTML document."""
        self._check_cached_source()
        if self.provider_metadata.get("format_discovered_on_download"):
            self.download()
        if self.media_type not in {"text/html", "application/xhtml+xml"}:
            raise UnsupportedCapabilityError(
                f"HTML/XHTML tables are unavailable for {self.media_type or self.filename}; "
                "select an HTML/XHTML archive member when the source is a ZIP"
            )
        if encoding not in self._tables_cache:
            from .html_tables import extract_html_tables

            content = (
                self.download(self._saved_path)
                if self._cached_bytes is None and self._saved_path is not None
                else self.download()
            )
            self._tables_cache[encoding] = extract_html_tables(
                content, provenance=self.provenance, source_location=self.source_url,
                encoding=encoding,
            )
        return list(self._tables_cache[encoding])

    @property
    def members(self) -> list[FilingArchiveMember]:
        """List files inside one selected original ZIP package on demand."""
        self._check_cached_source()
        if self.media_type is None and self.provider_metadata.get("format_discovered_on_download"):
            self.download()
        if self.media_type != "application/zip":
            raise UnsupportedCapabilityError(f"{self.filename} is not a ZIP source package")
        if self._members_cache is None:
            try:
                with zipfile.ZipFile(
                    self._archive_source(), metadata_encoding=self.provider_metadata.get("archive_encoding")
                ) as archive:
                    seen: set[str] = set()
                    members = []
                    for info in archive.infolist():
                        if info.is_dir():
                            continue
                        if info.filename in seen:
                            raise ParseError(f"ZIP package {self.filename} has duplicate entry {info.filename}")
                        seen.add(info.filename)
                        raw = {"package_document_id": self.document_id, "entry_path": info.filename,
                               "size": info.file_size, "compressed_size": info.compress_size, "crc": info.CRC}
                        members.append(FilingArchiveMember(
                            entry_path=info.filename,
                            source_url=self.source_url,
                            provenance=Provenance(self.provenance.provider, self.provenance.regulator,
                                                  self.provenance.jurisdiction, self.source_url,
                                                  f"{self.document_id}::{info.filename}",
                                                  datetime.now(timezone.utc), raw),
                            size=info.file_size,
                            _path_chain=(info.filename,),
                            _package=self,
                        ))
                    self._members_cache = members
            except zipfile.BadZipFile as exc:
                raise ParseError(f"{self.filename} is not a valid ZIP package") from exc
        return list(self._members_cache)


@dataclass(slots=True, weakref_slot=True)
class FilingArchiveMember:
    """One file inside an original source ZIP; provenance stays with its package."""

    entry_path: str
    source_url: str
    provenance: Provenance
    size: int
    _package: FilingDocument | FilingArchiveMember = field(repr=False, compare=False)
    _path_chain: tuple[str, ...] = field(default=(), repr=False, compare=False)
    _archive_depth: int = field(default=1, repr=False, compare=False)
    _cached_bytes: bytes | None = field(default=None, repr=False, compare=False)
    _archive_payload_cache: bytes | None = field(default=None, repr=False, compare=False)
    # A large nested package is opened from a temporary file, removed with this object.
    _archive_payload_path: Path | None = field(default=None, repr=False, compare=False)
    _members_cache: list[FilingArchiveMember] | None = field(default=None, repr=False, compare=False)
    _tables_cache: dict[str | None, tuple[FilingTable, ...]] = field(default_factory=dict, repr=False, compare=False)
    _markdown_cache: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def _check_source(self) -> None:
        if self.source_url != self.provenance.source_url or self.source_url != self._package.source_url:
            raise DownloadError("archive member source URL changed after selection")
        if self._path_chain and self.entry_path != self._path_chain[-1]:
            raise DownloadError("archive member entry path changed after selection")
        if isinstance(self._package, FilingArchiveMember):
            self._package._check_source()
        else:
            self._package._check_cached_source()

    @property
    def filename(self) -> str:
        """The member's file name inside its package."""
        self._check_source()
        return Path(self.entry_path).name

    def _head(self, size: int = 512) -> bytes:
        """The first bytes of this entry, for content sniffing without full extraction."""
        self._check_source()
        if self._cached_bytes is not None:
            return self._cached_bytes[:size]
        if isinstance(self._package, FilingArchiveMember):
            source, encoding = self._package._nested_source(), None
        else:
            source = self._package._archive_source()
            encoding = self._package.provider_metadata.get("archive_encoding")
        try:
            with zipfile.ZipFile(source, metadata_encoding=encoding) as archive:
                with archive.open(self.entry_path) as member:
                    return member.read(size)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ParseError(f"could not read ZIP member {self.entry_path}") from exc

    def _is_gzipped(self) -> bool:
        return self._head(2) == b"\x1f\x8b"

    def _markup_head(self) -> bytes:
        """The first decoded bytes; KNF gzips every attachment, markup included."""
        head = self._head(2048)
        if not head.startswith(b"\x1f\x8b"):
            return head
        try:
            return zlib.decompressobj(wbits=31).decompress(self._head(65536), 2048)
        except zlib.error:
            return b""

    @contextmanager
    def _gunzipped(self) -> Iterator[Path]:
        """This gzip-compressed member decompressed to a temporary file, bounded like a streamed parse."""
        limit = self._streamed_limit()
        with tempfile.TemporaryDirectory(prefix="ocf-gunzip-") as directory:
            packed = self.download(Path(directory) / "packed.gz", max_bytes=limit)
            target = Path(directory) / "member"
            total = 0
            try:
                with gzip.open(packed, "rb") as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > limit:
                            raise ParseError(f"gzip member {self.entry_path} exceeds the {limit} byte limit")
                        output.write(chunk)
            except OSError as exc:
                raise ParseError(f"invalid gzip member {self.entry_path}") from exc
            yield target

    def _streamed_limit(self) -> int:
        """Byte bound for a file-backed parse; refuses an implausibly compressed large member."""
        if self.size > MAX_ARCHIVE_MEMBER_BYTES:
            compressed = self.provenance.raw.get("compressed_size") or 0
            if compressed and self.size / compressed > _MAX_COMPRESSION_RATIO:
                raise ParseError(
                    f"ZIP member {self.entry_path} has an implausible compression ratio "
                    f"({self.size} bytes from {compressed})"
                )
        return MAX_STREAMED_MEMBER_BYTES

    def _nested_source(self) -> BytesIO | Path:
        """This opened nested package, for its own members to read from."""
        if self._archive_payload_path is not None:
            return self._archive_payload_path
        if self._archive_payload_cache is None:
            raise RuntimeError("parent archive has not been opened")
        return BytesIO(self._archive_payload_cache)

    def _spill_payload(self) -> Path:
        """Write a large nested package (gzip unwrapped) to a temporary file owned by this object."""
        limit = self._streamed_limit()
        fd, raw = tempfile.mkstemp(prefix="ocf-nested-", suffix=".zip")
        os.close(fd)
        path = Path(raw)
        weakref.finalize(self, _unlink_quietly, path)
        self.download(path, max_bytes=limit)
        with path.open("rb") as saved:
            wrapped = saved.read(2) == b"\x1f\x8b"
        if wrapped:
            fd, raw = tempfile.mkstemp(prefix="ocf-nested-", suffix=".zip")
            os.close(fd)
            unwrapped = Path(raw)
            weakref.finalize(self, _unlink_quietly, unwrapped)
            total = 0
            try:
                with gzip.open(path, "rb") as source, unwrapped.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > limit:
                            raise ParseError(f"gzip wrapper in {self.entry_path} exceeds the {limit} byte limit")
                        target.write(chunk)
            except OSError as exc:
                raise ParseError(f"invalid gzip wrapper in {self.entry_path}") from exc
            _unlink_quietly(path)
            path = unwrapped
        if not zipfile.is_zipfile(path):
            raise UnsupportedCapabilityError(f"{self.entry_path} is not a nested ZIP package")
        self._archive_payload_path = path
        return path

    @property
    def source_location(self) -> str:
        """Package URL plus the member's path chain, for provenance."""
        self._check_source()
        return f"{self.source_url}::{'::'.join(self._path_chain or (self.entry_path,))}"

    @property
    def members(self) -> list[FilingArchiveMember]:
        """Inspect a nested ZIP (or gzip-wrapped ZIP) without altering source bytes."""
        self._check_source()
        if self._archive_depth >= 5:
            raise UnsupportedCapabilityError("nested archive inspection is limited to five member levels")
        if self._members_cache is None:
            if self.size >= _STREAM_PARSE_MEMBER_BYTES:
                source: BytesIO | Path = self._spill_payload()
            else:
                content = self.download()
                if content.startswith(b"\x1f\x8b"):
                    try:
                        with gzip.GzipFile(fileobj=BytesIO(content)) as archive:
                            content = archive.read(MAX_ARCHIVE_MEMBER_BYTES + 1)
                    except OSError as exc:
                        raise ParseError(f"invalid gzip wrapper in {self.entry_path}") from exc
                    if len(content) > MAX_ARCHIVE_MEMBER_BYTES:
                        raise ParseError(f"gzip wrapper in {self.entry_path} exceeds the 100 MB inspection limit")
                if not zipfile.is_zipfile(BytesIO(content)):
                    raise UnsupportedCapabilityError(f"{self.entry_path} is not a nested ZIP package")
                self._archive_payload_cache = content
                source = BytesIO(content)
            try:
                with zipfile.ZipFile(source) as archive:
                    seen: set[str] = set()
                    members = []
                    for info in archive.infolist():
                        if info.is_dir():
                            continue
                        if info.filename in seen:
                            raise ParseError(f"nested ZIP {self.entry_path} has duplicate entry {info.filename}")
                        seen.add(info.filename)
                        chain = (*self._path_chain, info.filename)
                        raw = {"parent_source_id": self.provenance.source_id,
                               "entry_path": info.filename, "path_chain": chain,
                               "size": info.file_size, "compressed_size": info.compress_size,
                               "crc": info.CRC}
                        members.append(FilingArchiveMember(
                            entry_path=info.filename, source_url=self.source_url,
                            provenance=Provenance(self.provenance.provider, self.provenance.regulator,
                                                  self.provenance.jurisdiction, self.source_url,
                                                  f"{self.provenance.source_id}::{info.filename}",
                                                  datetime.now(timezone.utc), raw),
                            size=info.file_size, _package=self, _path_chain=chain,
                            _archive_depth=self._archive_depth + 1,
                        ))
                    self._members_cache = members
            except zipfile.BadZipFile as exc:
                raise ParseError(f"invalid nested ZIP in {self.entry_path}") from exc
        return list(self._members_cache)

    def download(
        self, path: str | Path | None = None, *, max_bytes: int | None = MAX_ARCHIVE_MEMBER_BYTES,
    ) -> bytes | Path:
        """Extract one entry, limited to 100 MB by default; override explicitly."""
        self._check_source()
        if max_bytes is not None and max_bytes <= 0:
            raise ValueError("max_bytes must be positive or None")
        if max_bytes is not None and self.size > max_bytes:
            raise ParseError(f"ZIP member {self.entry_path} exceeds the {max_bytes} byte extraction limit")
        content = self._cached_bytes
        if content is not None and max_bytes is not None and len(content) > max_bytes:
            raise ParseError(f"ZIP member {self.entry_path} exceeds the {max_bytes} byte extraction limit")
        target = Path(path) if path is not None else None
        temporary: str | None = None
        try:
            if content is None:
                if isinstance(self._package, FilingArchiveMember):
                    package_source = self._package._nested_source()
                    encoding = None
                else:
                    package_source = self._package._archive_source()
                    encoding = self._package.provider_metadata.get("archive_encoding")
                with zipfile.ZipFile(package_source, metadata_encoding=encoding) as archive:
                    with archive.open(self.entry_path) as member:
                        if target is None:
                            content = member.read(max_bytes + 1 if max_bytes is not None else -1)
                            if max_bytes is not None and len(content) > max_bytes:
                                raise ParseError(f"ZIP member {self.entry_path} exceeds the {max_bytes} byte extraction limit")
                            self._cached_bytes = content
                        else:
                            fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
                            with os.fdopen(fd, "wb") as output:
                                total = 0
                                while chunk := member.read(1024 * 1024):
                                    total += len(chunk)
                                    if max_bytes is not None and total > max_bytes:
                                        raise ParseError(f"ZIP member {self.entry_path} exceeds the {max_bytes} byte extraction limit")
                                    output.write(chunk)
            elif target is not None:
                fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
                with os.fdopen(fd, "wb") as output:
                    output.write(content)
            if target is None:
                return content
            os.replace(temporary, target)
            return target
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ParseError(f"could not read ZIP member {self.entry_path}") from exc
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def text(self, *, encoding: str | None = None) -> str:
        """Read visible HTML/XHTML text without retaining a large member buffer."""
        self._check_source()
        if Path(self.entry_path).suffix.lower() not in {".htm", ".html", ".xhtml"}:
            raise UnsupportedCapabilityError(f"HTML/XHTML text is unavailable for {self.entry_path}")
        if not _looks_like_markup(self._markup_head()):
            raise UnsupportedCapabilityError(
                f"{self.entry_path} is not HTML/XHTML text; its bytes are compressed or binary"
            )
        from .html_text import html_to_text

        if self._is_gzipped():
            with self._gunzipped() as decoded:
                return html_to_text(decoded, encoding=encoding)

        if self.size >= _STREAM_PARSE_MEMBER_BYTES and self._cached_bytes is None:
            with tempfile.TemporaryDirectory(prefix="ocf-member-text-") as directory:
                saved = self.download(Path(directory) / "report.xhtml", max_bytes=self._streamed_limit())
                return html_to_text(saved, encoding=encoding)
        return html_to_text(self.download(), encoding=encoding)

    @contextmanager
    def _parse_content(self, *, max_bytes: int | None = None) -> Iterator[bytes | Path]:
        """Expose one large member as a temporary file for bounded parsers."""
        self._check_source()
        if self._is_gzipped():
            with self._gunzipped() as decoded:
                yield decoded
            return
        if self.size >= _STREAM_PARSE_MEMBER_BYTES and self._cached_bytes is None:
            with tempfile.TemporaryDirectory(prefix="ocf-member-parse-") as directory:
                yield self.download(Path(directory) / "report", max_bytes=max_bytes or self._streamed_limit())
            return
        yield self.download(max_bytes=max_bytes or MAX_ARCHIVE_MEMBER_BYTES)

    def html(self, *, encoding: str | None = None) -> str:
        """Decode one selected HTML/XHTML entry inside its original package."""
        if Path(self.entry_path).suffix.lower() not in {".htm", ".html", ".xhtml"}:
            raise UnsupportedCapabilityError(f"HTML/XHTML is unavailable for {self.entry_path}")
        from .html_text import read_html

        with self._parse_content() as content:
            return read_html(content, encoding)

    def markdown(self, *, encoding: str | None = None) -> str:
        """Render one selected HTML/XHTML ZIP member as Markdown."""
        self._check_source()
        if Path(self.entry_path).suffix.lower() not in {".htm", ".html", ".xhtml"}:
            raise UnsupportedCapabilityError(f"HTML/XHTML Markdown is unavailable for {self.entry_path}")
        if encoding not in self._markdown_cache:
            from .markdown_text import html_to_markdown

            with self._parse_content() as content:
                self._markdown_cache[encoding] = html_to_markdown(content, encoding=encoding)
        return self._markdown_cache[encoding]

    def tables(self, *, encoding: str | None = None) -> list[FilingTable]:
        """Inspect literal table tags in one selected HTML/XHTML ZIP member."""
        self._check_source()
        if Path(self.entry_path).suffix.lower() not in {".htm", ".html", ".xhtml"}:
            raise UnsupportedCapabilityError(f"HTML/XHTML tables are unavailable for {self.entry_path}")
        if encoding not in self._tables_cache:
            from .html_tables import extract_html_tables

            with self._parse_content() as content:
                self._tables_cache[encoding] = extract_html_tables(
                    content, provenance=self.provenance,
                    source_location=self.source_location, encoding=encoding,
                )
        return list(self._tables_cache[encoding])


@dataclass(slots=True)
class Filing:
    filing_id: str
    entity_id: str
    jurisdiction: str
    provider: str
    regulator: str
    source_url: str
    provenance: Provenance
    filing_type_raw: str | None = None
    filing_type_normalized: str | None = None
    title: str | None = None
    filing_date: date | None = None
    published_at: datetime | None = None
    index_added_at: datetime | None = None
    period_start: date | None = None
    period_end: date | None = None
    amendment: bool | None = None
    language: str | None = None
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)
    _documents: list[FilingDocument] | None = field(default=None, repr=False, compare=False)
    _primary_document: FilingDocument | None = field(default=None, repr=False, compare=False)
    _facts_cache: tuple[FilingFact, ...] | None = field(default=None, repr=False, compare=False)
    _sections_cache: tuple[FilingSection, ...] | None = field(default=None, repr=False, compare=False)
    _provider: FilingProvider | None = field(default=None, repr=False, compare=False)
    _source_at_selection: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.filing_type_normalized is not None and self.filing_type_normalized not in FILING_CATEGORIES:
            raise ValueError(f"filing_type_normalized must be one of {sorted(FILING_CATEGORIES)} or None")
        self._source_at_selection = self.source_url

    def _check_content_sources(self) -> None:
        if self.source_url != self._source_at_selection:
            raise DownloadError("filing source URL changed after selection")
        if self._primary_document is not None:
            self._primary_document._check_cached_source()
        if self._documents is not None:
            for document in self._documents:
                document._check_cached_source()

    def _bind_document(self, document: FilingDocument) -> FilingDocument:
        if (document.filing_id != self.filing_id
                or document.provenance.provider != self.provider
                or document.provenance.jurisdiction != self.jurisdiction
                or document.provenance.source_url != document.source_url):
            raise ProviderError(
                f"document {document.document_id!r} does not belong to this filing's source"
            )
        document._provider = self._provider
        return document

    @property
    def documents(self) -> list[FilingDocument]:
        """Every original source document listed for this filing, verified and bound."""
        if self._documents is None:
            if self._provider is None:
                raise RuntimeError("filing is not bound to a provider")
            documents = self._provider.list_documents(self)
            for document in documents:
                self._bind_document(document)
            self._documents = documents
            if self._primary_document is not None:
                for index, document in enumerate(self._documents):
                    if (document.document_id == self._primary_document.document_id
                            and document.source_url == self._primary_document.source_url):
                        primary = self._primary_document
                        primary.provenance = document.provenance
                        primary.media_type = document.media_type
                        primary.document_type = document.document_type
                        primary.language = document.language
                        primary.is_primary = document.is_primary
                        primary.provider_metadata = document.provider_metadata
                        primary.description = document.description
                        primary.role = document.role
                        self._documents[index] = primary
                        break
                else:
                    self._primary_document = None
        for document in self._documents:
            self._bind_document(document)
        return list(self._documents)

    @property
    def primary_document(self) -> FilingDocument:
        """The filing's main document: one source-flagged file, else the report role, then format."""
        if self._primary_document is not None:
            return self._bind_document(self._primary_document)
        if self._documents is None and self._provider is not None:
            primary = self._provider.get_primary_document(self)
            if primary is not None:
                self._primary_document = self._bind_document(primary)
                return self._primary_document
        documents = self.documents
        if not documents:
            raise UnsupportedCapabilityError(f"filing {self.filing_id} has no source documents")
        self._primary_document = _choose_primary(documents)
        return self._primary_document

    def select_document(
        self, *, document_id: str | None = None, document_type: str | None = None,
        filename: str | None = None, media_type: str | None = None,
        language: str | None = None, description: str | None = None,
    ) -> FilingDocument:
        """Select one existing representation by exact source metadata."""
        if document_id is document_type is filename is media_type is language is description is None:
            return self.primary_document
        matches = [document for document in self.documents
                   if (document_id is None or document.document_id == document_id)
                   and (document_type is None or document.document_type == document_type)
                   and (filename is None or document.filename == filename)
                   and (media_type is None or document.media_type == media_type)
                   and (language is None or document.language == language)
                   and (description is None or document.description == description)]
        if not matches:
            raise UnsupportedCapabilityError(f"filing {self.filing_id} has no document matching the selection")
        if len(matches) > 1:
            raise ValueError(f"filing {self.filing_id} has {len(matches)} matching documents; refine the selection")
        return matches[0]

    @property
    def facts(self) -> list[FilingFact]:
        """Raw structured fact occurrences from this filing's original, parsed once."""
        return list(self._fact_occurrences())

    def _fact_occurrences(self) -> tuple[FilingFact, ...]:
        if self._provider is None:
            raise RuntimeError("filing is not bound to a provider")
        self._check_content_sources()
        if self._facts_cache is None:
            facts = tuple(self._provider.raw_facts(self))
            for fact in facts:
                if (fact.provenance.provider != self.provider
                        or fact.provenance.jurisdiction != self.jurisdiction):
                    raise ProviderError(
                        f"raw fact {fact.concept_raw!r} does not match this filing's source"
                    )
            self._facts_cache = facts
        self._check_content_sources()
        return self._facts_cache

    def find_facts(
        self, *, concept_raw: str | None = None, period_start: date | None = None,
        period_end: date | None = None, unit: str | None = None,
        context_id: str | None = None, taxonomy: str | None = None,
        dimensions: Mapping[str, str] | None = None, limit: int | None = None,
    ) -> list[FilingFact]:
        """Filter occurrences by exact raw fields; no concept normalization."""
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        matches = []
        for fact in self._fact_occurrences():
            if (
                (concept_raw is not None and fact.concept_raw != concept_raw)
                or (period_start is not None and fact.period_start != period_start)
                or (period_end is not None and fact.period_end != period_end)
                or (unit is not None and fact.unit != unit)
                or (context_id is not None and fact.context_id != context_id)
                or (taxonomy is not None and fact.taxonomy != taxonomy)
                or (dimensions is not None and not all(
                        fact.dimensions.get(key) == value for key, value in dimensions.items()
                    ))
            ):
                continue
            matches.append(fact)
            if limit is not None and len(matches) >= limit:
                break
        return matches

    @property
    def raw(self) -> Mapping[str, Any]:
        """The source's own record for this filing, unchanged."""
        return self.provider_metadata

    @property
    def metadata(self) -> dict[str, Any]:
        """Source metadata as a dict, dates as `date` objects; see `to_dict()` for JSON."""
        return {
            "filing_id": self.filing_id,
            "entity_id": self.entity_id,
            "jurisdiction": self.jurisdiction,
            "provider": self.provider,
            "regulator": self.regulator,
            "filing_type_raw": self.filing_type_raw,
            "filing_type_normalized": self.filing_type_normalized,
            "title": self.title,
            "filing_date": self.filing_date,
            "published_at": self.published_at,
            "index_added_at": self.index_added_at,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "amendment": self.amendment,
            "language": self.language,
            "source_url": self.source_url,
            "provider_metadata": self.provider_metadata,
        }

    def __repr__(self) -> str:
        parts = [self.filing_id, self.filing_type_raw or "", self.filing_type_normalized or "",
                 f"period={self.period_end}" if self.period_end else "",
                 f"filed={self.filing_date}" if self.filing_date else "", f"{self.jurisdiction}/{self.provider}"]
        return "<Filing " + " ".join(part for part in parts if part) + ">"

    def _repr_html_(self) -> str:
        period = f"{self.period_start or ''} to {self.period_end}" if self.period_end else None
        return _html_table(f"Filing {self.filing_id}", [
            ("type", self.filing_type_raw), ("category", self.filing_type_normalized),
            ("title", self.title), ("filing_date", self.filing_date), ("published_at", self.published_at),
            ("period", period), ("amendment", self.amendment),
            ("market", self.jurisdiction), ("regulator", self.regulator), ("provider", self.provider),
        ], self.source_url)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe filing metadata with its source pointers; source values are not reinterpreted."""
        record = _json_safe(self.metadata)
        record["provenance_source_url"] = self.provenance.source_url
        record["provenance_source_id"] = self.provenance.source_id
        return record

    def facts_to_pandas(self):
        """Raw facts as a DataFrame, one row per occurrence; requires the optional pandas extra."""
        pandas = _pandas()
        return pandas.DataFrame([fact.to_dict() for fact in self.facts], columns=_FACT_COLUMNS, dtype=object)

    def text(self) -> str:
        """Extracted text of the primary document where its format supports it."""
        return self.primary_document.text()

    def html(self, *, encoding: str | None = None) -> str:
        """The primary document's original HTML/XHTML as text."""
        return self.primary_document.html(encoding=encoding)

    def markdown(self, *, encoding: str | None = None) -> str:
        """The primary document rendered as Markdown (optional `markdown` extra)."""
        return self.primary_document.markdown(encoding=encoding)

    def tables(self, *, encoding: str | None = None) -> list[FilingTable]:
        """Literal HTML/XHTML tables of the primary document, cells as filed."""
        return self.primary_document.tables(encoding=encoding)

    def sections(self) -> list[FilingSection]:
        """Return verified source sections when the provider supports this filing."""
        if self._provider is None:
            raise RuntimeError("filing is not bound to a provider")
        self._check_content_sources()
        if self._sections_cache is None:
            self._sections_cache = tuple(self._provider.extract_sections(self))
        self._check_content_sources()
        return list(self._sections_cache)

    def section(self, item: str, *, part: str | None = None) -> FilingSection:
        """Select one verified Item span; 10-Q Item numbers may need a Part."""
        match = re.fullmatch(r"(?:Item\s+)?(\d{1,2}[A-C]?|[1-9]\.\d{2})\.?", item.strip(), re.IGNORECASE)
        if match is None:
            raise ValueError("Item must be a number such as '8', 'Item 1A' or '2.02'")
        code = match.group(1).upper()
        if part is not None:
            part_match = re.fullmatch(r"(?:Part\s+)?(I|II)", part.strip(), re.IGNORECASE)
            if part_match is None:
                raise ValueError("part must be 'I' or 'II'")
            part = part_match.group(1).upper()
        matches = [section for section in self.sections()
                   if code in section.items and (part is None or section.part == part)]
        if not matches:
            suffix = f" in Part {part}" if part else ""
            raise KeyError(f"Item {code}{suffix} is unavailable in filing {self.filing_id}")
        if len(matches) > 1:
            raise ValueError(f"Item {code} appears in multiple Parts; specify part='I' or part='II'")
        return matches[0]

    def section_references(self, item: str) -> tuple[FilingSectionReference, ...]:
        """Return as-filed SEC 10-K Item pointers without claiming referenced content."""
        match = re.fullmatch(r"(?:Item\s+)?(\d{1,2}[A-C]?)\.?", item.strip(), re.IGNORECASE)
        if match is None:
            raise ValueError("Item must be a number such as '8' or 'Item 1A'")
        if self.provider == "sec" and self.filing_type_raw == "10-K/A":
            raise UnsupportedCapabilityError(
                "SEC 10-K/A amendments may contain only changed Items; "
                "to navigate the original filing, use company.filings(form='annual', include_amendments=False).latest()"
            )
        if self.provider != "sec" or self.filing_type_raw != "10-K":
            raise UnsupportedCapabilityError("Item references require an SEC 10-K")
        self._check_content_sources()
        from .sec_sections import sec_10k_index_references

        try:
            return sec_10k_index_references(self.primary_document, match.group(1).upper())
        except UnsupportedCapabilityError as exc:
            if str(exc) != "SEC 10-K has no verified cross-reference index":
                raise
            return self.section(match.group(1).upper()).references

    def download(self, path: str | Path | None = None) -> bytes | Path:
        """The primary document's original bytes, or the saved path when `path` is given."""
        return self.primary_document.download(path)


def _bind_filing(filing: Filing, provider: FilingProvider, entity: Entity) -> Filing:
    """Reject source rows that escaped an issuer-scoped provider query."""
    if (filing.entity_id != entity.entity_id or filing.jurisdiction != entity.jurisdiction
            or filing.provider != provider.name):
        raise ProviderError(
            f"filing {filing.filing_id!r} does not match the selected entity and provider"
        )
    if (filing.provenance.provider != provider.name
            or filing.provenance.jurisdiction != filing.jurisdiction):
        raise ProviderError(f"filing {filing.filing_id!r} has inconsistent source provenance")
    filing._provider = provider
    return filing


class FilingCollection:
    def __init__(
        self,
        provider: FilingProvider,
        entity: Entity,
        *,
        form: str | None = None,
        start: date | None = None,
        end: date | None = None,
        include_amendments: bool = True,
        limit: int | None = None,
    ) -> None:
        self.provider = provider
        self.entity = entity
        self.form = form
        self.start = start
        self.end = end
        self.include_amendments = include_amendments
        self.limit = limit
        self.order_basis = provider.order_basis

    def _filters(self) -> list[tuple[str, Any]]:
        return [("form", self.form), ("start", self.start), ("end", self.end), ("limit", self.limit),
                ("include_amendments", None if self.include_amendments else False)]

    def __repr__(self) -> str:
        """Filters only: printing a collection never lists filings from the source."""
        filters = " ".join(f"{key}={value}" for key, value in self._filters() if value is not None)
        parts = [self.entity.name, f"{self.entity.jurisdiction}/{self.provider.name}", filters,
                 f"order={self.order_basis}"]
        return "<FilingCollection " + " ".join(part for part in parts if part) + ">"

    def _repr_html_(self) -> str:
        return _html_table(f"Filings for {self.entity.name}", [
            ("market", self.entity.jurisdiction), ("provider", self.provider.name),
            *self._filters(), ("order", self.order_basis),
        ], None)

    def to_pandas(self, n: int):
        """The first `n` filings as a DataFrame; requires the optional pandas extra.

        `n` is required because a source's history can be long and paged.
        """
        pandas = _pandas()
        frame = pandas.DataFrame([filing.to_dict() for filing in self.head(n)])
        frame.attrs["order_basis"] = self.order_basis
        return frame

    def download(
        self, directory: str | Path, *, documents: str | tuple[str, ...] = "primary",
        file_types: tuple[str, ...] | None = None, all_history: bool = False,
    ) -> dict[str, Any]:
        """Save this company's selected filings into `directory` with a resumable manifest.

        One company only, and bounded: the collection needs `limit=`, a
        `start`/`end` window, or `all_history=True`. `documents` is "primary"
        (default), "all", or a tuple of document roles such as ("report", "exhibit").
        `file_types` keeps documents whose filename has one of these extensions,
        such as (".pdf",) or (".xml", ".xsd"); with it, "primary" widens to every
        document, since the primary file may not be of that type. A rerun skips files whose SHA-256 matches the manifest; a failed filing is
        recorded and the rest continue.
        """
        if not (documents in ("primary", "all") or (
                isinstance(documents, tuple) and documents and set(documents) <= set(DOCUMENT_ROLES))):
            raise ValueError(f"documents must be 'primary', 'all' or a tuple of roles from {DOCUMENT_ROLES}")
        if self.limit is None and self.start is None and self.end is None and not all_history:
            raise ValueError("bound the download with filings(limit=...) or start=/end=, or pass all_history=True")
        suffixes = {f".{kind.lower().lstrip('.')}" for kind in file_types or ()}
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "manifest.json"
        entries: dict[str, dict[str, Any]] = {}
        if manifest_path.exists():
            for entry in json.loads(manifest_path.read_text(encoding="utf-8")).get("filings", []):
                entries[entry["filing"]["filing_id"]] = entry
        recorded = {document["path"]: document.get("sha256")
                    for entry in entries.values() for document in entry.get("documents", [])}
        counts = {"downloaded": 0, "skipped": 0, "failed": 0}
        processed = 0
        header = {"entity_id": self.entity.entity_id, "entity_name": self.entity.name,
                  "market": self.entity.jurisdiction, "provider": self.provider.name,
                  "order_basis": self.order_basis, "form": self.form}
        for filing in self:
            processed += 1
            folder = _safe_filename(filing.filing_id)
            entry: dict[str, Any] = {"filing": filing.to_dict(), "status": "ok", "documents": []}
            try:
                if documents == "primary" and not suffixes:
                    selected = [filing.primary_document]
                else:
                    selected = [document for document in filing.documents
                                if (documents in ("primary", "all") or document.role in documents)
                                and (not suffixes or Path(document.filename).suffix.lower() in suffixes)]
                used: set[str] = set()
                for document in selected:
                    name = _safe_filename(document.filename)
                    stem, suffix = os.path.splitext(name)
                    counter = 1
                    while name.casefold() in used:  # Windows and macOS file names ignore case
                        counter += 1
                        name = f"{stem}-{counter}{suffix}"
                    used.add(name.casefold())
                    relative = f"{folder}/{name}"
                    target = root / folder / name
                    record = {**document.to_dict(), "path": relative}
                    if target.exists() and recorded.get(relative) == _file_sha256(target):
                        record.update(status="skipped", sha256=recorded[relative], bytes=target.stat().st_size)
                        counts["skipped"] += 1
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        document.download(target)
                        record.update(status="downloaded", sha256=_file_sha256(target), bytes=target.stat().st_size)
                        counts["downloaded"] += 1
                    entry["documents"].append(record)
            except OpenCorpFilingsError as exc:
                entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                counts["failed"] += 1
            entries[filing.filing_id] = entry
            _write_manifest(manifest_path, header, entries)
        _write_manifest(manifest_path, header, entries)
        return {"manifest": str(manifest_path), "filings": processed, **counts}

    def _filter_mismatch(self, filing: Filing) -> str | None:
        if self.form is not None:
            if filing.filing_type_normalized is None and filing.filing_type_raw is None:
                raise UnsupportedCapabilityError(
                    f"{self.provider.name} returned a filing without a filing type"
                )
            if not self.provider.filing_matches_form(filing, self.form):
                return "form"
        if self.start is not None or self.end is not None:
            filter_date = self.provider.filing_date_for_filter(filing)
            if filter_date is None:
                raise UnsupportedCapabilityError(
                    f"{self.provider.name} returned a filing without a source filing date for filtering"
                )
            if ((self.start is not None and filter_date < self.start)
                    or (self.end is not None and filter_date > self.end)):
                return "date range"
        if not self.include_amendments and filing.amendment is True:
            return "amendment filter"
        return None

    def __iter__(self) -> Iterator[Filing]:
        source = self.provider.iter_filings(
            self.entity,
            form=self.form,
            start=self.start,
            end=self.end,
            include_amendments=self.include_amendments,
            limit=self.limit,
        )
        for filing in islice(source, self.limit):
            _bind_filing(filing, self.provider, self.entity)
            if mismatch := self._filter_mismatch(filing):
                raise ProviderError(f"{self.provider.name} returned a filing outside the requested {mismatch}")
            yield filing

    def __getitem__(self, index: int | slice) -> Filing | list[Filing]:
        """`filings[0]` or `filings[:5]`, reading only as far as the position asked for."""
        if isinstance(index, slice):
            if self.limit is not None:
                return list(self)[index]
            start, stop, step = index.start or 0, index.stop, index.step
            if stop is None or start < 0 or stop < 0 or (step is not None and step < 0):
                raise IndexError("an unbounded collection takes slices like [:5] or [2:5]; "
                                 "set limit= or use .latest(n) for the newest n")
            return self.head(stop)[index] if stop > 0 else []
        if not isinstance(index, int):
            raise TypeError(f"filing positions are integers, not {type(index).__name__}")
        if index < 0:
            if self.limit is None:
                raise IndexError("negative positions need a bounded collection; "
                                 "set limit= or use .latest(n) for the newest n")
            return list(self)[index]
        filings = self.head(index + 1)
        if index >= len(filings):
            raise IndexError(f"there are only {len(filings)} {self.form or 'matching'} filings")
        return filings[index]

    def head(self, n: int) -> list[Filing]:
        """The first `n` filings in source order, read with a bounded listing."""
        if n <= 0:
            raise ValueError("n must be positive")
        bounded = FilingCollection(
            self.provider, self.entity, form=self.form, start=self.start, end=self.end,
            include_amendments=self.include_amendments,
            limit=min(n, self.limit) if self.limit is not None else n,
        )
        return list(islice(bounded, n))

    def get(self, filing_id: str, *, max_scan: int = 500) -> Filing:
        """Find an exact source ID, scanning only for bounded or non-direct sources."""
        if not filing_id:
            raise ValueError("filing_id must not be empty")
        if max_scan <= 0:
            raise ValueError("max_scan must be positive")
        if self.limit is None and self.provider.supports("direct_filing_lookup"):
            filing = self.provider.get_filing(self.entity, filing_id)
            if filing.filing_id != filing_id or filing.entity_id != self.entity.entity_id:
                raise FilingNotFoundError(f"filing {filing_id!r} does not belong to {self.entity.name}")
            _bind_filing(filing, self.provider, self.entity)
            if self._filter_mismatch(filing):
                raise FilingNotFoundError(f"filing {filing_id!r} is outside the selected filters")
            return filing
        scan_limit = min(max_scan, self.limit) if self.limit is not None else max_scan
        bounded = FilingCollection(
            self.provider, self.entity, form=self.form, start=self.start, end=self.end,
            include_amendments=self.include_amendments, limit=scan_limit,
        )
        for filing in islice(bounded, scan_limit):
            if filing.filing_id == filing_id:
                return filing
        raise FilingNotFoundError(
            f"filing {filing_id!r} was not found among the first {scan_limit} "
            f"{self.form or 'matching'} records for {self.entity.name}"
        )

    def latest(self, n: int | None = None) -> Filing | list[Filing]:
        """The newest filing in `order_basis`, or the newest `n` as a list."""
        if n is not None:
            return self.head(n)
        filing = next(iter(self.head(1)), None)
        if filing is None:
            raise FilingNotFoundError(
                f"no {self.form or 'matching'} filings for {self.entity.name}"
            )
        return filing


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(name: str) -> str:
    """A source ID or filename as one portable path segment (France IDs contain ':')."""
    cleaned = _UNSAFE_FILENAME.sub("_", name).strip(" .")
    return cleaned or "file"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path: Path, header: dict[str, Any], entries: dict[str, dict[str, Any]]) -> None:
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps({**header, "filings": list(entries.values())}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    os.replace(temporary, path)
