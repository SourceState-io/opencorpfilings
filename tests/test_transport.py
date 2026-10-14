import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest

from opencorpfilings.errors import AuthenticationError, ProviderError, RateLimitError, SourceUnavailableError
from opencorpfilings.transport import HttpTransport


def test_concurrent_requests_share_pacing_gate():
    ready = Barrier(4)
    dispatched = Event()

    def handle(request):
        dispatched.set()
        return httpx.Response(200, content=b"ok")

    transport = HttpTransport(
        min_interval=0.04,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    original_pace = transport._pace

    def synchronized_pace(url):
        ready.wait(timeout=2)
        original_pace(url)

    transport._pace = synchronized_pace
    with ThreadPoolExecutor(max_workers=3) as executor:
        pacer = transport._pacer_for("https://example.test/0")
        pacer.lock.acquire()
        try:
            futures = [executor.submit(transport.get, f"https://example.test/{index}")
                       for index in range(3)]
            ready.wait(timeout=2)
            assert not dispatched.wait(0.02)
        finally:
            pacer.lock.release()
        assert [future.result() for future in futures] == [b"ok"] * 3
    assert dispatched.is_set()


def test_concurrent_cached_reads_share_one_atomic_lookup():
    ready = Barrier(3)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=b"source")

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    url = "https://example.test/filings"
    assert transport.get(url) == b"source"
    cache_lock = transport._cache_lock

    def read():
        ready.wait(timeout=2)
        return transport.get(url)

    with ThreadPoolExecutor(max_workers=2) as executor:
        cache_lock.acquire()
        try:
            futures = [executor.submit(read) for _ in range(2)]
            ready.wait(timeout=2)
            assert not any(future.done() for future in futures)
        finally:
            cache_lock.release()
        assert [future.result() for future in futures] == [b"source", b"source"]
    assert len(calls) == 1


def test_concurrent_expired_cache_reads_refetch_without_stale_bytes():
    ready = Barrier(3)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=b"old" if len(calls) == 1 else b"fresh")

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    url = "https://example.test/filings"
    assert transport.get(url) == b"old"
    with transport._cache_lock:
        key = next(iter(transport._cache))
        transport._cache[key] = (b"old", time.time() - 1)

    def read():
        ready.wait(timeout=2)
        return transport.get(url)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(read) for _ in range(2)]
        ready.wait(timeout=2)
        assert [future.result() for future in futures] == [b"fresh", b"fresh"]
    assert 2 <= len(calls) <= 3


def test_request_cache_and_auth_partition():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=request.headers["X-Key"].encode())

    client = httpx.Client(transport=httpx.MockTransport(handle))
    transport = HttpTransport(client=client)
    url = "https://example.test/one"
    assert transport.get(url, headers={"X-Key": "a"}) == b"a"
    assert transport.get(url, headers={"X-Key": "a"}) == b"a"
    assert transport.get(url, headers={"X-Key": "b"}) == b"b"
    assert len(calls) == 2


def test_opt_in_disk_cache_reuses_public_get_across_transport_instances(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=b"source metadata")

    for _ in range(2):
        transport = HttpTransport(cache_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handle)))
        assert transport.get("https://example.test/list") == b"source metadata"
    assert len(calls) == 1
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("credential", [
    {"headers": {"Authorization": "Bearer private"}},
    {"headers": {"Cookie": "session=private"}},
    {"params": {"Subscription-Key": "private"}},
    {"params": {"crtfc_key": "private"}},
])
def test_explicit_credentials_bypass_response_cache(tmp_path, credential):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=f"version {len(calls)}".encode())

    for expected in (b"version 1", b"version 2"):
        transport = HttpTransport(cache_dir=tmp_path,
                                  client=httpx.Client(transport=httpx.MockTransport(handle)))
        assert transport.get("https://example.test/list", **credential) == expected
    assert len(calls) == 2
    assert list(tmp_path.iterdir()) == []


def test_opt_in_keyed_get_reuses_memory_only_and_partitions_keys(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=f"version {len(calls)}".encode())

    transport = HttpTransport(cache_dir=tmp_path,
                              client=httpx.Client(transport=httpx.MockTransport(handle)))
    url = "https://example.test/daily"
    first = {"Subscription-Key": "first"}
    second = {"Subscription-Key": "second"}
    assert transport.get(url, params=first, cache_credentials_in_memory=True) == b"version 1"
    assert transport.get(url, params=first, cache_credentials_in_memory=True) == b"version 1"
    assert transport.get(url, params=second, cache_credentials_in_memory=True) == b"version 2"
    assert len(calls) == 2
    assert list(tmp_path.iterdir()) == []
    assert all("first" not in repr(key) and "second" not in repr(key) for key in transport._cache)


