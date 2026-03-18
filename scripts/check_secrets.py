#!/usr/bin/env python3
"""Pre-commit hook: scan staged changes for secrets."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml


def _load_patterns() -> list[dict]:
    """Load secret patterns from .secrets-patterns.yaml."""
    config_path = Path(__file__).parent.parent / ".secrets-patterns.yaml"
    if not config_path.exists():
        return []
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("patterns", [])


def _load_allowlist() -> set[str]:
    """Load allowlisted files."""
    config_path = Path(__file__).parent.parent / ".secrets-patterns.yaml"
    if not config_path.exists():
        return set()
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return set(config.get("allowlist_files", []))


def main() -> int:
    patterns_config = _load_patterns()
    allowlist = _load_allowlist()

    if not patterns_config:
        return 0

    compiled = [
        (re.compile(p["pattern"]), p["name"], p.get("severity", "high")) for p in patterns_config
    ]

    result = subprocess.run(
        ["git", "diff", "--cached", "-U0"],
        capture_output=True,
        text=True,
    )

    violations = []
    current_file = ""

    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            if current_file in allowlist:
                continue
            # Skip test files — they may contain pattern strings
            if "/tests/" in current_file or "/test_" in current_file:
                continue
            added = line[1:]
            for regex, name, severity in compiled:
                if regex.search(added):
                    # Skip if it's in a comment or string that looks like a pattern definition
                    stripped = added.strip()
                    if (
                        stripped.startswith("#")
                        or "re.compile" in stripped
                        or "pattern" in stripped.lower()
                    ):
                        continue
                    violations.append(
                        f"  [{severity.upper()}] {name} in {current_file}: {stripped[:80]}"
                    )
                    break

    if violations:
        print("Secrets detected in staged changes:")
        for v in violations:
            print(v)
        print("\nRemove secrets before committing.")
        print(
            "If this is a false positive, add the file to allowlist_files in .secrets-patterns.yaml"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
