"""The README names only things that exist: imports, methods, ocf commands and environment variables."""

import ast
import re
from pathlib import Path

import pytest

import opencorpfilings
from opencorpfilings import cli

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PYTHON_BLOCKS = re.findall(r"```python\n(.*?)```", README, re.S)
BASH_BLOCKS = re.findall(r"```bash\n(.*?)```", README, re.S)
SOURCE = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "opencorpfilings").rglob("*.py"))


def _public_attributes() -> set[str]:
    names: set[str] = set()
    for name in opencorpfilings.__all__:
        names.update(dir(getattr(opencorpfilings, name)))
    return names


def test_readme_has_python_examples_and_each_compiles():
    assert len(PYTHON_BLOCKS) >= 5
    for block in PYTHON_BLOCKS:
        compile(block, "README.md", "exec")


def test_readme_imports_only_public_names():
    imported = {alias.name for block in PYTHON_BLOCKS for node in ast.walk(ast.parse(block))
                if isinstance(node, ast.ImportFrom) and node.module == "opencorpfilings" for alias in node.names}
    assert imported and imported <= set(opencorpfilings.__all__)


def test_readme_calls_only_methods_that_exist():
    called = {node.attr for block in PYTHON_BLOCKS for node in ast.walk(ast.parse(block)) if isinstance(node, ast.Attribute)}
    inline = set(re.findall(r"`(?:filing|document|collection|company|match)\.([a-z_]+)", README))
    missing = sorted((called | inline) - _public_attributes())
    assert not missing, f"README names attributes no public class has: {missing}"


def test_readme_ocf_commands_exist():
    parser = cli._parser() if hasattr(cli, "_parser") else None
    commands = set(re.findall(r"^ocf (\w+)", "\n".join(BASH_BLOCKS), re.M))
    assert commands
    if parser is None:
        for command in commands:
            assert f'add_parser("{command}"' in (ROOT / "src" / "opencorpfilings" / "cli.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(set(re.findall(r"OPENCORPFILINGS_[A-Z_]+", README))))
def test_readme_environment_variables_are_read_by_the_code(name):
    assert f'"{name}"' in SOURCE
