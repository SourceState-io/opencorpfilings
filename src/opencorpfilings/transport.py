"""Polite, bounded HTTP for individual source requests."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import tempfile
import threading
import time
import zipfile
from collections import OrderedDict
from contextlib import nullcontext
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, ContextManager
from urllib.parse import urlsplit

import httpx

from ._version import __version__
from .errors import AuthenticationError, ProviderError, RateLimitError, SourceUnavailableError


_CACHE_MAGIC = b"SSF2"
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key"})
_CREDENTIAL_PARAMS = frozenset({
    "api_key", "api-key", "apikey", "access_token", "token", "key",
    "subscription-key", "crtfc_key",
})


class _Pacer:
    """Minimum spacing between requests; shared by every transport with one pace key."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_at = 0.0


_SHARED_PACERS: dict[str, _Pacer] = {}
_SHARED_PACERS_LOCK = threading.Lock()


def _retryable_error(status: int) -> type[ProviderError]:
    return RateLimitError if status == 429 else SourceUnavailableError


def _safe_origin(url: str) -> str:
    """Keep the source host in public errors without exposing credentials or signed paths."""
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.hostname:
        return "<source>"
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        port = ""
    return f"{parsed.scheme}://{host}{port}"


class HttpTransport:
    def __init__(
        self,
        *,
        user_agent: str = f"OpenCorpFilings/{__version__}",
        timeout: float = 20.0,
        min_interval: float = 0.0,
        max_retries: int = 2,
        cache_dir: str | Path | None = None,
        cache_ttl_seconds: float = 300.0,
        max_cache_entries: int = 128,
        client: httpx.Client | None = None,
        pace_key: str | None = None,
    ) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must not be negative")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be positive")
        if max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be positive")
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_retries = max_retries
        # A source's fair-access limit is per client, not per object: transports
        # created by separate Company objects share pacing, under `pace_key` or else per source host.
        self.pace_key = pace_key
        self._pacer: _Pacer | None = None
        if pace_key is not None:
            with _SHARED_PACERS_LOCK:
                self._pacer = _SHARED_PACERS.setdefault(pace_key, _Pacer())
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_entries = max_cache_entries
        self.cache_dir: Path | None = None
        self._cache_lock = threading.Lock()
        self._cache: OrderedDict[
            tuple[str, tuple[tuple[str, str], ...]], tuple[bytes, float]
        ] = OrderedDict()
        if cache_dir is not None:
            self.configure_cache(cache_dir)
        elif environment_cache_dir := os.getenv("OPENCORPFILINGS_CACHE_DIR"):
            self.configure_cache(environment_cache_dir)
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._owns_client = client is None

    def configure_cache(self, cache_dir: str | Path) -> None:
        """Enable bounded local GET reuse without changing source pacing."""
        if not str(cache_dir).strip():
            raise ValueError("cache_dir must not be empty")
        target = Path(cache_dir).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        with self._cache_lock:
            self.cache_dir = target
            self._cache.clear()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> HttpTransport:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _pacer_for(self, url: str) -> _Pacer:
        if self._pacer is not None:
            return self._pacer
        with _SHARED_PACERS_LOCK:
            return _SHARED_PACERS.setdefault(f"host:{urlsplit(url).hostname or ''}", _Pacer())

    def _pace(self, url: str) -> None:
        pacer = self._pacer_for(url)
        with pacer.lock:
            delay = pacer.next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            pacer.next_at = time.monotonic() + self.min_interval

    def _request(
        self, url: str, send: Callable[[], ContextManager[httpx.Response]],
        consume: Callable[[httpx.Response], Any], *, accept: Callable[[int], bool] = lambda status: status == 200,
    ) -> Any:
        """Paced attempts at one request: access refusals fail at once, retryable statuses and network errors
        are retried (`Retry-After` honoured up to 60s), and an accepted response is handed to `consume`."""
        safe_url = _safe_origin(url)
        for attempt in range(self.max_retries + 1):
            self._pace(url)
            try:
                with send() as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise AuthenticationError(f"source rejected access to {safe_url} (HTTP {status})")
                    if status in _RETRYABLE_STATUSES:
                        error = _retryable_error(status)
                        if attempt == self.max_retries:
                            raise error(f"source returned HTTP {status} for {safe_url}")
                        wait = self._retry_delay(response, attempt)
                        if wait > 60:
                            raise error(f"source returned HTTP {status} for {safe_url}; retry after {wait:.0f}s")
                    elif not accept(status):
                        raise ProviderError(f"source returned HTTP {status} for {safe_url}")
                    else:
                        return consume(response)
            except httpx.RequestError as exc:
                if attempt == self.max_retries:
                    raise ProviderError(f"request failed for {safe_url} ({type(exc).__name__})") from exc
                time.sleep(min(2**attempt, 8))
                continue
            time.sleep(wait)
        raise AssertionError("unreachable retry state")

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        cache: bool = True,
        cache_credentials_in_memory: bool = False,
        max_bytes: int | None = None,
    ) -> bytes:
        if max_bytes is not None and max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if max_bytes is not None:
            # Attachment envelopes can contain multiple base64 files. Read them
            # incrementally so a source response cannot grow without bound.
            return self._get_limited(url, params=params, headers=headers, max_bytes=max_bytes)
        request_headers = {"User-Agent": self.user_agent, **(headers or {})}
        request = self.client.build_request("GET", url, params=params, headers=request_headers)
        key = (str(request.url), tuple(sorted(request.headers.items())))
        keyed_request = any(name.lower() in _CREDENTIAL_PARAMS for name in request.url.params)
        if (self.client.auth is not None or self.client.cookies
                or any(name.lower() in _CREDENTIAL_HEADERS for name in request.headers)):
            # Client auth, headers and cookies may change outside this request key.
            cache = False
        elif keyed_request:
            cache = cache and cache_credentials_in_memory
            # Retain only a digest of a request containing a query credential.
            key = (hashlib.sha256(json.dumps(key, ensure_ascii=True).encode("ascii")).hexdigest(), ())
        if cache:
            with self._cache_lock:
                cached_entry = self._cache.get(key)
                if cached_entry is not None:
                    content, expires_at = cached_entry
                    if time.time() < expires_at:
                        self._cache.move_to_end(key)
                        return content
                    del self._cache[key]
        if cache and not keyed_request and self.cache_dir is not None:
            cached = self._read_disk_cache(key)
            if cached is not None:
                content, expires_at = cached
                self._remember(key, content, expires_at)
                return content
        def consume(response: httpx.Response) -> bytes:
            content = response.content
            redirect_set_cookie = any(hop.headers.get("Set-Cookie") for hop in response.history)
            if cache and not self.client.cookies and not redirect_set_cookie and len(content) <= 2_000_000:
                lifetime = self._cache_lifetime(response)
                if lifetime is not None:
                    expires_at = time.time() + lifetime
                    self._remember(key, content, expires_at)
                    if not keyed_request and self.cache_dir is not None:
                        self._write_disk_cache(key, content, expires_at)
            return content

        return self._request(url, lambda: nullcontext(self.client.get(url, params=params, headers=request_headers)),
                             consume)

    def _get_limited(
        self, url: str, *, params: dict[str, str | int] | None,
        headers: dict[str, str] | None, max_bytes: int,
    ) -> bytes:
        safe_url = _safe_origin(url)
        request_headers = {"User-Agent": self.user_agent, **(headers or {})}

        def consume(response: httpx.Response) -> bytes:
            length = response.headers.get("Content-Length")
            if length and length.isdecimal() and int(length) > max_bytes:
                raise ProviderError(f"source response exceeds {max_bytes} bytes for {safe_url}")
            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                if len(content) + len(chunk) > max_bytes:
                    raise ProviderError(f"source response exceeds {max_bytes} bytes for {safe_url}")
                content.extend(chunk)
            return bytes(content)

        return self._request(url, lambda: self.client.stream("GET", url, params=params, headers=request_headers),
                             consume)

    def _cache_lifetime(self, response: httpx.Response) -> float | None:
        if response.headers.get("Set-Cookie"):
            return None
        if response.headers.get("Vary", "").strip() == "*":
            return None
        if "no-cache" in response.headers.get("Pragma", "").lower():
            return None
        lifetime = self.cache_ttl_seconds
        has_max_age = False
        for directive in response.headers.get("Cache-Control", "").lower().split(","):
            directive = directive.strip()
            if directive.startswith(("no-store", "no-cache")):
                return None
            if directive.startswith("max-age="):
                try:
                    max_age = int(directive.removeprefix("max-age=").strip('"'))
                    age = int(response.headers.get("Age", "0"))
                except ValueError:
                    return None
                has_max_age = True
                lifetime = min(lifetime, max_age - age)
        if not has_max_age and (expires := response.headers.get("Expires")):
            try:
                expiry = parsedate_to_datetime(expires)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                return None
            lifetime = min(lifetime, (expiry - datetime.now(timezone.utc)).total_seconds())
        return lifetime if lifetime > 0 else None

    def _remember(self, key: tuple[str, tuple[tuple[str, str], ...]], content: bytes, expires_at: float) -> None:
        with self._cache_lock:
            self._cache[key] = (content, expires_at)
            self._cache.move_to_end(key)
            if len(self._cache) > self.max_cache_entries:
                self._cache.popitem(last=False)

    def _cache_path(self, key: tuple[str, tuple[tuple[str, str], ...]]) -> Path:
        assert self.cache_dir is not None
        digest = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode("ascii")).hexdigest()
        return self.cache_dir / f"{digest}.body"

    def _read_disk_cache(self, key: tuple[str, tuple[tuple[str, str], ...]]) -> tuple[bytes, float] | None:
        path = self._cache_path(key)
        try:
            if path.stat().st_size > 2_000_044:
                return None
            payload = path.read_bytes()
        except OSError:
            return None
        if len(payload) < 44 or payload[:4] != _CACHE_MAGIC:
            return None
        expires_at = struct.unpack(">d", payload[4:12])[0]
        if time.time() >= expires_at or hashlib.sha256(payload[:12] + payload[44:]).digest() != payload[12:44]:
            return None
        return payload[44:], expires_at

    def _write_disk_cache(self, key: tuple[str, tuple[tuple[str, str], ...]], content: bytes, expires_at: float) -> None:
        path = self._cache_path(key)
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".part", dir=path.parent)
            with os.fdopen(fd, "wb") as output:
                header = _CACHE_MAGIC + struct.pack(">d", expires_at)
                output.write(header)
                output.write(hashlib.sha256(header + content).digest())
                output.write(content)
            os.replace(temporary, path)
            temporary = None
            entries = sorted(
                (entry for entry in path.parent.iterdir()
                 if re.fullmatch(r"[0-9a-f]{64}\.body", entry.name)),
                key=lambda entry: entry.stat().st_mtime,
            )
            for old in entries[:-self.max_cache_entries]:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # Cache failure must not hide a successful source response.
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def get_to_file(
        self, url: str, path: str | Path, *,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        expected_prefix: bytes | None = None,
        expected_sha256: str | None = None,
        validate_zip_crc: bool = False,
    ) -> Path:
        """Stream one GET to a temporary file, replacing the target on success."""
        safe_url = _safe_origin(url)
        if expected_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise ValueError("expected_sha256 must be a 64-character hex digest")
        target = Path(path)
        request_headers = {"User-Agent": self.user_agent, **(headers or {})}

        def consume(response: httpx.Response) -> Path:
            fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
            try:
                size = 0
                digest = hashlib.sha256() if expected_sha256 is not None else None
                with os.fdopen(fd, "wb") as output:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        output.write(chunk)
                        size += len(chunk)
                        if digest is not None:
                            digest.update(chunk)
                if size == 0:
                    raise ProviderError(f"source returned an empty document for {safe_url}")
                length = response.headers.get("Content-Length")
                if (
                    length and length.isdecimal()
                    and not response.headers.get("Content-Encoding")
                    and size != int(length)
                ):
                    raise ProviderError(f"source returned an incomplete document for {safe_url}")
                if expected_prefix is not None:
                    with open(temporary, "rb") as saved:
                        if saved.read(len(expected_prefix)) != expected_prefix:
                            raise ProviderError(f"source returned an unexpected document format for {safe_url}")
                if digest is not None and digest.hexdigest() != expected_sha256.lower():
                    raise ProviderError(f"source returned a document with unexpected SHA-256 for {safe_url}")
                if expected_prefix == b"PK\x03\x04":
                    try:
                        with zipfile.ZipFile(temporary) as archive:
                            if validate_zip_crc:
                                if not archive.namelist() or archive.testzip() is not None:
                                    raise ProviderError(f"source returned an invalid ZIP for {safe_url}")
                            else:
                                archive.infolist()
                    except (zipfile.BadZipFile, OSError) as exc:
                        raise ProviderError(f"source returned an invalid ZIP for {safe_url}") from exc
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return target

        return self._request(url, lambda: self.client.stream("GET", url, params=params, headers=request_headers),
                             consume)

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        if value:
            try:
                seconds = float(value)
                if math.isfinite(seconds):
                    return max(0.0, seconds)
            except ValueError:
                pass
            try:
                when = parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
        return min(float(2**attempt), 8.0)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        safe_url = _safe_origin(url)
        try:
            return json.loads(self.get(url, **kwargs))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError(f"source returned invalid JSON for {safe_url}") from exc

    def post_form(
        self, url: str, *, data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> bytes:
        """Submit one idempotent public search form with the same pacing policy."""
        request_headers = {"User-Agent": self.user_agent, **(headers or {})}
        return self._request(url, lambda: nullcontext(self.client.post(url, data=data, headers=request_headers)),
                             lambda response: response.content, accept=lambda status: status < 400)

    def post_json(
        self, url: str, payload: dict[str, Any], *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Submit one idempotent public JSON search without caching its result."""
        safe_url = _safe_origin(url)
        request_headers = {"User-Agent": self.user_agent, **(headers or {})}

        def consume(response: httpx.Response) -> Any:
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError(f"source returned invalid JSON for {safe_url}") from exc

        return self._request(url, lambda: nullcontext(self.client.post(url, json=payload, headers=request_headers)),
                             consume, accept=lambda status: status < 400)