def test_opt_in_keyed_get_obeys_no_store_and_cache_false(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={"Cache-Control": "no-store"}, content=b"source")

    transport = HttpTransport(cache_dir=tmp_path,
                              client=httpx.Client(transport=httpx.MockTransport(handle)))
    kwargs = {"params": {"Subscription-Key": "private"}, "cache_credentials_in_memory": True}
    assert transport.get("https://example.test/daily", **kwargs) == b"source"
    assert transport.get("https://example.test/daily", **kwargs) == b"source"
    assert transport.get("https://example.test/daily", cache=False, **kwargs) == b"source"
    assert len(calls) == 3
    assert not transport._cache
    assert list(tmp_path.iterdir()) == []


def test_cache_directory_can_be_set_in_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCORPFILINGS_CACHE_DIR", str(tmp_path))
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"one"),
    )))
    assert transport.cache_dir == tmp_path
    assert transport.get("https://example.test/one") == b"one"
    assert len(list(tmp_path.glob("*.body"))) == 1


def test_empty_cache_directory_is_rejected():
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"one"),
    )))
    with pytest.raises(ValueError, match="cache_dir"):
        transport.configure_cache("")


def test_disk_cache_expiry_corruption_and_auth_partition(tmp_path, monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=f"version {len(calls)}".encode())

    def fresh_transport():
        return HttpTransport(cache_dir=tmp_path, cache_ttl_seconds=60,
                             client=httpx.Client(transport=httpx.MockTransport(handle)))

    url = "https://example.test/list"
    assert fresh_transport().get(url, headers={"X-Key": "a"}) == b"version 1"
    assert fresh_transport().get(url, headers={"X-Key": "b"}) == b"version 2"
    assert fresh_transport().get(url, headers={"X-Key": "a"}) == b"version 1"
    assert len(calls) == 2
    cache_files = list(tmp_path.iterdir())
    assert len(cache_files) == 2
    future = time.time() + 120
    monkeypatch.setattr("opencorpfilings.transport.time.time", lambda: future)
    assert fresh_transport().get(url, headers={"X-Key": "a"}) == b"version 3"
    assert len(calls) == 3
    recent = next(path for path in tmp_path.iterdir() if b"version 3" in path.read_bytes())
    recent.write_bytes(b"broken cache entry")
    assert fresh_transport().get(url, headers={"X-Key": "a"}) == b"version 4"
    assert len(calls) == 4


def test_client_level_auth_does_not_share_a_cached_response(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=request.headers["Authorization"].encode())

    responses = []
    for password in ("first", "second"):
        client = httpx.Client(auth=("user", password), transport=httpx.MockTransport(handle))
        transport = HttpTransport(cache_dir=tmp_path, client=client)
        responses.append(transport.get("https://example.test/private"))
    assert len(calls) == 2
    assert responses[0] != responses[1]
    assert list(tmp_path.glob("*.body")) == []


def test_cookie_response_is_not_cached_across_session_changes(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=str(len(calls)).encode(),
                              headers={"Set-Cookie": "session=one; Path=/"})

    transport = HttpTransport(cache_dir=tmp_path,
                              client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert transport.get("https://example.test/session") == b"1"
    assert transport.get("https://example.test/session") == b"2"
    assert len(calls) == 2
    assert list(tmp_path.glob("*.body")) == []


def test_redirect_cookie_does_not_cache_personalized_final_response(tmp_path):
    calls = []

    def client_for(session):
        def handle(request):
            calls.append((session, request.url.path))
            if request.url.path == "/start":
                return httpx.Response(302, headers={
                    "Location": "/personal", "Set-Cookie": f"session={session}; Path=/",
                })
            assert request.headers["Cookie"] == f"session={session}"
            return httpx.Response(200, content=f"account {session}".encode())

        return httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True)

    first = HttpTransport(cache_dir=tmp_path, client=client_for("one"))
    assert first.get("https://example.test/start") == b"account one"
    second = HttpTransport(cache_dir=tmp_path, client=client_for("two"))
    assert second.get("https://example.test/start") == b"account two"
    assert len(calls) == 4
    assert list(tmp_path.glob("*.body")) == []


