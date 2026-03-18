"""Posipaka — Google Workspace Integration (Sheets + Docs)."""

from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger

from posipaka.security.injection import sanitize_external_content

# Google Workspace tools require google-api-python-client
# pip install posipaka[google]

_NOT_CONFIGURED = (
    "Google Workspace не налаштовано. Встановіть GOOGLE_TOKEN_PATH та GOOGLE_CREDENTIALS_PATH."
)


def _get_sheets_service():
    """Отримати Google Sheets API service."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = os.environ.get("GOOGLE_TOKEN_PATH", "")
        if not token_path or not os.path.exists(token_path):
            return None

        creds = Credentials.from_authorized_user_file(token_path)
        return build("sheets", "v4", credentials=creds)
    except ImportError:
        return None
    except Exception:
        return None


def _get_docs_service():
    """Отримати Google Docs API service."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = os.environ.get("GOOGLE_TOKEN_PATH", "")
        if not token_path or not os.path.exists(token_path):
            return None

        creds = Credentials.from_authorized_user_file(token_path)
        return build("docs", "v1", credentials=creds)
    except ImportError:
        return None
    except Exception:
        return None


def _get_drive_service():
    """Отримати Google Drive API service (для створення файлів)."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = os.environ.get("GOOGLE_TOKEN_PATH", "")
        if not token_path or not os.path.exists(token_path):
            return None

        creds = Credentials.from_authorized_user_file(token_path)
        return build("drive", "v3", credentials=creds)
    except ImportError:
        return None
    except Exception:
        return None


async def google_sheets_read(
    spreadsheet_id: str,
    range_name: str = "Sheet1!A1:Z100",
) -> str:
    """Прочитати дані з Google Sheets."""
    try:
        service = _get_sheets_service()
        if not service:
            return _NOT_CONFIGURED

        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_name)
            .execute()
        )
        values = result.get("values", [])

        if not values:
            return f"Таблиця порожня (range: {range_name})."

        lines = []
        for i, row in enumerate(values):
            cells = " | ".join(str(c) for c in row)
            lines.append(f"Row {i + 1}: {cells}")

        content = "\n".join(lines)
        return sanitize_external_content(content, source="google_sheets")
    except Exception as e:
        logger.error(f"Sheets read error: {e}")
        return f"Помилка читання таблиці: {e}"


async def google_sheets_write(
    spreadsheet_id: str,
    range_name: str,
    values: str,
) -> str:
    """Записати дані в Google Sheets (requires approval).

    Args:
        spreadsheet_id: ID таблиці.
        range_name: Діапазон (напр. Sheet1!A1:C3).
        values: JSON-рядок з масивом рядків, напр.
                '[["a","b"],["c","d"]]'.
    """
    try:
        service = _get_sheets_service()
        if not service:
            return _NOT_CONFIGURED

        parsed_values = json.loads(values)
        if not isinstance(parsed_values, list):
            return "values має бути JSON-масивом рядків."

        body = {"values": parsed_values}
        result = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body,
            )
            .execute()
        )
        updated = result.get("updatedCells", 0)
        return f"Записано {updated} комірок в {range_name}."
    except json.JSONDecodeError:
        return "Невалідний JSON у values."
    except Exception as e:
        logger.error(f"Sheets write error: {e}")
        return f"Помилка запису в таблицю: {e}"


async def google_sheets_create(title: str) -> str:
    """Створити нову Google Sheets таблицю (requires approval)."""
    try:
        service = _get_sheets_service()
        if not service:
            return _NOT_CONFIGURED

        spreadsheet = {"properties": {"title": title}}
        result = (
            service.spreadsheets()
            .create(body=spreadsheet, fields="spreadsheetId,spreadsheetUrl")
            .execute()
        )
        sid = result.get("spreadsheetId", "")
        url = result.get(
            "spreadsheetUrl",
            f"https://docs.google.com/spreadsheets/d/{sid}",
        )
        return f"Таблицю створено: {title}\nID: {sid}\nURL: {url}"
    except Exception as e:
        logger.error(f"Sheets create error: {e}")
        return f"Помилка створення таблиці: {e}"


async def google_docs_read(document_id: str) -> str:
    """Прочитати вміст Google Docs документа."""
    try:
        service = _get_docs_service()
        if not service:
            return _NOT_CONFIGURED

        doc = service.documents().get(documentId=document_id).execute()
        title = doc.get("title", "(без назви)")
        body = doc.get("body", {})
        content_parts: list[str] = []

        for element in body.get("content", []):
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for el in paragraph.get("elements", []):
                text_run = el.get("textRun")
                if text_run:
                    content_parts.append(text_run.get("content", ""))

        text = "".join(content_parts).strip()
        if not text:
            text = "(документ порожній)"

        result = f"Документ: {title}\n\n{text}"
        return sanitize_external_content(result, source="google_docs")
    except Exception as e:
        logger.error(f"Docs read error: {e}")
        return f"Помилка читання документа: {e}"


async def google_docs_create(
    title: str,
    content: str = "",
) -> str:
    """Створити новий Google Docs документ (requires approval)."""
    try:
        service = _get_docs_service()
        if not service:
            return _NOT_CONFIGURED

        doc = service.documents().create(body={"title": title}).execute()
        doc_id = doc.get("documentId", "")

        if content:
            requests = [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": content,
                    }
                }
            ]
            service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()

        url = f"https://docs.google.com/document/d/{doc_id}"
        return f"Документ створено: {title}\nID: {doc_id}\nURL: {url}"
    except Exception as e:
        logger.error(f"Docs create error: {e}")
        return f"Помилка створення документа: {e}"


def register(registry: Any) -> None:
    """Register Google Workspace tools."""
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="google_sheets_read",
            description=("Read data from a Google Sheets spreadsheet."),
            category="integration",
            handler=google_sheets_read,
            input_schema={
                "type": "object",
                "required": ["spreadsheet_id"],
                "properties": {
                    "spreadsheet_id": {
                        "type": "string",
                        "description": "Google Sheets spreadsheet ID",
                    },
                    "range_name": {
                        "type": "string",
                        "description": ("Cell range, e.g. Sheet1!A1:Z100"),
                    },
                },
            },
            tags=["google", "sheets", "spreadsheet"],
        )
    )

    registry.register(
        ToolDefinition(
            name="google_sheets_write",
            description=("Write data to a Google Sheets spreadsheet. Requires user approval."),
            category="integration",
            handler=google_sheets_write,
            input_schema={
                "type": "object",
                "required": [
                    "spreadsheet_id",
                    "range_name",
                    "values",
                ],
                "properties": {
                    "spreadsheet_id": {
                        "type": "string",
                        "description": "Google Sheets spreadsheet ID",
                    },
                    "range_name": {
                        "type": "string",
                        "description": ("Target range, e.g. Sheet1!A1:C3"),
                    },
                    "values": {
                        "type": "string",
                        "description": ('JSON array of rows, e.g. \'[["a","b"],["c","d"]]\''),
                    },
                },
            },
            requires_approval=True,
            tags=["google", "sheets", "spreadsheet"],
        )
    )

    registry.register(
        ToolDefinition(
            name="google_sheets_create",
            description=("Create a new Google Sheets spreadsheet. Requires user approval."),
            category="integration",
            handler=google_sheets_create,
            input_schema={
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {
                        "type": "string",
                        "description": ("Title for the new spreadsheet"),
                    },
                },
            },
            requires_approval=True,
            tags=["google", "sheets", "spreadsheet"],
        )
    )

    registry.register(
        ToolDefinition(
            name="google_docs_read",
            description=("Read content from a Google Docs document."),
            category="integration",
            handler=google_docs_read,
            input_schema={
                "type": "object",
                "required": ["document_id"],
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Google Docs document ID",
                    },
                },
            },
            tags=["google", "docs", "document"],
        )
    )

    registry.register(
        ToolDefinition(
            name="google_docs_create",
            description=("Create a new Google Docs document. Requires user approval."),
            category="integration",
            handler=google_docs_create,
            input_schema={
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {
                        "type": "string",
                        "description": ("Title for the new document"),
                    },
                    "content": {
                        "type": "string",
                        "description": ("Initial text content (optional)"),
                    },
                },
            },
            requires_approval=True,
            tags=["google", "docs", "document"],
        )
    )
