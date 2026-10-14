"""Two Company objects on one source share its request pacing within a process."""

from opencorpfilings import transport as transport_module
from opencorpfilings.transport import HttpTransport


def test_transports_with_one_pace_key_share_the_interval(monkeypatch):
    clock = [100.0]
    slept = []
    monkeypatch.setattr(transport_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(transport_module.time, "sleep", lambda seconds: slept.append(round(seconds, 3)))
    first = HttpTransport(min_interval=0.12, pace_key="test-shared-host")
    second = HttpTransport(min_interval=0.12, pace_key="test-shared-host")
    separate = HttpTransport(min_interval=0.12)
    first._pace("https://shared.example.test/1")
    second._pace("https://other.example.test/2")
    separate._pace("https://separate.example.test/3")
    assert slept == [0.12]
    for transport in (first, second, separate):
        transport.close()


def test_sec_provider_paces_per_process(monkeypatch):
    from opencorpfilings.providers.sec import SECProvider

    provider = SECProvider(user_agent="Example Contact contact@example.com")
    try:
        assert provider.transport.pace_key == "sec.gov"
    finally:
        provider.close()
