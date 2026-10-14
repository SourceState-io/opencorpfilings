"""Check built archives with declared base dependencies outside the source checkout."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def check_archives(dist: Path) -> Path:
    wheels = list(dist.glob("opencorpfilings-*.whl"))
    source_archives = list(dist.glob("opencorpfilings-*.tar.gz"))
    if len(wheels) != 1 or len(source_archives) != 1:
        raise RuntimeError("Expected exactly one wheel and one source archive")

    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    roots = {name.split("/", 1)[0] for name in names}
    if "opencorpfilings" not in roots or len(roots) != 2:
        raise RuntimeError(f"Unexpected wheel roots: {sorted(roots)}")
    if not any(root.endswith(".dist-info") for root in roots):
        raise RuntimeError(f"Wheel metadata missing: {sorted(roots)}")

    package_root = Path(__file__).resolve().parents[1] / "src" / "opencorpfilings"
    expected_modules = {
        module.relative_to(package_root.parent).as_posix()
        for module in package_root.rglob("*.py")
    }
    wheel_modules = {name for name in names if name.startswith("opencorpfilings/") and name.endswith(".py")}
    if wheel_modules != expected_modules:
        raise RuntimeError(
            f"wheel modules differ from source: missing {sorted(expected_modules - wheel_modules)}, "
            f"extra {sorted(wheel_modules - expected_modules)}"
        )

    with tarfile.open(source_archives[0], "r:gz") as archive:
        source_names = archive.getnames()
    for name in source_names:
        parts = Path(name).parts
        if any(part == ".env" or part == "__pycache__" or part.lower() == "hermes" for part in parts):
            raise RuntimeError(f"Unexpected source archive member: {name}")
        if name.endswith(".pyc"):
            raise RuntimeError(f"Compiled Python file in source archive: {name}")
    source_modules = {
        name.split("/", 1)[1].removeprefix("src/")
        for name in source_names
        if "/src/opencorpfilings/" in name and name.endswith(".py")
    }
    if source_modules != expected_modules:
        raise RuntimeError(
            f"source archive modules differ from source: missing {sorted(expected_modules - source_modules)}, "
            f"extra {sorted(source_modules - expected_modules)}"
        )
    print(f"Archive contents: {len(names)} wheel members, {len(source_names)} source members")
    return wheel


def _isolated_import(code: str, target: Path, scratch: Path) -> None:
    environment = os.environ.copy()
    environment["SSF_INSTALL_TARGET"] = str(target)
    subprocess.run([sys.executable, "-I", "-c", code], check=True, cwd=scratch, env=environment)


def check_installed_import(wheel: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ocf-distribution-") as scratch:
        scratch_path = Path(scratch)
        target = scratch_path / "installed"
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--target", str(target), str(wheel)],
            check=True,
            cwd=scratch_path,
        )
        code = """
import os
import sys
import importlib
import pkgutil
from pathlib import Path

target = Path(os.environ['SSF_INSTALL_TARGET']).resolve()
sys.path[:] = [str(target)] + [
    path for path in sys.path
    if 'site-packages' not in path.lower() and 'dist-packages' not in path.lower()
]
import opencorpfilings as filings
import bs4
import httpx

origin = Path(filings.__file__).resolve()
assert origin.is_relative_to(target), origin
assert Path(bs4.__file__).resolve().is_relative_to(target), bs4.__file__
assert Path(httpx.__file__).resolve().is_relative_to(target), httpx.__file__
for module in pkgutil.walk_packages(filings.__path__, prefix='opencorpfilings.'):
    importlib.import_module(module.name)
assert 'hermes' not in sys.modules
assert filings.supported_markets()
print(f'Installed import: {origin}')
"""
        _isolated_import(code, target, scratch_path)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(target),
             f"{wheel}[pdf,markdown]"],
            check=True,
            cwd=scratch_path,
        )
        optional_code = """
import os
import sys
from io import BytesIO
from pathlib import Path

target = Path(os.environ['SSF_INSTALL_TARGET']).resolve()
sys.path[:] = [str(target)] + [
    path for path in sys.path
    if 'site-packages' not in path.lower() and 'dist-packages' not in path.lower()
]
import markdownify
import pypdf
from opencorpfilings.markdown_text import html_to_markdown
from opencorpfilings.pdf_text import extract_pdf_pages

assert Path(markdownify.__file__).resolve().is_relative_to(target)
assert Path(pypdf.__file__).resolve().is_relative_to(target)
assert html_to_markdown(b'<h1>Report</h1><p>Original</p>') == '# Report\\n\\nOriginal'
pdf = BytesIO()
writer = pypdf.PdfWriter()
writer.add_blank_page(width=72, height=72)
writer.write(pdf)
assert extract_pdf_pages(pdf.getvalue()) == ('',)
print('Installed optional PDF and Markdown parsers from wheel extras')
"""
        _isolated_import(optional_code, target, scratch_path)


if __name__ == "__main__":
    distribution = Path(sys.argv[1] if len(sys.argv) > 1 else "dist").resolve()
    check_installed_import(check_archives(distribution))
