"""Helpers the national OAM adapters share where their behaviour is identical."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from ..errors import DownloadError, ProviderError
from ..models import _BINARY_PREFIXES
from ..transport import HttpTransport

LEI = re.compile(r"[A-Z0-9]{20}")
# ESEF packages are ZIPs, whether named .zip or .xbri.
_MEDIA_TYPES = {
    ".zip": "application/zip", ".xbri": "application/zip", ".pdf": "application/pdf",
    ".xhtml": "application/xhtml+xml", ".html": "text/html", ".htm": "text/html",
    ".xml": "application/xml", ".txt": "text/plain",
}


def media_type(name: str) -> str | None:
    """Media type of a filename or URL, from its extension."""
    return _MEDIA_TYPES.get(PurePosixPath(urlparse(name).path).suffix.lower())


def require_https_host(url: str, host: str, message: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != host:
        raise DownloadError(message)


def download(transport: HttpTransport, url: str, *, label: str) -> bytes:
    """Uncached original bytes of a checked URL; FilingDocument.download verifies PDF/ZIP format."""
    try:
        return transport.get(url, cache=False)
    except ProviderError as exc:
        raise DownloadError(f"{label} failed: {exc}") from exc


def save(transport: HttpTransport, url: str, path: Path, media_type: str | None, *, label: str) -> Path:
    """Stream a checked URL to `path`, refusing a PDF or ZIP whose first bytes are wrong."""
    try:
        return transport.get_to_file(url, path, expected_prefix=_BINARY_PREFIXES.get(media_type))
    except ProviderError as exc:
        raise DownloadError(f"{label} failed: {exc}") from exc
