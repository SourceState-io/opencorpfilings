"""Bounded, optional text extraction from original PDF pages."""

from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from .errors import ParseError, UnsupportedCapabilityError


MAX_PDF_BYTES = 50_000_000
MAX_PDF_PAGES = 2_000
MAX_PAGE_CONTENT_BYTES = 10_000_000


@contextmanager
def _reader(content: bytes | Path):
    if isinstance(content, Path):
        if content.stat().st_size > MAX_PDF_BYTES:
            raise ParseError("PDF exceeds the 50 MB text extraction size limit; original bytes remain available")
        source = content.open("rb")
    else:
        if len(content) > MAX_PDF_BYTES:
            raise ParseError("PDF exceeds the 50 MB text extraction size limit; original bytes remain available")
        source = BytesIO(content)
    with source:
        if b"%PDF-" not in source.read(1024):
            raise ParseError("source document is not a PDF; original bytes remain available")
        source.seek(0)
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise UnsupportedCapabilityError(
                "PDF text requires the optional 'pdf' extra (the pypdf package)"
            ) from exc
        reader = PdfReader(source)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError("PDF text requires a password for this encrypted source")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ParseError("PDF exceeds the 2,000-page text extraction limit")
        yield reader


def _page_text(page, number: int) -> str:
    stream = page.get_contents()
    if stream is not None and len(stream.get_data()) > MAX_PAGE_CONTENT_BYTES:
        raise ParseError(f"PDF page {number} exceeds the page content limit")
    return page.extract_text() or ""


def extract_pdf_pages(content: bytes | Path) -> tuple[str, ...]:
    """Return visible text per original page; no OCR or table interpretation."""
    try:
        with _reader(content) as reader:
            pages = []
            for number, page in enumerate(reader.pages, start=1):
                pages.append(_page_text(page, number))
            return tuple(pages)
    except (ParseError, UnsupportedCapabilityError):
        raise
    except MemoryError:
        raise
    except Exception as exc:
        raise ParseError(f"could not read PDF pages: {exc}") from exc


def extract_pdf_page(content: bytes | Path, number: int) -> str:
    """Read one numbered PDF page without extracting the others."""
    if number < 1:
        raise ValueError("PDF page number must be positive")
    try:
        with _reader(content) as reader:
            if number > len(reader.pages):
                raise IndexError(f"PDF page {number} is out of range (1-{len(reader.pages)})")
            return _page_text(reader.pages[number - 1], number)
    except (ParseError, UnsupportedCapabilityError, IndexError):
        raise
    except MemoryError:
        raise
    except Exception as exc:
        raise ParseError(f"could not read PDF page {number}: {exc}") from exc
