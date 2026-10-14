"""The distribution audit must detect a missing runtime module."""

from io import BytesIO
from pathlib import Path
import tarfile
import zipfile

import pytest

from scripts.check_distribution import check_archives


_ROOT = Path(__file__).resolve().parents[1]
_MODULES = sorted((_ROOT / "src" / "opencorpfilings").rglob("*.py"))


def _archives(dist: Path, *, omit_wheel: str | None = None, omit_sdist: str | None = None) -> None:
    wheel = dist / "opencorpfilings-0.2.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for module in _MODULES:
            relative = module.relative_to(_ROOT / "src").as_posix()
            if relative != omit_wheel:
                archive.writestr(relative, module.read_bytes())
        archive.writestr("opencorpfilings-0.2.0.dist-info/METADATA", "Name: opencorpfilings")
    source = dist / "opencorpfilings-0.2.0.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        for module in _MODULES:
            relative = module.relative_to(_ROOT).as_posix()
            if relative == omit_sdist:
                continue
            payload = module.read_bytes()
            item = tarfile.TarInfo(f"opencorpfilings-0.2.0/{relative}")
            item.size = len(payload)
            archive.addfile(item, BytesIO(payload))


def test_checker_rejects_missing_wheel_module(tmp_path) -> None:
    _archives(tmp_path, omit_wheel="opencorpfilings/sec_printed_pages.py")
    with pytest.raises(RuntimeError, match="wheel modules"):
        check_archives(tmp_path)


def test_checker_rejects_missing_source_archive_module(tmp_path) -> None:
    _archives(tmp_path, omit_sdist="src/opencorpfilings/sec_printed_pages.py")
    with pytest.raises(RuntimeError, match="source archive modules"):
        check_archives(tmp_path)