def test_cookie_free_redirect_still_reuses_public_response(tmp_path):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/public"})
        return httpx.Response(200, content=b"public filing list")

    transport = HttpTransport(cache_dir=tmp_path, client=httpx.Client(
        transport=httpx.MockTransport(handle), follow_redirects=True,
    ))
    assert transport.get("https://example.test/start") == b"public filing list"
    assert transport.get("https://example.test/start") == b"public filing list"
    assert calls == ["/start", "/public"]


def test_disk_cache_is_bounded_and_cache_false_bypasses_it(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=request.url.path.encode())

    transport = HttpTransport(cache_dir=tmp_path, max_cache_entries=2,
                              client=httpx.Client(transport=httpx.MockTransport(handle)))
    for suffix in ("one", "two", "three"):
        assert transport.get(f"https://example.test/{suffix}") == f"/{suffix}".encode()
    assert len(list(tmp_path.glob("*.body"))) == 2
    assert transport.get("https://example.test/two", cache=False) == b"/two"
    assert len(calls) == 4


def test_memory_cache_expires_and_no_store_response_is_not_saved(tmp_path, monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        headers = {"Cache-Control": "private, no-store"} if request.url.path == "/private" else {}
        return httpx.Response(200, content=f"version {len(calls)}".encode(), headers=headers)

    transport = HttpTransport(cache_dir=tmp_path, cache_ttl_seconds=60,
                              client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert transport.get("https://example.test/list") == b"version 1"
    future = time.time() + 120
    monkeypatch.setattr("opencorpfilings.transport.time.time", lambda: future)
    assert transport.get("https://example.test/list") == b"version 2"
    assert transport.get("https://example.test/private") == b"version 3"
    assert transport.get("https://example.test/private") == b"version 4"
    assert len(list(tmp_path.glob("*.body"))) == 1


def test_source_short_freshness_and_no_cache_directives_are_respected(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        policy = "max-age=30" if request.url.path == "/short" else "no-cache"
        return httpx.Response(200, content=str(len(calls)).encode(), headers={"Cache-Control": policy})

    transport = HttpTransport(cache_dir=tmp_path, cache_ttl_seconds=300,
                              client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert transport.get("https://example.test/short") == b"1"
    assert transport.get("https://example.test/short") == b"1"
    fresh = HttpTransport(cache_dir=tmp_path, cache_ttl_seconds=300,
                          client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert fresh.get("https://example.test/short") == b"1"
    assert fresh.get("https://example.test/no-cache") == b"2"
    assert fresh.get("https://example.test/no-cache") == b"3"
    assert len(list(tmp_path.glob("*.body"))) == 1


def test_short_source_freshness_expires_after_remaining_max_age(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("opencorpfilings.transport.time.time", lambda: clock[0])
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=f"version {len(calls)}".encode(),
                              headers={"Cache-Control": "max-age=10", "Age": "4"})

    def fresh_transport():
        return HttpTransport(cache_dir=tmp_path, cache_ttl_seconds=300,
                             client=httpx.Client(transport=httpx.MockTransport(handle)))

    url = "https://example.test/short"
    assert fresh_transport().get(url) == b"version 1"
    clock[0] = 1005.0
    assert fresh_transport().get(url) == b"version 1"
    clock[0] = 1006.0
    assert fresh_transport().get(url) == b"version 2"
    assert len(calls) == 2


def test_authentication_error():
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401)))
    transport = HttpTransport(client=client)
    with pytest.raises(AuthenticationError):
        transport.get("https://example.test/one")


@pytest.mark.parametrize("operation,status,content", [
    ("get", 401, b""),
    ("limited", 401, b""),
    ("get_json", 200, b"not JSON"),
    ("get_to_file", 200, b"not a ZIP"),
    ("post_form", 401, b""),
    ("post_json", 200, b"not JSON"),
])
def test_public_transport_errors_hide_request_credentials(tmp_path, operation, status, content):
    secret = "private-credential-value"
    url = f"https://user:{secret}@example.test/private/path?crtfc_key={secret}"
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, content=content),
    ))
    transport = HttpTransport(client=client, max_retries=0)
    with pytest.raises(ProviderError) as caught:
        if operation == "get":
            transport.get(url, params={"api_key": secret})
        elif operation == "limited":
            transport.get(url, max_bytes=100)
        elif operation == "get_json":
            transport.get_json(url)
        elif operation == "get_to_file":
            transport.get_to_file(url, tmp_path / "original.zip", expected_prefix=b"PK\x03\x04")
        elif operation == "post_form":
            transport.post_form(url, data={"query": "issuer"})
        else:
            transport.post_json(url, {"query": "issuer"})
    message = str(caught.value)
    assert "https://example.test" in message
    assert secret not in message
    assert "crtfc_key" not in message
    assert "api_key" not in message
    assert "/private/path" not in message


