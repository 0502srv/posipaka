"""Posipaka — GitHub Integration."""

from __future__ import annotations

import os
from typing import Any


def _get_github():
    try:
        from github import Github

        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return None
        return Github(token)
    except ImportError:
        return None


async def github_list_repos(owner: str = "") -> str:
    g = _get_github()
    if not g:
        return "GitHub не налаштовано (GITHUB_TOKEN)."
    try:
        user = g.get_user(owner) if owner else g.get_user()
        repos = list(user.get_repos(sort="updated")[:10])
        lines = [f"Репозиторії {user.login}:\n"]
        for r in repos:
            stars = f" ⭐{r.stargazers_count}" if r.stargazers_count else ""
            lines.append(f"• {r.full_name}{stars} — {r.description or 'без опису'}")
        return "\n".join(lines)
    except Exception as e:
        return f"GitHub помилка: {e}"


async def github_create_issue(repo: str, title: str, body: str = "") -> str:
    g = _get_github()
    if not g:
        return "GitHub не налаштовано."
    try:
        r = g.get_repo(repo)
        issue = r.create_issue(title=title, body=body)
        return f"Issue створено: {issue.html_url}"
    except Exception as e:
        return f"Помилка: {e}"


async def github_list_prs(repo: str) -> str:
    g = _get_github()
    if not g:
        return "GitHub не налаштовано."
    try:
        r = g.get_repo(repo)
        prs = list(r.get_pulls(state="open")[:10])
        if not prs:
            return f"Немає відкритих PR у {repo}"
        lines = [f"Відкриті PR у {repo}:\n"]
        for pr in prs:
            lines.append(f"• #{pr.number} {pr.title} ({pr.user.login})")
        return "\n".join(lines)
    except Exception as e:
        return f"Помилка: {e}"


async def github_get_file(repo: str, path: str) -> str:
    g = _get_github()
    if not g:
        return "GitHub не налаштовано."
    try:
        from posipaka.security.injection import sanitize_external_content

        r = g.get_repo(repo)
        content = r.get_contents(path)
        if hasattr(content, "decoded_content"):
            text = content.decoded_content.decode("utf-8")
            return sanitize_external_content(text[:5000], source=f"github:{repo}/{path}")
        return "Не вдалось прочитати файл"
    except Exception as e:
        return f"Помилка: {e}"


def register(registry: Any) -> None:
    import os

    if not os.environ.get("GITHUB_TOKEN"):
        return

    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="github_list_repos",
            description="List GitHub repositories for a user.",
            category="integration",
            handler=github_list_repos,
            input_schema={
                "type": "object",
                "properties": {
                    "owner": {
                        "type": "string",
                        "description": "GitHub username (default: authenticated user)",
                    }
                },
            },
            tags=["github"],
        )
    )

    registry.register(
        ToolDefinition(
            name="github_create_issue",
            description="Create a GitHub issue. Requires approval.",
            category="integration",
            handler=github_create_issue,
            input_schema={
                "type": "object",
                "required": ["repo", "title"],
                "properties": {
                    "repo": {"type": "string", "description": "Repo in format owner/name"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
            requires_approval=True,
            tags=["github"],
        )
    )

    registry.register(
        ToolDefinition(
            name="github_list_prs",
            description="List open pull requests in a GitHub repository.",
            category="integration",
            handler=github_list_prs,
            input_schema={
                "type": "object",
                "required": ["repo"],
                "properties": {"repo": {"type": "string"}},
            },
            tags=["github"],
        )
    )

    registry.register(
        ToolDefinition(
            name="github_get_file",
            description="Read a file from a GitHub repository.",
            category="integration",
            handler=github_get_file,
            input_schema={
                "type": "object",
                "required": ["repo", "path"],
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo"},
                    "path": {"type": "string", "description": "File path in repo"},
                },
            },
            tags=["github"],
        )
    )
