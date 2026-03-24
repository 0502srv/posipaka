"""ToolRouter — hybrid auto-routing: keyword index + UA synonyms.

Автоматично будує keyword index з tool descriptions + tags.
Доповнює UA синонімами з _UA_KEYWORDS для мультимовності.
Не потребує оновлення при додаванні нових EN tools.
UA keywords потрібно додавати тільки для нових КОНЦЕПЦІЙ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger

# UA synonyms → tool names mapping
# Додавати сюди тільки УКРАЇНСЬКІ слова, бо EN витягуються автоматично
_UA_KEYWORDS: dict[str, list[str]] = {
    # Health / Fitness
    "вага": ["log_weight"],
    "зважи": ["log_weight"],
    "кілограм": ["log_weight"],
    "сон": ["log_sleep", "get_garmin_daily"],
    "спав": ["log_sleep", "get_garmin_daily"],
    "виспа": ["log_sleep"],
    "настрій": ["log_mood"],
    "вод": ["log_water"],
    "склянк": ["log_water"],
    "тренуванн": ["log_set", "log_exercise", "health_report"],
    "підхід": ["log_set"],
    "повторенн": ["log_set"],
    "рекорд": ["get_pr"],
    "жим": ["log_set"],
    "тяга": ["log_set"],
    "присід": ["log_set"],
    "підтягуванн": ["log_set"],
    "махи": ["log_set"],
    "розводк": ["log_set"],
    "пульс": ["get_garmin_daily"],
    "годинник": ["get_garmin_daily"],
    "готовність": ["get_garmin_daily"],
    "батарейк": ["get_garmin_daily"],
    "стрес": ["get_garmin_daily"],
    "калорі": ["log_exercise"],
    "звіт": ["health_report"],
    "здоров": ["health_report"],
    # Reminders
    "нагадай": ["set_reminder"],
    "нагадати": ["set_reminder"],
    "нагадуй": ["set_recurring_reminder"],
    "нагадування": ["set_reminder", "list_reminders"],
    "заплануй": ["set_reminder", "set_recurring_reminder"],
    "запланувати": ["set_reminder", "set_recurring_reminder"],
    "щоранку": ["set_recurring_reminder"],
    "щодня": ["set_recurring_reminder"],
    "щотижня": ["set_recurring_reminder"],
    "щогодини": ["set_recurring_reminder"],
    "робочі": ["set_recurring_reminder"],
    "вихідні": ["set_recurring_reminder"],
    "скасуй": ["cancel_reminder"],
    "скасувати": ["cancel_reminder"],
    "відмін": ["cancel_reminder"],
    # Weather
    "погод": ["get_weather", "get_forecast"],
    "прогноз": ["get_weather", "get_forecast"],
    "температур": ["get_weather"],
    "дощ": ["get_weather"],
    "сніг": ["get_weather"],
    "вітер": ["get_weather"],
    # Crypto
    "біткоїн": ["get_crypto_price"],
    "крипт": ["get_crypto_price", "get_crypto_chart"],
    "курс": ["get_crypto_price"],
    # News
    "новин": ["get_news", "get_top_headlines"],
    "заголовк": ["get_news"],
    # Search / Knowledge
    "розкажи": ["web_search", "wikipedia_search"],
    "знайди": ["web_search"],
    "пошук": ["web_search"],
    "шукай": ["web_search"],
    "вікіпед": ["wikipedia_search", "wikipedia_summary"],
    "визначення": ["web_search", "wikipedia_search"],
    "означа": ["web_search", "wikipedia_search"],
    "значить": ["web_search", "wikipedia_search"],
    # Files
    "файл": ["read_file", "write_file", "list_directory"],
    "папк": ["list_directory"],
    "команд": ["shell_exec"],
    # Email
    "пошт": ["gmail_list", "gmail_read", "send_email"],
    "лист": ["gmail_list", "gmail_read", "send_email"],
    # Calendar
    "календар": ["calendar_list", "calendar_create"],
    "зустріч": ["calendar_list", "calendar_create"],
    "подія": ["calendar_list", "calendar_create"],
    "розклад": ["calendar_list"],
    # Notes / Bookmarks
    "нотатк": ["create_note", "list_notes"],
    "запиши": ["create_note"],
    "закладк": ["add_bookmark", "list_bookmarks"],
    # Finance
    "витрат": ["add_expense", "finance_report"],
    "дохід": ["add_income"],
    "фінанс": ["finance_report", "finance_balance"],
    "бюджет": ["finance_report", "finance_balance"],
    # Habits
    "звичк": ["add_habit", "log_habit", "habits_report"],
}


def _extract_keywords(text: str) -> list[str]:
    """Витягнути слова з тексту (≥3 символи)."""
    return re.findall(r"[a-zA-Zа-яА-ЯіІїЇєЄґҐ'ʼ]{3,}", text.lower())


class _ToolIndex:
    """Інвертований індекс: keyword → set of tool names.

    EN keywords витягуються автоматично з tool descriptions.
    UA keywords додаються з _UA_KEYWORDS mapping.
    """

    def __init__(self) -> None:
        self._index: dict[str, set[str]] = {}
        self._built = False

    def build(self, schemas: list[dict]) -> None:
        self._index.clear()

        # 1. Auto-index з EN tool descriptions
        for schema in schemas:
            func = schema.get("function", {})
            name = func.get("name") or schema.get("name", "")
            if not name:
                continue

            desc = func.get("description") or schema.get("description", "")
            params = func.get("parameters", {}) or schema.get("input_schema", {})

            text_parts = [name.replace("_", " "), desc]
            for pinfo in params.get("properties", {}).values():
                text_parts.append(pinfo.get("description", ""))

            for word in _extract_keywords(" ".join(text_parts)):
                if len(word) >= 3:
                    self._index.setdefault(word, set()).add(name)

        # 2. UA keywords з маппінгу
        for keyword, tool_names in _UA_KEYWORDS.items():
            for tool_name in tool_names:
                self._index.setdefault(keyword, set()).add(tool_name)

        self._built = True
        logger.debug(f"ToolIndex: {len(self._index)} keywords")

    def search(self, query: str, top_k: int = 7) -> list[tuple[str, int]]:
        if not self._built:
            return []

        query_lower = query.lower()
        scores: dict[str, int] = {}

        # Keyword matching (exact word)
        for word in _extract_keywords(query):
            for tool_name in self._index.get(word, set()):
                scores[tool_name] = scores.get(tool_name, 0) + 1

        # Substring matching for UA stems (e.g. "нагадуй" matches "нагадуй")
        for keyword, tool_names in self._index.items():
            if len(keyword) >= 4 and keyword in query_lower:
                for tool_name in tool_names:
                    scores[tool_name] = scores.get(tool_name, 0) + 2

        if not scores:
            return []

        return sorted(scores.items(), key=lambda x: -x[1])[:top_k]


_tool_index = _ToolIndex()
_last_schema_count = 0


@dataclass
class ToolRouteResult:
    tools: list[dict]
    tool_choice: str | dict | None
    confident: bool


def route_tools(
    query: str,
    all_schemas: list[dict],
    provider: str = "mistral",
) -> ToolRouteResult:
    """Hybrid auto-routing: keyword index + UA synonyms."""
    global _last_schema_count

    if provider == "anthropic":
        return ToolRouteResult(tools=all_schemas, tool_choice=None, confident=False)

    if len(all_schemas) != _last_schema_count:
        _tool_index.build(all_schemas)
        _last_schema_count = len(all_schemas)

    schema_map: dict[str, dict] = {}
    for s in all_schemas:
        name = s.get("function", {}).get("name") or s.get("name", "")
        if name:
            schema_map[name] = s

    matches = _tool_index.search(query, top_k=7)

    if not matches:
        return ToolRouteResult(tools=all_schemas, tool_choice="auto", confident=False)

    # Adaptive threshold: at least 30% of top score
    top_score = matches[0][1]
    min_score = max(1, top_score // 3)
    relevant = [(n, s) for n, s in matches if s >= min_score]

    matched_names = [n for n, _ in relevant]
    filtered = [schema_map[n] for n in matched_names if n in schema_map]

    if not filtered:
        return ToolRouteResult(tools=all_schemas, tool_choice="auto", confident=False)

    top_name = matched_names[0]
    confident = top_score >= 2

    logger.debug(
        f"ToolRouter: {len(filtered)} tools "
        f"(top: {top_name}={top_score}, total: {len(all_schemas)})"
    )

    if confident and len(filtered) <= 7 and top_name in schema_map:
        tool_choice: str | dict = {
            "type": "function",
            "function": {"name": top_name},
        }
    else:
        tool_choice = "auto"

    return ToolRouteResult(
        tools=filtered,
        tool_choice=tool_choice,
        confident=confident,
    )
