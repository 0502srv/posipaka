"""LLMClient — абстракція над LLM провайдерами (Anthropic / OpenAI / Ollama + OpenAI-сумісні)."""

from __future__ import annotations

from typing import Any

from loguru import logger

from posipaka.config.settings import Settings

_PROVIDER_BASE_URLS: dict[str, str] = {
    "mistral": "https://api.mistral.ai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "xai": "https://api.x.ai/v1",
}


class LLMClient:
    """Абстракція над LLM провайдерами (Anthropic / OpenAI / Ollama + OpenAI-сумісні)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._primary_client: Any = None
        self._fallback_client: Any = None

    def reinitialize(self) -> None:
        """Скинути кешовані клієнти — наступний complete() створить нових."""
        self._primary_client = None
        self._fallback_client = None
        logger.info("LLM client reset — will reinitialize on next call")

    def _init_clients(self) -> None:
        provider = self._settings.llm.provider
        api_key = self._settings.llm.api_key.get_secret_value()

        if provider == "anthropic" and api_key:
            try:
                import anthropic

                self._primary_client = anthropic.AsyncAnthropic(api_key=api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
        elif provider == "openai" and api_key:
            try:
                import openai

                self._primary_client = openai.AsyncOpenAI(api_key=api_key)
            except ImportError:
                logger.warning("openai package not installed")
        elif provider == "ollama":
            try:
                import openai

                base_url = self._settings.llm.base_url or "http://localhost:11434/v1"
                self._primary_client = openai.AsyncOpenAI(base_url=base_url, api_key="ollama")
            except ImportError:
                logger.warning("openai package not installed")
        elif provider in _PROVIDER_BASE_URLS and api_key:
            try:
                import openai

                self._primary_client = openai.AsyncOpenAI(
                    base_url=_PROVIDER_BASE_URLS[provider],
                    api_key=api_key,
                )
            except ImportError:
                logger.warning("openai package not installed")

    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
        """
        Виклик LLM.

        Returns: {content, stop_reason, tool_use, usage}
        """
        if self._primary_client is None:
            self._init_clients()

        provider = self._settings.llm.provider
        model = model or self._settings.llm.model

        try:
            if provider == "anthropic":
                return await self._call_anthropic(system, messages, tools, model)
            else:
                return await self._call_openai(system, messages, tools, model, tool_choice)
        except Exception as e:
            logger.error(f"LLM primary error: {e}")
            # Try fallback
            if self._settings.llm.fallback_provider:
                logger.info("Switching to fallback LLM")
                try:
                    return await self._call_fallback(system, messages, tools)
                except Exception as fe:
                    logger.error(f"LLM fallback error: {fe}")
            raise

    async def _call_anthropic(
        self, system: str, messages: list[dict], tools: list[dict] | None, model: str
    ) -> dict:
        if self._primary_client is None:
            raise RuntimeError("Anthropic client not initialized")

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self._settings.llm.max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._primary_client.messages.create(**kwargs)

        content = ""
        tool_use: list[dict] = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_use.append(
                    {
                        "name": block.name,
                        "input": block.input,
                        "id": block.id,
                    }
                )

        return {
            "content": content,
            "stop_reason": response.stop_reason,
            "tool_use": tool_use,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

    async def _call_openai(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
        tool_choice: str | dict | None = None,
    ) -> dict:
        if self._primary_client is None:
            raise RuntimeError("OpenAI client not initialized")

        oai_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        prev_role = "system"
        for msg in messages:
            role = msg["role"]
            # Tool-related messages pass through as-is (structured format)
            if role == "tool" or "tool_calls" in msg:
                oai_messages.append(msg)
                prev_role = role
                continue
            # Merge consecutive same-role messages (Mistral requires alternation)
            if role == prev_role and oai_messages:
                oai_messages[-1]["content"] += "\n" + msg["content"]
            else:
                oai_messages.append({"role": role, "content": msg["content"]})
                prev_role = role
        # Ensure last message is user or tool (required by Mistral)
        while (
            len(oai_messages) > 1
            and oai_messages[-1]["role"] == "assistant"
            and "tool_calls" not in oai_messages[-1]
        ):
            oai_messages.pop()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": oai_messages,
            "max_tokens": self._settings.llm.max_tokens,
        }
        if tools:
            kwargs["tools"] = [
                t
                if "type" in t
                else {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]
            if tool_choice:
                kwargs["tool_choice"] = tool_choice

        response = await self._primary_client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        tool_use: list[dict] = []
        if choice.message.tool_calls:
            import json

            for tc in choice.message.tool_calls:
                tool_use.append(
                    {
                        "name": tc.function.name,
                        "input": json.loads(tc.function.arguments),
                        "id": tc.id,
                    }
                )

        return {
            "content": choice.message.content or "",
            "stop_reason": "tool_use" if tool_use else "end_turn",
            "tool_use": tool_use,
            "usage": {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }

    async def _call_fallback(
        self, system: str, messages: list[dict], tools: list[dict] | None
    ) -> dict:
        fb_provider = self._settings.llm.fallback_provider
        fb_model = self._settings.llm.fallback_model
        fb_key = self._settings.llm.fallback_api_key.get_secret_value()

        if fb_provider == "anthropic" and fb_key:
            import anthropic

            old_client = self._primary_client
            self._primary_client = anthropic.AsyncAnthropic(api_key=fb_key)
            try:
                return await self._call_anthropic(system, messages, tools, fb_model)
            finally:
                self._primary_client = old_client
        elif fb_provider == "openai" and fb_key:
            import openai

            old_client = self._primary_client
            self._primary_client = openai.AsyncOpenAI(api_key=fb_key)
            try:
                return await self._call_openai(system, messages, tools, fb_model)
            finally:
                self._primary_client = old_client
        elif fb_provider == "ollama":
            import openai

            old_client = self._primary_client
            self._primary_client = openai.AsyncOpenAI(
                base_url="http://localhost:11434/v1", api_key="ollama"
            )
            try:
                return await self._call_openai(system, messages, tools, fb_model)
            finally:
                self._primary_client = old_client
        elif fb_provider in _PROVIDER_BASE_URLS and fb_key:
            import openai

            old_client = self._primary_client
            self._primary_client = openai.AsyncOpenAI(
                base_url=_PROVIDER_BASE_URLS[fb_provider],
                api_key=fb_key,
            )
            try:
                return await self._call_openai(system, messages, tools, fb_model)
            finally:
                self._primary_client = old_client

        raise RuntimeError("No fallback LLM available")
