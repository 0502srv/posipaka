"""Messenger-based onboarding — налаштування через Telegram inline кнопки.

Секція 10.3 MASTER.md: /setup команда при першому запуску.
Покрокове налаштування через кнопки inline keyboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import yaml
from loguru import logger

from posipaka.config.defaults import (
    MEMORY_DEFAULT_CONTENT,
    SOUL_DEFAULT_CONTENT,
    USER_DEFAULT_CONTENT,
)

if TYPE_CHECKING:
    from posipaka.config.settings import Settings


class MessengerSetupState:
    """Per-user setup state for messenger onboarding."""

    def __init__(self) -> None:
        self.step: int = 0
        self.config: dict[str, Any] = {}
        self.awaiting_input: str | None = None  # field name awaiting free-text input


class MessengerSetupWizard:
    """Messenger-based setup wizard — works through Telegram inline buttons.

    Тригер: /setup command або перше повідомлення від нового користувача.
    Процес через inline keyboard buttons + text input.
    """

    def __init__(self, settings: Settings, data_dir: Path | None = None) -> None:
        self.settings = settings
        self.data_dir = data_dir or Path.home() / ".posipaka"
        self._states: dict[str, MessengerSetupState] = {}

    def get_state(self, user_id: str) -> MessengerSetupState:
        """Get or create setup state for user."""
        if user_id not in self._states:
            self._states[user_id] = MessengerSetupState()
        return self._states[user_id]

    def is_in_setup(self, user_id: str) -> bool:
        """Check if user is currently in setup flow."""
        return user_id in self._states and self._states[user_id].step > 0

    def cancel(self, user_id: str) -> None:
        """Cancel setup for user."""
        self._states.pop(user_id, None)

    # ─── Main Entry Point ─────────────────────────────────────────

    def start_setup(self, user_id: str) -> dict[str, Any]:
        """Start setup flow. Returns message + keyboard."""
        state = self.get_state(user_id)
        state.step = 1
        state.config = {}
        return self._render_step(state)

    def handle_callback(self, user_id: str, callback_data: str) -> dict[str, Any]:
        """Handle inline button callback. Returns message + keyboard."""
        state = self.get_state(user_id)

        if callback_data == "setup_cancel":
            self.cancel(user_id)
            return {"text": "Налаштування скасовано.", "keyboard": None}

        if callback_data == "setup_skip":
            state.step += 1
            return self._render_step(state)

        return self._process_callback(state, callback_data)

    def handle_text_input(self, user_id: str, text: str) -> dict[str, Any]:
        """Handle free-text input during setup. Returns message + keyboard."""
        state = self.get_state(user_id)

        if not state.awaiting_input:
            return {"text": "Використайте кнопки для навігації.", "keyboard": None}

        return self._process_text_input(state, text)

    # ─── Step Rendering ────────────────────────────────────────────

    def _render_step(self, state: MessengerSetupState) -> dict[str, Any]:
        """Render current step. Returns {text, keyboard}."""
        renderers = {
            1: self._step_welcome,
            2: self._step_llm_provider,
            3: self._step_llm_key,
            4: self._step_integrations,
            5: self._step_agent_name,
            6: self._step_language,
            7: self._step_done,
        }
        renderer = renderers.get(state.step, self._step_done)
        return renderer(state)

    def _step_welcome(self, state: MessengerSetupState) -> dict[str, Any]:
        return {
            "text": (
                "Привіт! Я Posipaka, ваш AI-агент.\n"
                "Схоже, це наш перший раз. Давайте налаштуємось!\n\n"
                "Це займе 2-3 хвилини."
            ),
            "keyboard": [
                [("Почати налаштування", "setup_step_2")],
                [("Пропустити", "setup_skip")],
            ],
        }

    def _step_llm_provider(self, state: MessengerSetupState) -> dict[str, Any]:
        return {
            "text": (
                "Крок 1/5: AI модель\n\n"
                "LLM (Large Language Model) — це AI-мозок агента.\n"
                "Оберіть провайдера:"
            ),
            "keyboard": [
                [("Anthropic Claude (рекомендовано)", "setup_llm_anthropic")],
                [("OpenAI GPT-4o", "setup_llm_openai")],
                [("Ollama (локально)", "setup_llm_ollama")],
                [("Скасувати", "setup_cancel")],
            ],
        }

    def _step_llm_key(self, state: MessengerSetupState) -> dict[str, Any]:
        provider = state.config.get("llm_provider", "anthropic")

        if provider == "ollama":
            state.config["llm_api_key"] = ""
            state.config["llm_model"] = "llama3"
            state.step = 4
            return self._render_step(state)

        provider_name = "Anthropic" if provider == "anthropic" else "OpenAI"
        site = "console.anthropic.com" if provider == "anthropic" else "platform.openai.com"

        state.awaiting_input = "llm_api_key"
        return {
            "text": (
                f"Крок 2/5: API ключ для {provider_name}\n\n"
                f"Отримайте ключ на: {site}\n\n"
                "Надішліть ключ текстовим повідомленням.\n"
                "(Він зберігається тільки на вашому сервері)"
            ),
            "keyboard": [
                [("Пропустити", "setup_skip")],
                [("Скасувати", "setup_cancel")],
            ],
        }

    def _step_integrations(self, state: MessengerSetupState) -> dict[str, Any]:
        return {
            "text": (
                "Крок 3/5: Що я маю вміти?\n\n"
                "Виберіть інтеграції (натискайте кілька, потім 'Далі'):"
            ),
            "keyboard": [
                [("Gmail", "setup_int_gmail"), ("Календар", "setup_int_calendar")],
                [("Браузер", "setup_int_browser"), ("Shell", "setup_int_shell")],
                [("GitHub", "setup_int_github"), ("Погода", "setup_int_weather")],
                [("Далі", "setup_step_5")],
                [("Скасувати", "setup_cancel")],
            ],
        }

    def _step_agent_name(self, state: MessengerSetupState) -> dict[str, Any]:
        state.awaiting_input = "soul_name"
        return {
            "text": (
                "Крок 4/5: Як мене називати?\n\n"
                "Надішліть ім'я агента або натисніть кнопку:"
            ),
            "keyboard": [
                [("Posipaka (за замовчуванням)", "setup_name_default")],
                [("Скасувати", "setup_cancel")],
            ],
        }

    def _step_language(self, state: MessengerSetupState) -> dict[str, Any]:
        return {
            "text": "Крок 5/5: Мова відповідей",
            "keyboard": [
                [("Авто (визначати з повідомлення)", "setup_lang_auto")],
                [("Українська", "setup_lang_uk")],
                [("English", "setup_lang_en")],
                [("Скасувати", "setup_cancel")],
            ],
        }

    def _step_done(self, state: MessengerSetupState) -> dict[str, Any]:
        # Save config
        self._save_config(state)

        integrations = state.config.get("integrations", [])
        int_text = ""
        if integrations:
            int_text = "\n".join(f"  - {i}" for i in integrations)
            int_text = f"\nІнтеграції:\n{int_text}\n"

        # Cleanup
        user_id = None
        for uid, s in self._states.items():
            if s is state:
                user_id = uid
                break
        if user_id:
            self._states.pop(user_id, None)

        return {
            "text": (
                "Налаштування завершено!\n\n"
                f"Ім'я: {state.config.get('soul_name', 'Posipaka')}\n"
                f"AI: {state.config.get('llm_provider', 'anthropic')}\n"
                f"Мова: {state.config.get('soul_language', 'auto')}\n"
                f"{int_text}\n"
                'Спробуйте: "Покажи мої останні листи"\n'
                'або: "Яка погода в Києві?"'
            ),
            "keyboard": None,
        }

    # ─── Callback Processing ──────────────────────────────────────

    def _process_callback(self, state: MessengerSetupState, data: str) -> dict[str, Any]:
        # Step navigation
        if data.startswith("setup_step_"):
            step = int(data.split("_")[-1])
            state.step = step
            state.awaiting_input = None
            return self._render_step(state)

        # LLM provider
        if data.startswith("setup_llm_"):
            provider = data.replace("setup_llm_", "")
            state.config["llm_provider"] = provider
            if provider == "anthropic":
                state.config["llm_model"] = "claude-sonnet-4-20250514"
            elif provider == "openai":
                state.config["llm_model"] = "gpt-4o-mini"
            else:
                state.config["llm_model"] = "llama3"
            state.step = 3
            return self._render_step(state)

        # Integrations toggle
        if data.startswith("setup_int_"):
            integration = data.replace("setup_int_", "")
            ints = state.config.setdefault("integrations", [])
            if integration in ints:
                ints.remove(integration)
            else:
                ints.append(integration)
            # Re-render same step with updated selection
            selected = ", ".join(ints) if ints else "нічого"
            result = self._step_integrations(state)
            result["text"] += f"\n\nВибрано: {selected}"
            return result

        # Agent name default
        if data == "setup_name_default":
            state.config["soul_name"] = "Posipaka"
            state.awaiting_input = None
            state.step = 6
            return self._render_step(state)

        # Language
        if data.startswith("setup_lang_"):
            lang = data.replace("setup_lang_", "")
            state.config["soul_language"] = lang
            state.step = 7
            return self._render_step(state)

        return {"text": "Невідома команда.", "keyboard": None}

    def _process_text_input(self, state: MessengerSetupState, text: str) -> dict[str, Any]:
        field = state.awaiting_input
        state.awaiting_input = None

        if field == "llm_api_key":
            state.config["llm_api_key"] = text.strip()
            # Test the key
            test_result = self._test_llm_key(
                state.config.get("llm_provider", "anthropic"),
                text.strip(),
            )
            state.step = 4
            next_step = self._render_step(state)
            next_step["text"] = f"{test_result}\n\n{next_step['text']}"
            return next_step

        if field == "soul_name":
            state.config["soul_name"] = text.strip() or "Posipaka"
            state.step = 6
            return self._render_step(state)

        return {"text": "Дані збережено.", "keyboard": None}

    # ─── Helpers ───────────────────────────────────────────────────

    def _test_llm_key(self, provider: str, api_key: str) -> str:
        """Test LLM key. Returns status text."""
        try:
            if provider == "anthropic":
                resp = httpx.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    return "Підключення успішне! Claude готовий до роботи."
                return f"Помилка підключення (HTTP {resp.status_code}). Перевірте ключ пізніше."
            elif provider == "openai":
                resp = httpx.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return "OpenAI підключено успішно!"
                return f"Помилка підключення (HTTP {resp.status_code})."
        except Exception as e:
            return f"Помилка підключення: {e}"
        return "Ключ збережено."

    def _save_config(self, state: MessengerSetupState) -> None:
        """Save setup config to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for subdir in ("logs", "skills", "chroma"):
            (self.data_dir / subdir).mkdir(exist_ok=True)

        config = state.config

        # .env
        env_lines = [
            f"LLM_PROVIDER={config.get('llm_provider', 'anthropic')}",
            f"LLM_MODEL={config.get('llm_model', 'claude-sonnet-4-20250514')}",
        ]
        if config.get("llm_api_key"):
            env_lines.append(f"LLM_API_KEY={config['llm_api_key']}")

        env_lines.append(f"SOUL_NAME={config.get('soul_name', 'Posipaka')}")
        env_lines.append(f"SOUL_LANGUAGE={config.get('soul_language', 'auto')}")
        env_lines.append("SOUL_TIMEZONE=Europe/Kyiv")

        # Preserve existing telegram token if set
        if self.settings.telegram.token.get_secret_value():
            env_lines.append(
                f"TELEGRAM_TOKEN={self.settings.telegram.token.get_secret_value()}"
            )
            env_lines.append(f"TELEGRAM_OWNER_ID={self.settings.telegram.owner_id}")

        env_path = self.data_dir / ".env"
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        env_path.chmod(0o600)

        # Default files
        for path, content in [
            (self.data_dir / "SOUL.md", SOUL_DEFAULT_CONTENT),
            (self.data_dir / "USER.md", USER_DEFAULT_CONTENT),
            (self.data_dir / "MEMORY.md", MEMORY_DEFAULT_CONTENT),
        ]:
            if not path.exists():
                path.write_text(content, encoding="utf-8")

        # config.yaml
        safe_config = {
            k: v for k, v in config.items()
            if "key" not in k and "token" not in k
        }
        config_yaml = self.data_dir / "config.yaml"
        config_yaml.write_text(yaml.dump(safe_config, allow_unicode=True), encoding="utf-8")

        logger.info(f"Messenger wizard: config saved to {self.data_dir}")


def build_telegram_keyboard(keyboard_data: list[list[tuple[str, str]]] | None):
    """Convert keyboard data to telegram InlineKeyboardMarkup.

    Args:
        keyboard_data: List of rows, each row is list of (text, callback_data) tuples.

    Returns:
        InlineKeyboardMarkup or None.
    """
    if not keyboard_data:
        return None

    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    except ImportError:
        return None

    rows = []
    for row in keyboard_data:
        buttons = [
            InlineKeyboardButton(text=text, callback_data=data)
            for text, data in row
        ]
        rows.append(buttons)
    return InlineKeyboardMarkup(rows)
