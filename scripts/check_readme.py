"""Run every Python block in README.md against the live sources, in order, in a temporary folder.

Example:
    OPENCORPFILINGS_SEC_USER_AGENT="Your Name you@example.com" EDINET_API_KEY=... python scripts/check_readme.py

It makes real requests (about a minute, mostly EDINET) and writes only into a
temporary directory. Compare its output with the README's ```text blocks.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import tempfile
import time
import traceback
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def main() -> int:
    blocks = re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.S)
    namespace: dict[str, object] = {}
    failures = 0
    with tempfile.TemporaryDirectory() as folder:
        previous = os.getcwd()
        os.chdir(folder)
        try:
            for number, block in enumerate(blocks, 1):
                started = time.perf_counter()
                output = io.StringIO()
                try:
                    with contextlib.redirect_stdout(output):
                        exec(compile(block, f"README block {number}", "exec"), namespace)
                    status = "ok"
                except Exception:
                    failures += 1
                    status = "FAILED\n" + traceback.format_exc(limit=3)
                print(f"--- block {number}: {status} ({time.perf_counter() - started:.1f}s)")
                print(output.getvalue(), end="")
        finally:
            os.chdir(previous)
    print(f"{len(blocks)} blocks, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
