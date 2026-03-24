"""ToolRouter — fully automatic routing via LLM-generated keyword cache.

При першому старті (або при зміні tools) — один LLM call генерує
UA/RU/EN keywords для кожного tool. Кеш зберігається на диск.
Routing працює миттєво через keyword matching.

Для сильних моделей (Anthropic) — routing не потрібен, всі tools.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

_CACHE_FILE = Path.home() / ".posipaka" / "tool_keywords_cache.json"
_MIN_WORD_LEN = 3


def _extract_words(text: str) -> list[str]:
    """Extract words ≥3 chars from text."""
    return [
        w
        for w in re.findall(r"[a-zA-Zа-яА-ЯіІїЇєЄґҐ'ʼ]{3,}", text.lower())
        if len(w) >= _MIN_WORD_LEN
    ]


def _tools_hash(schemas: list[dict]) -> str:
    """Hash of tool names — changes when tools added/removed."""
    names = sorted(s.get("function", {}).get("name") or s.get("name", "") for s in schemas)
    return hashlib.md5("|".join(names).encode()).hexdigest()[:12]


def _load_cache() -> dict | None:
    """Load cached keywords from disk."""
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_cache(data: dict) -> None:
    """Save keywords cache to disk."""
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _generate_keywords_prompt(schemas: list[dict]) -> str:
    """Build prompt for LLM to generate keywords."""
    tool_list = []
    for s in schemas:
        func = s.get("function", {})
        name = func.get("name") or s.get("name", "")
        desc = func.get("description") or s.get("description", "")
        if name and desc:
            tool_list.append(f"- {name}: {desc}")

    tools_text = "\n".join(tool_list)
    return (
        "For each tool below, generate 5-10 keywords in Ukrainian and Russian "
        "that a user might say when they need this tool. "
        "Include verb forms, nouns, and common phrases. "
        'Return ONLY valid JSON: {"tool_name": ["keyword1", "keyword2", ...], ...}\n'
        "No markdown, no explanation, just JSON.\n\n"
        f"Tools:\n{tools_text}"
    )


async def generate_keyword_cache(schemas: list[dict], llm_client) -> dict:
    """Generate UA/RU keywords via LLM and cache them."""
    current_hash = _tools_hash(schemas)

    # Check existing cache
    cached = _load_cache()
    if cached and cached.get("hash") == current_hash:
        logger.debug(f"ToolRouter: using cached keywords ({len(cached.get('keywords', {}))} tools)")
        return cached.get("keywords", {})

    # Generate new keywords via LLM
    prompt = _generate_keywords_prompt(schemas)
    logger.info("ToolRouter: generating keyword cache via LLM...")

    try:
        response = await llm_client.complete(
            system="You are a keyword generator. Return only valid JSON.",
            messages=[{"role": "user", "content": prompt}],
            tools=None,
            model=None,
        )
        text = response.get("content", "").strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```" in text:
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()

        keywords_map = json.loads(text)

        # Validate: should be dict of lists
        if not isinstance(keywords_map, dict):
            raise ValueError("Expected dict")

        # Also add EN keywords from descriptions automatically
        for s in schemas:
            func = s.get("function", {})
            name = func.get("name") or s.get("name", "")
            desc = func.get("description") or s.get("description", "")
            if name:
                en_words = _extract_words(f"{name.replace('_', ' ')} {desc}")
                existing = keywords_map.get(name, [])
                combined = list(set(existing + en_words))
                keywords_map[name] = combined

        # Save cache
        cache_data = {"hash": current_hash, "keywords": keywords_map}
        _save_cache(cache_data)
        logger.info(f"ToolRouter: keyword cache generated ({len(keywords_map)} tools)")
        return keywords_map

    except Exception as e:
        logger.warning(f"ToolRouter: LLM keyword generation failed: {e}")
        # Fallback: extract EN keywords from descriptions only
        keywords_map = {}
        for s in schemas:
            func = s.get("function", {})
            name = func.get("name") or s.get("name", "")
            desc = func.get("description") or s.get("description", "")
            if name:
                keywords_map[name] = _extract_words(f"{name.replace('_', ' ')} {desc}")
        cache_data = {"hash": current_hash, "keywords": keywords_map}
        _save_cache(cache_data)
        return keywords_map


class _ToolIndex:
    """Inverted index: keyword → set of tool names."""

    def __init__(self) -> None:
        self._index: dict[str, set[str]] = {}
        self._built = False

    def build_from_keywords(self, keywords_map: dict[str, list[str]]) -> None:
        """Build index from pre-generated keywords map."""
        self._index.clear()
        for tool_name, keywords in keywords_map.items():
            for kw in keywords:
                kw_lower = kw.lower().strip()
                if len(kw_lower) >= _MIN_WORD_LEN:
                    self._index.setdefault(kw_lower, set()).add(tool_name)
        self._built = True
        logger.debug(f"ToolIndex: {len(self._index)} keywords indexed")

    def search(self, query: str, top_k: int = 7) -> list[tuple[str, int]]:
        if not self._built:
            return []

        query_lower = query.lower()
        scores: dict[str, int] = {}

        # Word matching
        for word in _extract_words(query):
            for tool_name in self._index.get(word, set()):
                scores[tool_name] = scores.get(tool_name, 0) + 1

        # Substring matching (for UA stems)
        for keyword, tool_names in self._index.items():
            if len(keyword) >= 4 and keyword in query_lower:
                for tool_name in tool_names:
                    scores[tool_name] = scores.get(tool_name, 0) + 2

        if not scores:
            return []

        return sorted(scores.items(), key=lambda x: -x[1])[:top_k]


_tool_index = _ToolIndex()
_last_schema_hash = ""


@dataclass
class ToolRouteResult:
    tools: list[dict]
    tool_choice: str | dict | None
    confident: bool


async def init_router(schemas: list[dict], llm_client) -> None:
    """Initialize router with LLM-generated keywords. Call once at startup."""
    global _last_schema_hash
    current_hash = _tools_hash(schemas)
    if current_hash == _last_schema_hash:
        return

    keywords_map = await generate_keyword_cache(schemas, llm_client)
    _tool_index.build_from_keywords(keywords_map)
    _last_schema_hash = current_hash


def route_tools(
    query: str,
    all_schemas: list[dict],
    provider: str = "mistral",
) -> ToolRouteResult:
    """Route tools based on cached keyword index."""
    if provider == "anthropic":
        return ToolRouteResult(tools=all_schemas, tool_choice=None, confident=False)

    # If index not built yet — fallback to all tools
    if not _tool_index._built:
        # Try to build from cache file
        cached = _load_cache()
        if cached and cached.get("keywords"):
            _tool_index.build_from_keywords(cached["keywords"])
        else:
            return ToolRouteResult(tools=all_schemas, tool_choice="auto", confident=False)

    schema_map: dict[str, dict] = {}
    for s in all_schemas:
        name = s.get("function", {}).get("name") or s.get("name", "")
        if name:
            schema_map[name] = s

    matches = _tool_index.search(query, top_k=7)

    if not matches:
        return ToolRouteResult(tools=all_schemas, tool_choice="auto", confident=False)

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
