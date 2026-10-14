"""Record real source responses once, then replay them offline in tests.

Recording wraps httpx at the transport layer, so providers run their real code
paths. A response is keyed by method, URL without credential parameters, and a
digest of any request body. Request headers (where API keys can travel) are
never stored, and bodies are gzip-compressed on disk.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

CREDENTIAL_PARAMS = frozenset({
    "api_key", "api-key", "apikey", "access_token", "token", "key",
    "subscription-key", "crtfc_key",
})


def request_key(method: str, url: str, body: bytes = b"") -> str:
    parts = urlsplit(url)
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                   if k.lower() not in CREDENTIAL_PARAMS)
    digest = hashlib.sha256(body).hexdigest()[:16] if body else ""
    return f"{method.upper()} {parts.scheme}://{parts.netloc}{parts.path}?{urlencode(query)} {digest}".rstrip()


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.inner = httpx.HTTPTransport()
        self.index: dict[str, dict] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        content = response.read()
        key = request_key(request.method, str(request.url), request.content)
        name = f"{len(self.index):03d}.bin.gz"
        (self.directory / name).write_bytes(gzip.compress(content, mtime=0))
        self.index[key] = {"status": response.status_code, "file": name,
                           "content_type": response.headers.get("content-type", "")}
        # read() already decoded the body, so the encoding headers no longer describe it.
        headers = [(k, v) for k, v in response.headers.items()
                   if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}]
        return httpx.Response(response.status_code, headers=headers, content=content, request=request)

    def save(self) -> None:
        (self.directory / "responses.json").write_text(
            json.dumps(self.index, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def replay_client(directory: Path) -> httpx.Client:
    index = json.loads((directory / "responses.json").read_text(encoding="utf-8"))

    def handle(request: httpx.Request) -> httpx.Response:
        key = request_key(request.method, str(request.url), request.content)
        if key not in index:
            raise AssertionError(f"no recorded response for {key}")
        entry = index[key]
        body = gzip.decompress((directory / entry["file"]).read_bytes())
        return httpx.Response(entry["status"], content=body, headers={"content-type": entry["content_type"]})

    return httpx.Client(transport=httpx.MockTransport(handle))
