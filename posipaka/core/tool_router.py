"""ToolRouter — smart tool filtering for weak and strong models.

Зменшує кількість tools що передаються до LLM на основі
keyword-matching запиту користувача. Слабкі моделі працюють
надійніше з 2-3 tools замість 20+.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger

# Mapping: keyword patterns → relevant tool names
# Порядок має значення — перша відповідність перемагає
_TOOL_ROUTES: list[tuple[re.Pattern, list[str]]] = [
    # Weather
    (
        re.compile(
            r"погод|прогноз|температур|дощ|сніг|вітер|weather|forecast|rain|snow",
            re.IGNORECASE,
        ),
        ["get_weather", "get_forecast"],
    ),
    # Crypto
    (
        re.compile(
            r"біткоїн|bitcoin|btc|eth|крипт|crypto|курс.*монет|"
            r"ethereum|solana|dogecoin|ціна.*coin",
            re.IGNORECASE,
        ),
        ["get_crypto_price", "get_crypto_chart"],
    ),
    # News
    (
        re.compile(
            r"новин|news|headline|заголовк|що нового|що відбува",
            re.IGNORECASE,
        ),
        ["get_news", "get_top_headlines"],
    ),
    # Knowledge / informational queries
    (
        re.compile(
            r"розкажи|розповідь|розповісти|опиши|описати|"
            r"що таке|хто так|що відомо|що знаєш|"
            r"історі[яю]|факти про|інформаці[яю] про|"
            r"tell me about|describe|explain|what is|who is",
            re.IGNORECASE,
        ),
        ["wikipedia_search", "wikipedia_summary", "web_search", "web_fetch"],
    ),
    # Web search
    (
        re.compile(
            r"знайди|пошук|search|google|шукай|загугли|"
            r"wiki|вікіпед",
            re.IGNORECASE,
        ),
        ["web_search", "web_fetch", "wikipedia_search", "wikipedia_summary"],
    ),
    # Files / shell
    (
        re.compile(
            r"файл|file|директор|director|папк|folder|"
            r"виконай|execute|shell|terminal|команд",
            re.IGNORECASE,
        ),
        ["shell_exec", "python_exec", "read_file", "write_file", "list_directory"],
    ),
    # Documents
    (
        re.compile(
            r"pdf|docx|csv|документ|document|генеруй.*файл|створи.*файл",
            re.IGNORECASE,
        ),
        ["generate_pdf", "generate_docx", "generate_csv"],
    ),
    # Gmail (if configured)
    (
        re.compile(r"пошт|email|mail|gmail|лист|inbox", re.IGNORECASE),
        ["gmail_list", "gmail_read", "send_email", "gmail_search"],
    ),
    # Calendar (if configured)
    (
        re.compile(
            r"календар|calendar|подія|event|зустріч|meeting|розклад|schedule",
            re.IGNORECASE,
        ),
        ["calendar_list", "calendar_create", "delete_event", "calendar_free_slots"],
    ),
    # GitHub (if configured)
    (
        re.compile(r"github|репозитор|repo|pull.?request|issue|коміт", re.IGNORECASE),
        [
            "github_list_repos",
            "github_create_issue",
            "github_list_prs",
            "github_get_file",
        ],
    ),
]


@dataclass
class ToolRouteResult:
    """Результат routing."""

    tools: list[dict]  # Filtered tool schemas
    tool_choice: str | dict | None  # "auto", "required", or specific tool
    confident: bool  # True if router is confident tools are needed


def route_tools(
    query: str,
    all_schemas: list[dict],
    provider: str = "mistral",
) -> ToolRouteResult:
    """Filter tools based on user query.

    For weak models: returns only relevant tools (2-5) + tool_choice hint.
    For strong models (anthropic): returns all tools, no filtering.
    """
    # Strong models handle many tools well — no filtering needed
    if provider == "anthropic":
        return ToolRouteResult(tools=all_schemas, tool_choice=None, confident=False)

    # Build name→schema lookup
    schema_map: dict[str, dict] = {}
    for s in all_schemas:
        name = s.get("function", {}).get("name") or s.get("name", "")
        if name:
            schema_map[name] = s

    # Match query against routes
    matched_names: list[str] = []
    for pattern, tool_names in _TOOL_ROUTES:
        if pattern.search(query):
            matched_names.extend(tool_names)
            break  # First match wins

    if not matched_names:
        # No specific match — return all tools with "auto"
        return ToolRouteResult(tools=all_schemas, tool_choice="auto", confident=False)

    # Filter to only matched tools that are actually registered
    filtered = [schema_map[n] for n in matched_names if n in schema_map]

    if not filtered:
        return ToolRouteResult(tools=all_schemas, tool_choice="auto", confident=False)

    logger.debug(
        f"ToolRouter: matched {len(filtered)} tools for query "
        f"(from {len(all_schemas)} total)"
    )

    # Force tool call when few tools matched — even weak models handle this
    tool_choice: str | dict = "required" if len(filtered) <= 5 else "auto"

    return ToolRouteResult(
        tools=filtered,
        tool_choice=tool_choice,
        confident=True,
    )
