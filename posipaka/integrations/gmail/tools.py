"""Posipaka — Gmail Integration (Google API)."""

from __future__ import annotations

from typing import Any

from loguru import logger

from posipaka.security.injection import sanitize_external_content

# Gmail tools require google-api-python-client
# pip install posipaka[google]


async def gmail_list(max_results: int = 10, query: str = "") -> str:
    """Список останніх листів (паралельний fetch метаданих)."""
    try:
        import asyncio

        service = _get_gmail_service()
        if not service:
            return "Gmail не налаштовано. Запустіть `posipaka integrations setup gmail`."

        results = (
            service.users().messages().list(userId="me", maxResults=max_results, q=query).execute()
        )
        messages = results.get("messages", [])

        if not messages:
            return "Листів не знайдено."

        # Паралельний fetch метаданих (замість N+1 sequential)
        async def _get_metadata(msg_id: str) -> str:
            msg = await asyncio.to_thread(
                lambda: (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_id,
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    )
                    .execute()
                )
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            subj = headers.get("Subject", "(без теми)")
            frm = headers.get("From", "?")
            date = headers.get("Date", "?")
            return f"📧 [{msg_id[:8]}] {subj}\n   Від: {frm} | {date}"

        tasks = [_get_metadata(m["id"]) for m in messages]
        lines = await asyncio.gather(*tasks, return_exceptions=True)

        # Фільтруємо помилки
        result_lines = []
        for line in lines:
            if isinstance(line, Exception):
                logger.debug(f"Gmail metadata fetch error: {line}")
            else:
                result_lines.append(line)

        return "\n".join(result_lines) or "Листів не знайдено."
    except Exception as e:
        logger.error(f"Gmail list error: {e}")
        return f"Помилка Gmail: {e}"


async def gmail_read(message_id: str) -> str:
    """Прочитати лист за ID."""
    try:
        service = _get_gmail_service()
        if not service:
            return "Gmail не налаштовано."

        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = _extract_body(msg.get("payload", {}))

        result = (
            f"Від: {headers.get('From', '?')}\n"
            f"Тема: {headers.get('Subject', '?')}\n"
            f"Дата: {headers.get('Date', '?')}\n\n"
            f"{body}"
        )
        return sanitize_external_content(result, source="gmail")
    except Exception as e:
        return f"Помилка читання листа: {e}"


async def send_email(to: str, subject: str, body: str) -> str:
    """Надіслати лист (requires approval)."""
    try:
        import base64
        from email.mime.text import MIMEText

        service = _get_gmail_service()
        if not service:
            return "Gmail не налаштовано."

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Лист надіслано до {to}"
    except Exception as e:
        return f"Помилка відправки: {e}"


async def gmail_search(query: str, max_results: int = 5) -> str:
    """Пошук листів."""
    return await gmail_list(max_results=max_results, query=query)


async def gmail_archive(message_id: str) -> str:
    """Архівувати лист."""
    try:
        service = _get_gmail_service()
        if not service:
            return "Gmail не налаштовано."
        service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()
        return f"Лист {message_id} архівовано."
    except Exception as e:
        return f"Помилка архівації: {e}"


def _get_gmail_service():
    """Отримати Gmail API service."""
    try:
        import os

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = os.environ.get("GOOGLE_TOKEN_PATH", "")
        if not token_path or not os.path.exists(token_path):
            return None

        creds = Credentials.from_authorized_user_file(token_path)
        return build("gmail", "v1", credentials=creds)
    except ImportError:
        return None
    except Exception:
        return None


def _extract_body(payload: dict) -> str:
    """Витягнути тіло листа."""
    import base64

    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    return "(не вдалося прочитати тіло листа)"


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="gmail_list",
            description="List recent emails from Gmail inbox.",
            category="integration",
            handler=gmail_list,
            input_schema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Max emails to return (default 10)",
                    },
                    "query": {"type": "string", "description": "Gmail search query (optional)"},
                },
            },
            tags=["gmail", "email"],
        )
    )

    registry.register(
        ToolDefinition(
            name="gmail_read",
            description="Read a specific email by message ID.",
            category="integration",
            handler=gmail_read,
            input_schema={
                "type": "object",
                "required": ["message_id"],
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                },
            },
            tags=["gmail", "email"],
        )
    )

    registry.register(
        ToolDefinition(
            name="send_email",
            description="Send an email via Gmail. Requires user approval before sending.",
            category="integration",
            handler=send_email,
            input_schema={
                "type": "object",
                "required": ["to", "subject", "body"],
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                },
            },
            requires_approval=True,
            tags=["gmail", "email"],
        )
    )

    registry.register(
        ToolDefinition(
            name="gmail_search",
            description="Search emails in Gmail.",
            category="integration",
            handler=gmail_search,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer"},
                },
            },
            tags=["gmail", "email"],
        )
    )