def test_request_failure_does_not_echo_http_client_exception_text():
    secret = "private-credential-value"
    url = f"https://example.test/file?api_key={secret}"

    def fail(_):
        raise httpx.ConnectError(f"connection failed for {url}")

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(fail)), max_retries=0)
    with pytest.raises(ProviderError) as caught:
        transport.get(url)
    assert secret not in str(caught.value)
    assert "https://example.test" in str(caught.value)


def test_public_json_search_uses_pacing_retry_and_no_response_cache(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["Content-Type"].startswith("application/json")
        assert request.headers["User-Agent"]
        assert request.content == b'{"query":"Carlsberg","page":1}'
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"rows": ["one"]})

    transport = HttpTransport(cache_dir=tmp_path,
                              client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert transport.post_json("https://example.test/search", {"query": "Carlsberg", "page": 1}) == {"rows": ["one"]}
    assert len(calls) == 2
    assert list(tmp_path.iterdir()) == []


def test_long_retry_after_is_respected_without_early_retry():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(RateLimitError, match="retry after 120s"):
        transport.get("https://example.test/one")
    assert len(calls) == 1


def test_nonfinite_retry_after_uses_bounded_backoff():
    response = httpx.Response(429, headers={"Retry-After": "NaN"})
    assert HttpTransport._retry_delay(response, 0) == 1.0
    response = httpx.Response(503, headers={"Retry-After": "Infinity"})
    assert HttpTransport._retry_delay(response, 1) == 2.0


@pytest.mark.parametrize("option,value", [("max_retries", -1), ("min_interval", -0.1)])
def test_invalid_retry_and_pacing_configuration_fails_clearly(option, value):
    with pytest.raises(ValueError, match=option):
        HttpTransport(**{option: value})


def test_streamed_get_saves_original_chunks_and_honors_retry(tmp_path):
    calls = []

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b"first-"
            yield b"second"

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, stream=Chunks())

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(handle)))
    target = tmp_path / "original.bin"
    assert transport.get_to_file("https://example.test/one", target, headers={"X-Key": "secret"}) == target
    assert target.read_bytes() == b"first-second"
    assert len(calls) == 2
    assert all(call.headers["X-Key"] == "secret" for call in calls)
    assert list(tmp_path.iterdir()) == [target]


def test_streamed_get_failure_preserves_existing_file(tmp_path):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadError("connection ended")

    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, stream=Broken()),
    )), max_retries=0)
    target = tmp_path / "original.bin"
    target.write_bytes(b"existing")
    with pytest.raises(ProviderError, match="request failed"):
        transport.get_to_file("https://example.test/one", target)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


def test_streamed_get_rejects_partial_or_truncated_response(tmp_path):
    target = tmp_path / "original.bin"
    target.write_bytes(b"existing")
    for response in (
        httpx.Response(206, content=b"partial"),
        httpx.Response(302, headers={"Location": "https://example.test/login"}),
        httpx.Response(200, headers={"Content-Length": "10"}, content=b"short"),
    ):
        transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(lambda _: response)))
        with pytest.raises(ProviderError):
            transport.get_to_file("https://example.test/one", target)
        assert target.read_bytes() == b"existing"
        assert list(tmp_path.iterdir()) == [target]


def test_streamed_get_rejects_empty_200_without_replacing_target(tmp_path):
    target = tmp_path / "original.html"
    target.write_bytes(b"existing original")
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b""),
    )))
    with pytest.raises(ProviderError, match="empty document"):
        transport.get_to_file("https://example.test/original.html", target)
    assert target.read_bytes() == b"existing original"
    assert list(tmp_path.iterdir()) == [target]


def test_streamed_get_checks_source_magic_before_replacing_target(tmp_path):
    target = tmp_path / "annual.zip"
    target.write_bytes(b"existing")
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"<html>source error</html>")
    )))
    with pytest.raises(ProviderError, match="unexpected document format"):
        transport.get_to_file("https://example.test/annual.zip", target, expected_prefix=b"PK\x03\x04")
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("status", [206, 302])
@pytest.mark.parametrize("max_bytes", [None, 100])
def test_buffered_get_rejects_partial_or_unfollowed_redirect(status, max_bytes):
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, content=b"incomplete")
    ), follow_redirects=False)
    transport = HttpTransport(client=client)
    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        transport.get("https://example.test/original", max_bytes=max_bytes)


