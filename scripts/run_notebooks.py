"""Execute example notebooks cell by cell and store their outputs, without Jupyter.

Example:
    python scripts/run_notebooks.py examples/notebooks/*.ipynb

Cells run in order in one namespace with the notebook's folder as the working
directory, so relative download folders land next to it. A cell's printed text
and the value of its last expression are saved as outputs (with an HTML form
when the value has one). Any exception stops the run, so a notebook that
reaches the end ran cleanly against the live sources.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import sys
from pathlib import Path


def _run_cell(source: str, namespace: dict) -> list[dict]:
    tree = ast.parse(source)
    last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    stdout = io.StringIO()
    value = None
    with contextlib.redirect_stdout(stdout):
        exec(compile(tree, "<cell>", "exec"), namespace)
        if last is not None:
            value = eval(compile(ast.Expression(last.value), "<cell>", "eval"), namespace)
    outputs = []
    if stdout.getvalue():
        outputs.append({"output_type": "stream", "name": "stdout", "text": stdout.getvalue()})
    if value is not None:
        data = {"text/plain": repr(value)}
        if hasattr(value, "_repr_html_"):
            html = value._repr_html_()
            if html:
                data["text/html"] = html
        outputs.append({"output_type": "execute_result", "data": data, "metadata": {}, "execution_count": None})
    return outputs


def run(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    namespace: dict = {"__name__": "__main__"}
    previous = Path.cwd()
    os.chdir(path.parent)
    try:
        count = 0
        for cell in notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            count += 1
            source = "".join(cell["source"])
            try:
                outputs = _run_cell(source, namespace)
            except Exception as exc:
                raise SystemExit(f"{path.name} cell {count} failed: {type(exc).__name__}: {exc}") from exc
            cell["outputs"] = outputs
            cell["execution_count"] = count
            for output in outputs:
                if output["output_type"] == "execute_result":
                    output["execution_count"] = count
    finally:
        os.chdir(previous)
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{path.name}: {count} cells ran")


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        run(Path(argument))
