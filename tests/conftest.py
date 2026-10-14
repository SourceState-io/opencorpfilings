"""Tests run offline and must not depend on the developer's own credentials or cache."""

import os
import socket

import pytest

_CALLER_SETTINGS = ("EDINET_API_KEY", "OPENDART_API_KEY")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("offline test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture(autouse=True)
def _isolate_from_caller_environment(monkeypatch):
    # A developer with real keys or a cache directory set saw 55 tests fail.
    for name in list(os.environ):
        if name.startswith("OPENCORPFILINGS_") or name in _CALLER_SETTINGS:
            monkeypatch.delenv(name)
