#!/usr/bin/env python3
"""Pre-commit hook: prevent committing dev/private files and AI traces."""

from __future__ import annotations

import re
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
    ".copilot-instructions.md",
    ".aider.conf.yml",
    ".aider.input.history",
    ".aider.chat.history.md",
]

FORBIDDEN_DIRS = [
    ".claude/",
    ".cursor/",
    ".windsurf/",
    ".aider/",
]

# Patterns in code that reveal AI authorship
AI_CODE_PATTERNS = [
    re.compile(
        r"#\s*(generated|written|created)\s+(by|with)\s+"
        r"(ai|claude|gpt|copilot|chatgpt|gemini|cursor)",
        re.I,
    ),
    re.compile(r"#\s*ai[- ]generated", re.I),
    re.compile(r"#\s*this (code|file) was (generated|written|created) (by|with|using)", re.I),
]

# Patterns in commit messages that reveal AI authorship
AI_COMMIT_PATTERNS = [
    re.compile(
        r"co-authored-by:.*\b(claude|gpt|copilot|cursor"
        r"|ai|anthropic|openai|gemini)\b",
        re.I,
    ),
    re.compile(r"generated (by|with) (claude|gpt|copilot|cursor|ai|chatgpt|gemini)", re.I),
    re.compile(r"\bai[- ]generated\b", re.I),
]


def _check_staged_files() -> list[str]:
    """Check staged files for forbidden names/dirs."""
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
    return violations


def _check_ai_traces_in_diff() -> list[str]:
    """Scan staged diff for AI-authorship markers in code."""
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
            added = line[1:]
            for pattern in AI_CODE_PATTERNS:
                if pattern.search(added):
                    violations.append(f"  AI TRACE in {current_file}: {added.strip()}")
                    break
    return violations


def _check_commit_message() -> list[str]:
    """Check commit message for AI-authorship markers (commit-msg hook)."""
    # This runs as pre-commit, so commit message is not yet available.
    # For commit-msg hook, the message file path is passed as argv[1].
    if len(sys.argv) < 2:
        return []
    msg_file = sys.argv[1]
    try:
        with open(msg_file) as f:
            msg = f.read()
    except (OSError, FileNotFoundError):
        return []
    violations = []
    for pattern in AI_COMMIT_PATTERNS:
        match = pattern.search(msg)
        if match:
            violations.append(f"  AI TRACE in commit message: {match.group()}")
    return violations


def main() -> int:
    violations = []
    violations.extend(_check_staged_files())
    violations.extend(_check_ai_traces_in_diff())
    violations.extend(_check_commit_message())

    if violations:
        print("Pre-commit check failed:")
        for v in violations:
            print(v)
        print("\nFix violations before committing.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
