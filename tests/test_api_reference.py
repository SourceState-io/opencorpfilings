"""The API reference is generated from the code and every public member says what it does."""

import inspect
from pathlib import Path

import opencorpfilings as package
from scripts.api_reference import _members, render

ROOT = Path(__file__).resolve().parents[1]


def test_committed_api_reference_matches_the_code():
    assert (ROOT / "API.md").read_text(encoding="utf-8") == render(), \
        "regenerate with: python scripts/api_reference.py > API.md"


def test_every_public_class_method_and_property_has_a_docstring():
    missing = []
    for name in package.__all__:
        obj = getattr(package, name)
        if not inspect.isclass(obj) or issubclass(obj, BaseException):
            continue
        for member, value in _members(obj):
            target = value.fget if isinstance(value, property) else getattr(value, "__func__", value)
            if not inspect.getdoc(target):
                missing.append(f"{name}.{member}")
    assert missing == []