@pytest.mark.parametrize("operation", ["get", "limited", "save", "post", "post_json"])
@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_exhausted_temporary_source_failure_has_common_error(tmp_path, operation, status):
    transport = HttpTransport(max_retries=0, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(status, content=b"temporarily unavailable"),
    )))
    url = "https://example.test/original"
    target = tmp_path / "original"
    target.write_bytes(b"existing")
    with pytest.raises(SourceUnavailableError, match=f"HTTP {status}"):
        if operation == "get":
            transport.get(url)
        elif operation == "limited":
            transport.get(url, max_bytes=100)
        elif operation == "save":
            transport.get_to_file(url, target)
        elif operation == "post_json":
            transport.post_json(url, {"q": "one"})
        else:
            transport.post_form(url, data={"q": "one"})
    assert target.read_bytes() == b"existing"


@pytest.mark.parametrize("operation", ["get", "limited", "save", "post", "post_json"])
def test_one_transient_500_retries_then_returns_source_result(tmp_path, operation):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, content=b"temporarily unavailable")
        if operation == "post_json":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, content=b"source original")

    transport = HttpTransport(max_retries=1, client=httpx.Client(transport=httpx.MockTransport(handle)))
    transport._retry_delay = lambda *_: 0
    url = "https://example.test/original"
    if operation == "get":
        result = transport.get(url)
    elif operation == "limited":
        result = transport.get(url, max_bytes=100)
    elif operation == "save":
        target = tmp_path / "original"
        target.write_bytes(b"existing")
        result = transport.get_to_file(url, target).read_bytes()
    elif operation == "post_json":
        result = transport.post_json(url, {"q": "one"})
    else:
        result = transport.post_form(url, data={"q": "one"})
    assert result == ({"ok": True} if operation == "post_json" else b"source original")
    assert len(calls) == 2


def test_unimplemented_source_501_is_not_retried():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(501, content=b"not implemented")

    transport = HttpTransport(max_retries=2, client=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(ProviderError, match="HTTP 501"):
        transport.get("https://example.test/original")
    assert len(calls) == 1


def test_post_form_long_source_retry_delay_is_unavailable_not_rate_limit() -> None:
    transport = HttpTransport(max_retries=1, client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(503, headers={"Retry-After": "120"}),
    )))
    with pytest.raises(SourceUnavailableError, match="retry after 120s"):
        transport.post_form("https://example.test/search", data={"q": "one"})


def test_streamed_get_rejects_truncated_zip_with_valid_magic(tmp_path):
    target = tmp_path / "original.zip"
    target.write_bytes(b"existing")
    transport = HttpTransport(client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"PK\x03\x04truncated")
    )))
    with pytest.raises(ProviderError, match="invalid ZIP"):
        transport.get_to_file("https://example.test/original.zip", target, expected_prefix=b"PK\x03\x04")
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]


def test_streamed_get_checks_source_sha256_before_replacing_target(tmp_path):
    import hashlib

    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr("report.txt", "source package")
    body = package.getvalue()
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)))
    transport = HttpTransport(client=client)
    target = tmp_path / "original.zip"
    target.write_bytes(b"existing")
    with pytest.raises(ProviderError, match="SHA-256"):
        transport.get_to_file("https://example.test/original.zip", target,
                              expected_prefix=b"PK\x03\x04", expected_sha256="0" * 64)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.glob("*.part")) == []
    assert transport.get_to_file("https://example.test/original.zip", target,
                                 expected_prefix=b"PK\x03\x04",
                                 expected_sha256=hashlib.sha256(body).hexdigest()) == target
    assert target.read_bytes() == body
    assert list(tmp_path.iterdir()) == [target]


def test_separate_transports_share_pacing_for_one_source_host():
    def handle(request):
        return httpx.Response(200, content=b"ok")

    first, second = (HttpTransport(min_interval=0.3, client=httpx.Client(transport=httpx.MockTransport(handle)))
                     for _ in range(2))
    started = time.monotonic()
    first.get("https://pacing.example.test/a", cache=False)
    second.get("https://pacing.example.test/b", cache=False)
    assert time.monotonic() - started >= 0.25
    started = time.monotonic()
    second.get("https://other-host.example.test/c", cache=False)
    assert time.monotonic() - started < 0.25
