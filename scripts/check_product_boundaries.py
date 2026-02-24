#!/usr/bin/env python3
"""Validate product-package import boundaries."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

RULES: list[tuple[Path, set[str], str]] = [
    (
        REPO_ROOT / "packages/maestro-engine/src/maestro_engine",
        {"maestro", "maestro_solo", "maestro_fleet"},
        "maestro-engine must stay product-agnostic",
    ),
    (
        REPO_ROOT / "packages/maestro-solo/src/maestro_solo",
        {"maestro", "maestro_fleet"},
        "maestro-solo must not depend on legacy or fleet packages",
    ),
    (
        REPO_ROOT / "packages/maestro-fleet/src/maestro_fleet",
        {"maestro_solo"},
        "maestro-fleet must not depend on maestro-solo",
    ),
]


def _violations_for_file(path: Path, blocked_roots: set[str]) -> list[tuple[int, str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in blocked_roots:
                    violations.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            # Relative imports stay inside product package; skip them.
            if node.level and node.level > 0:
                continue
            if not node.module:
                continue
            root = node.module.split(".", 1)[0]
            if root in blocked_roots:
                violations.append((node.lineno, node.module))

    return violations


def main() -> int:
    failures: list[str] = []

    for root_dir, blocked, reason in RULES:
        if not root_dir.exists():
            continue
        for py_file in sorted(root_dir.rglob("*.py")):
            for lineno, module_name in _violations_for_file(py_file, blocked):
                rel = py_file.relative_to(REPO_ROOT)
                failures.append(f"{rel}:{lineno}: disallowed import '{module_name}' ({reason})")

    if failures:
        print("Product boundary check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Product boundary check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
