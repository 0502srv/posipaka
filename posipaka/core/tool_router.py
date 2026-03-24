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
    # Reminders
    (
        re.compile(
            r"нагадай|нагадати|нагадування|remind|reminder|"
            r"через.*хвилин|через.*годин|через.*хв|"
            r"о \d{1,2}:\d{2}",
            re.IGNORECASE,
        ),
        ["set_reminder", "list_reminders", "cancel_reminder"],
    ),
    # Knowledge / informational / factual queries — EXPANDED
    (
        re.compile(
            r"розкажи|розповідь|розповісти|опиши|описати|"
            r"що таке|хто так|що відомо|що знаєш|"
            r"історі[яю]|факти про|інформаці[яю] про|"
            r"як працює|як діє|як влаштован|"
            r"порівняй|різниця між|відмінність|"
            r"переваги|недоліки|плюси|мінуси|"
            # Factual questions (expanded)
            r"чому |навіщо |де знаходи|звідки |коли був|"
            r"скільки |яка різниця|який найб|яке найб|"
            r"хто створ|хто винайш|хто написав|"
            r"що означа|що значить|визначення|"
            # Product/medicine/brand questions
            r"що це за |для чого |як приймати|як використовувати|"
            r"інструкці[яю]|склад |побічні|протипоказан|"
            r"ціна |вартість |де купити|"
            # English patterns
            r"tell me about|describe|explain|what is|who is|how does|"
            r"why |where is|when was|how many|how much|"
            r"definition of|meaning of",
            re.IGNORECASE,
        ),
        ["web_search", "wikipedia_search", "wikipedia_summary", "web_fetch"],
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

# Patterns that indicate a factual question requiring web search verification.
# Used as fallback when no specific route matches — adds web_search to tools.
_FACTUAL_FALLBACK_PATTERN = re.compile(
    r"\?$|"  # Ends with question mark
    r"^(що|хто|де|коли|чому|як|скільки|яка?|яке?|які?|чи) ",  # UA question words
    re.IGNORECASE,
)


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
        # Fallback: if query looks like a factual question, add web search tools
        if _FACTUAL_FALLBACK_PATTERN.search(query.strip()):
            web_tools = ["web_search", "wikipedia_search", "wikipedia_summary"]
            filtered = [schema_map[n] for n in web_tools if n in schema_map]
            if filtered:
                logger.debug(
                    f"ToolRouter: factual fallback — adding {len(filtered)} web search tools"
                )
                # Return web tools with "auto" — let model decide if search is needed
                return ToolRouteResult(
                    tools=filtered + all_schemas,
                    tool_choice="auto",
                    confident=False,
                )

        # No specific match — return all tools with "auto"
        return ToolRouteResult(tools=all_schemas, tool_choice="auto", confident=False)

    # Filter to only matched tools that are actually registered
    filtered = [schema_map[n] for n in matched_names if n in schema_map]

    if not filtered:
        return ToolRouteResult(tools=all_schemas, tool_choice="auto", confident=False)

    logger.debug(
        f"ToolRouter: matched {len(filtered)} tools for query (from {len(all_schemas)} total)"
    )

    # Force tool call when few tools matched — even weak models handle this
    tool_choice: str | dict = "required" if len(filtered) <= 5 else "auto"

    return ToolRouteResult(
        tools=filtered,
        tool_choice=tool_choice,
        confident=True,
    )
