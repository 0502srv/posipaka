#!/usr/bin/env python3
"""Pre-commit hook: prevent committing dev/private files."""

from __future__ import annotations

import subprocess
import sys

FORBIDDEN_FILES = [
    "MASTER.md",
    "PLANNING.md",
    "DEV_NOTES.md",
    "TODO_PRIVATE.md",
    "CLAUDE.md",
    ".cursorrules",
    ".cursorignore",
    ".windsurfrules",
]

FORBIDDEN_DIRS = [
    ".claude/",
    ".cursor/",
    ".windsurf/",
]


def main() -> int:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
    )
    staged = result.stdout.strip().splitlines()

    violations = []
    for filepath in staged:
        name = filepath.split("/")[-1]
        if name in FORBIDDEN_FILES:
            violations.append(f"  FORBIDDEN FILE: {filepath}")
        for d in FORBIDDEN_DIRS:
            if d in filepath:
                violations.append(f"  FORBIDDEN DIR: {filepath}")

    if violations:
        print("Forbidden files in staging area:")
        for v in violations:
            print(v)
        print("\nRemove with: git reset HEAD <file>")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
