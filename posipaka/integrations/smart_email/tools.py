"""Smart Email integration — classification and auto-filtering.

Extends gmail integration with smart categorization.
"""

from __future__ import annotations

from typing import Any

# Email categories
CATEGORIES = {
    "urgent": ["urgent", "asap", "critical", "терміново", "негайно", "важливо"],
    "newsletter": ["unsubscribe", "newsletter", "digest", "відписатися", "розсилка"],
    "notification": ["notification", "alert", "noreply", "no-reply", "сповіщення"],
    "personal": [],  # fallback
    "work": ["meeting", "sprint", "standup", "deadline", "зустріч", "задача"],
    "finance": ["invoice", "payment", "receipt", "рахунок", "оплата", "чек"],
    "spam": ["lottery", "winner", "congratulations", "виграш", "лотерея"],
}


def classify_email(subject: str, sender: str, body_preview: str) -> str:
    """Класифікувати email за категорією."""
    text = f"{subject} {sender} {body_preview}".lower()

    for category, keywords in CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return category

    return "personal"


async def smart_email_summary(max_emails: int = 20) -> str:
    """Отримати розумний підсумок пошти з категоризацією."""
    try:
        from posipaka.integrations.gmail.tools import gmail_list
    except ImportError:
        return "Gmail інтеграція не доступна."

    emails_text = await gmail_list(max_results=max_emails)
    if "не налаштовано" in emails_text.lower() or "error" in emails_text.lower():
        return emails_text

    # Parse and categorize
    categorized: dict[str, list[str]] = {}
    for line in emails_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("Листи"):
            continue
        category = classify_email(line, "", line)
        categorized.setdefault(category, []).append(line)

    # Build summary
    lines = ["Розумний підсумок пошти:"]
    priority_order = ["urgent", "work", "personal", "finance", "notification", "newsletter", "spam"]
    for cat in priority_order:
        emails = categorized.get(cat, [])
        if emails:
            emoji = {
                "urgent": "🔴",
                "work": "💼",
                "personal": "💬",
                "finance": "💰",
                "notification": "🔔",
                "newsletter": "📰",
                "spam": "🗑️",
            }.get(cat, "📧")
            lines.append(f"\n{emoji} {cat.upper()} ({len(emails)}):")
            for e in emails[:5]:
                lines.append(f"  • {e[:80]}")
            if len(emails) > 5:
                lines.append(f"  ... та ще {len(emails) - 5}")

    return "\n".join(lines)


async def email_filter_rules() -> str:
    """Показати правила фільтрації пошти."""
    lines = ["Правила фільтрації пошти:"]
    for category, keywords in CATEGORIES.items():
        if keywords:
            lines.append(f"  {category}: {', '.join(keywords[:5])}")
    return "\n".join(lines)


def register(registry: Any) -> None:
    import os

    if not os.environ.get("GOOGLE_TOKEN_PATH"):
        return

    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="smart_email_summary",
            description=(
                "Get a smart email summary with automatic "
                "categorization (urgent, work, personal, etc)."
            ),
            category="email",
            handler=smart_email_summary,
            input_schema={
                "type": "object",
                "properties": {
                    "max_emails": {
                        "type": "integer",
                        "description": "Max emails to analyze (default 20)",
                    },
                },
            },
            tags=["email", "smart", "categorize"],
        )
    )

    registry.register(
        ToolDefinition(
            name="email_filter_rules",
            description="Show email categorization/filter rules.",
            category="email",
            handler=email_filter_rules,
            input_schema={"type": "object", "properties": {}},
            tags=["email", "filter", "rules"],
        )
    )
