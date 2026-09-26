"""No pure-logic module reads a clock or calls an LLM (spec §1).

Covers both pure packages: app/domain/ (platform logic) and
app/assistant_domain/ (the assistant's own). Checked structurally rather
than by review, because the fake clock in layer 4 depends on it and a single
datetime.now() would quietly break it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
PURE_DIRS = (APP_DIR / "domain", APP_DIR / "assistant_domain")
PURE_FILES = sorted(path for directory in PURE_DIRS for path in directory.rglob("*.py"))

FORBIDDEN_CALLS = {"now", "utcnow", "today", "monotonic"}
# `time` is banned as an import rather than as a call: that makes time.time()
# unreachable without also banning datetime.time(), which is a component
# accessor, not a clock read.
FORBIDDEN_IMPORTS = {"time", "anthropic", "openai", "sentence_transformers", "httpx", "requests"}


def test_both_pure_packages_are_present():
    assert PURE_FILES
    for directory in PURE_DIRS:
        assert directory.is_dir(), directory


@pytest.mark.parametrize("path", PURE_FILES, ids=lambda p: str(p.relative_to(APP_DIR)))
def test_no_clock_and_no_llm(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in FORBIDDEN_CALLS, f"{path.name} calls .{node.func.attr}()"
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert not roots & FORBIDDEN_IMPORTS, f"{path.name} imports {roots & FORBIDDEN_IMPORTS}"
