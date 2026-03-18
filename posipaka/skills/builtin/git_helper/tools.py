"""Git security tools — secret scanning, history audit, repo hygiene."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "Anthropic API Key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI API Key"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "AWS Access Key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub PAT"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "GitHub OAuth"),
    (re.compile(r"glpat-[A-Za-z0-9\-]{20,}"), "GitLab PAT"),
    (re.compile(r"xoxb-[A-Za-z0-9\-]+"), "Slack Bot Token"),
    (re.compile(r"xoxp-[A-Za-z0-9\-]+"), "Slack User Token"),
    (re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}"), "Telegram Bot Token"),
    (re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----"), "Private Key"),
    (re.compile(r"password\s*[=:]\s*[\"'][^\"']{6,}[\"']", re.I), "Hardcoded Password"),
]

_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}
_SKIP_SUFFIXES = {".pyc", ".db", ".sqlite", ".sqlite3"}
_MAX_FILES = 1000
_MAX_FILE_SIZE = 1_000_000  # 1 MB

FORBIDDEN_FILENAMES = [
    ".env",
    "credentials",
    "secret",
    "private_key",
    ".pem",
    ".key",
    "MASTER.md",
    "CLAUDE.md",
]
AI_TRACE_PATTERN = re.compile(r"Co-Authored-By.*(?:Claude|GPT|AI|Copilot)", re.I)


def _load_gitignore(repo: Path) -> list[str]:
    """Load .gitignore patterns (simple line-based matching)."""
    gi = repo / ".gitignore"
    if not gi.exists():
        return []
    patterns: list[str] = []
    for line in gi.read_text(errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(path: Path, repo: Path, patterns: list[str]) -> bool:
    """Simple gitignore check — match filename or relative path parts."""
    rel = str(path.relative_to(repo))
    name = path.name
    for pat in patterns:
        pat_clean = pat.rstrip("/")
        if name == pat_clean or rel.startswith(pat_clean):
            return True
        if pat_clean.startswith("*.") and name.endswith(pat_clean[1:]):
            return True
    return False


async def git_secret_scan(repo_path: str = ".") -> str:
    """Scan repository files for leaked secrets using regex patterns."""
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        return f"Error: {repo} is not a directory."

    gi_patterns = _load_gitignore(repo)
    findings: list[str] = []
    files_scanned = 0

    for p in repo.rglob("*"):
        if files_scanned >= _MAX_FILES:
            break
        if not p.is_file():
            continue
        # skip dirs
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in _SKIP_SUFFIXES:
            continue
        if _is_ignored(p, repo, gi_patterns):
            continue
        if p.stat().st_size > _MAX_FILE_SIZE:
            continue

        try:
            content = p.read_text(errors="replace")
        except Exception:
            continue

        files_scanned += 1
        rel = str(p.relative_to(repo))
        for pattern, label in SECRET_PATTERNS:
            for m in pattern.finditer(content):
                line_no = content[: m.start()].count("\n") + 1
                findings.append(f"  - {rel}:{line_no} — {label}")

    if findings:
        header = f"SECRET SCAN: {len(findings)} issue(s) found in {files_scanned} files:\n"
        return header + "\n".join(findings)
    return f"No secrets found. Scanned {files_scanned} files."


async def git_history_audit(repo_path: str = ".", depth: int = 50) -> str:
    """Audit git commit history for sensitive files and AI traces."""
    import shlex

    from posipaka.integrations.shell.tools import shell_exec

    repo = Path(repo_path).resolve()
    safe_repo = shlex.quote(str(repo))
    cmd = (
        f'git -C {safe_repo} log --all --diff-filter=A --name-only --format="%H %s" -n {int(depth)}'
    )
    output = await shell_exec(cmd)

    if not output or output.startswith("Error"):
        return f"Could not audit history: {output}"

    sensitive_files: list[str] = []
    ai_traces: list[str] = []
    current_commit = ""

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('"') or (len(line) > 40 and " " in line):
            # commit line: hash + message
            current_commit = line.strip('"')
            if AI_TRACE_PATTERN.search(current_commit):
                ai_traces.append(f"  - {current_commit[:80]}")
        else:
            # filename line
            fname_lower = line.lower()
            for forbidden in FORBIDDEN_FILENAMES:
                if forbidden.lower() in fname_lower:
                    sensitive_files.append(f"  - {line} (in commit: {current_commit[:40]}...)")
                    break

    parts: list[str] = [f"HISTORY AUDIT (last {depth} commits):"]
    if sensitive_files:
        parts.append(f"\nSensitive files added ({len(sensitive_files)}):")
        parts.extend(sensitive_files)
    else:
        parts.append("\nNo sensitive files found in history.")

    if ai_traces:
        parts.append(f"\nAI traces in commits ({len(ai_traces)}):")
        parts.extend(ai_traces)
    else:
        parts.append("\nNo AI traces in commit messages.")

    return "\n".join(parts)


async def repo_hygiene_check(repo_path: str = ".") -> str:
    """Check repository hygiene: .gitignore, .dockerignore, LICENSE, etc."""
    from posipaka.integrations.shell.tools import shell_exec

    repo = Path(repo_path).resolve()
    checks: list[str] = []

    # .gitignore
    gi = repo / ".gitignore"
    if gi.exists():
        content = gi.read_text(errors="replace")
        required = [".env", "*.db", "MASTER.md", "CLAUDE.md", ".claude/", ".cursor/"]
        missing = [r for r in required if r not in content]
        if missing:
            checks.append(f"  .gitignore exists but missing: {', '.join(missing)}")
        else:
            checks.append("  .gitignore — all required patterns present")
    else:
        checks.append("  .gitignore — MISSING")

    # .dockerignore
    di = repo / ".dockerignore"
    if di.exists():
        content = di.read_text(errors="replace")
        required = [".env", "MASTER.md", "CLAUDE.md"]
        missing = [r for r in required if r not in content]
        if missing:
            checks.append(f"  .dockerignore exists but missing: {', '.join(missing)}")
        else:
            checks.append("  .dockerignore — all required patterns present")
    else:
        checks.append("  .dockerignore — MISSING")

    # LICENSE
    if (repo / "LICENSE").exists() or (repo / "LICENSE.md").exists():
        checks.append("  LICENSE")
    else:
        checks.append("  LICENSE — MISSING")

    # README.md
    if (repo / "README.md").exists():
        checks.append("  README.md")
    else:
        checks.append("  README.md — MISSING")

    # .env in tracked files
    import shlex

    output = await shell_exec(f"git -C {shlex.quote(str(repo))} ls-files")
    tracked = output.splitlines() if output else []
    env_files = [f for f in tracked if f.strip() == ".env" or f.strip().endswith("/.env")]
    if env_files:
        checks.append(f"  .env tracked — WARNING: {', '.join(env_files)}")
    else:
        checks.append("  No .env in tracked files")

    # pre-commit
    if (repo / ".pre-commit-config.yaml").exists():
        checks.append("  pre-commit config")
    else:
        checks.append("  pre-commit config — MISSING")

    return "REPO HYGIENE CHECK:\n" + "\n".join(checks)


async def git_safe_commit(message: str, files: str = ".") -> str:
    """Safe git commit — scans for secrets before committing. Requires approval."""
    from posipaka.integrations.shell.tools import shell_exec

    # Step 1: secret scan
    scan_result = await git_secret_scan(".")
    if "issue(s) found" in scan_result:
        return f"COMMIT ABORTED — secrets detected!\n\n{scan_result}"

    # Step 2: check message for AI traces
    if AI_TRACE_PATTERN.search(message):
        return (
            "COMMIT ABORTED — commit message contains"
            " AI trace pattern (Co-Authored-By AI/Claude/GPT)."
        )

    # Step 3: commit (sanitize message to prevent shell injection)
    import shlex

    safe_message = shlex.quote(message)
    safe_files = shlex.quote(files)
    add_result = await shell_exec(f"git add {safe_files}")
    if add_result and "error" in add_result.lower():
        return f"git add failed: {add_result}"

    commit_result = await shell_exec(f"git commit -m {safe_message}")
    return f"Commit result:\n{commit_result}"


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="git_secret_scan",
            description="Scan repository files for leaked secrets (API keys, tokens, passwords)",
            category="security",
            handler=git_secret_scan,
            input_schema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to git repo",
                        "default": ".",
                    },
                },
            },
            tags=["git", "security", "scanning"],
        )
    )
    registry.register(
        ToolDefinition(
            name="git_history_audit",
            description="Audit git history for sensitive files and AI traces in commits",
            category="security",
            handler=git_history_audit,
            input_schema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to git repo",
                        "default": ".",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Number of commits to check",
                        "default": 50,
                    },
                },
            },
            tags=["git", "security", "audit"],
        )
    )
    registry.register(
        ToolDefinition(
            name="repo_hygiene_check",
            description="Check repo hygiene: .gitignore, .dockerignore, LICENSE, pre-commit",
            category="security",
            handler=repo_hygiene_check,
            input_schema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Path to git repo",
                        "default": ".",
                    },
                },
            },
            tags=["git", "hygiene"],
        )
    )
    registry.register(
        ToolDefinition(
            name="git_safe_commit",
            description="Safe git commit with pre-commit secret scanning",
            category="security",
            handler=git_safe_commit,
            requires_approval=True,
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                    "files": {"type": "string", "description": "Files to stage", "default": "."},
                },
                "required": ["message"],
            },
            tags=["git", "security", "commit"],
        )
    )
