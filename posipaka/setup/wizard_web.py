"""Web-based Setup Wizard — налаштування через браузер (htmx + Tailwind).

Автоматично запускається на http://localhost:8080/setup при першому запуску.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml
from loguru import logger

from posipaka.config.defaults import (
    MEMORY_DEFAULT_CONTENT,
    SOUL_DEFAULT_CONTENT,
    USER_DEFAULT_CONTENT,
)


class WebSetupWizard:
    """Web-based setup wizard — generates HTML steps and processes form data."""

    TOTAL_STEPS = 12

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path.home() / ".posipaka"
        self.config: dict[str, Any] = {}

    # ─── Step Rendering ────────────────────────────────────────────

    def render_step(self, step: int, config: dict[str, Any] | None = None) -> str:
        """Render HTML for a specific wizard step."""
        if config:
            self.config.update(config)
        renderers = {
            1: self._render_welcome,
            2: self._render_llm,
            3: self._render_messengers,
            4: self._render_telegram,
            5: self._render_discord,
            6: self._render_slack,
            7: self._render_whatsapp,
            8: self._render_signal,
            9: self._render_google,
            10: self._render_agent,
            11: self._render_summary,
            12: self._render_done,
        }
        renderer = renderers.get(step, self._render_welcome)
        return renderer()

    def _progress_bar(self, step: int) -> str:
        pct = int((step / self.TOTAL_STEPS) * 100)
        return f"""
        <div class="mb-6">
            <div class="flex justify-between text-sm text-gray-400 mb-1">
                <span>Крок {step}/{self.TOTAL_STEPS}</span>
                <span>{pct}%</span>
            </div>
            <div class="w-full bg-gray-700 rounded-full h-2">
                <div class="bg-blue-500 h-2 rounded-full transition-all"
                     style="width: {pct}%"></div>
            </div>
        </div>
        """

    def _step_wrapper(self, step: int, title: str, content: str) -> str:
        return f"""
        <div id="wizard-step" class="bg-gray-800 p-6 rounded-xl shadow-lg max-w-xl mx-auto">
            {self._progress_bar(step)}
            <h2 class="text-xl font-bold mb-4">{title}</h2>
            {content}
        </div>
        """

    def _nav_buttons(self, step: int, next_step: int | None = None) -> str:
        prev_step = step - 1 if step > 1 else None
        next_step or (step + 1)
        buttons = '<div class="flex justify-between mt-6">'
        if prev_step:
            buttons += f"""
            <button hx-get="/setup/step/{prev_step}" hx-target="#wizard-step"
                    hx-swap="outerHTML"
                    class="px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded">
                &larr; Назад
            </button>"""
        else:
            buttons += "<div></div>"
        buttons += """
            <button type="submit"
                    class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded font-bold">
                Далі &rarr;
            </button>
        </div>"""
        return buttons

    def _render_welcome(self) -> str:
        import platform
        import shutil
        import sys

        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        py_ok = sys.version_info >= (3, 11)
        disk = shutil.disk_usage(Path.home())
        disk_gb = disk.free / (1024**3)

        try:
            httpx.get("https://httpbin.org/get", timeout=5)
            net_ok = True
        except Exception:
            net_ok = False

        checks = f"""
        <div class="space-y-2 mb-4">
            <div class="flex items-center gap-2">
                <span>{"&#10003;" if py_ok else "&#10007;"}</span>
                <span>Python {py_ver}</span>
            </div>
            <div class="flex items-center gap-2">
                <span>{"&#10003;" if disk_gb > 1 else "&#9888;"}</span>
                <span>Диск: {disk_gb:.1f} GB вільно</span>
            </div>
            <div class="flex items-center gap-2">
                <span>{"&#10003;" if net_ok else "&#9888;"}</span>
                <span>Мережа: {"доступна" if net_ok else "недоступна"}</span>
            </div>
            <div class="flex items-center gap-2">
                <span>&#8505;</span>
                <span>ОС: {platform.system()} {platform.release()}</span>
            </div>
        </div>
        <form hx-post="/setup/step/2" hx-target="#wizard-step" hx-swap="outerHTML">
            <button type="submit"
                    class="w-full px-4 py-3 bg-blue-600 hover:bg-blue-700 rounded font-bold text-lg">
                Почати налаштування &rarr;
            </button>
        </form>
        """
        return self._step_wrapper(1, "Ласкаво просимо до Posipaka!", checks)

    def _render_llm(self) -> str:
        content = f"""
        <form hx-post="/setup/step/3" hx-target="#wizard-step" hx-swap="outerHTML">
            <label class="block mb-2 text-sm text-gray-300">AI модель</label>
            <select name="llm_provider"
                    class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">
                <option value="mistral" selected>Mistral AI (рекомендовано)</option>
                <option value="anthropic">Anthropic Claude</option>
                <option value="openai">OpenAI GPT-4o</option>
                <option value="ollama">Ollama (локально, безкоштовно)</option>
                <option value="gemini">Google Gemini</option>
                <option value="groq">Groq (швидко)</option>
                <option value="deepseek">DeepSeek</option>
                <option value="xai">xAI Grok</option>
            </select>

            <label class="block mb-2 text-sm text-gray-300">API ключ</label>
            <input type="password" name="llm_api_key" placeholder="sk-ant-..."
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">

            <div id="test-result" class="mb-4"></div>
            <button type="button"
                    hx-post="/setup/test-llm" hx-target="#test-result"
                    hx-include="[name=llm_provider],[name=llm_api_key]"
                    class="px-3 py-1 bg-gray-600 hover:bg-gray-500 rounded text-sm mb-4">
                Перевірити підключення
            </button>

            {self._nav_buttons(2)}
        </form>
        """
        return self._step_wrapper(2, "AI модель", content)

    def _render_messengers(self) -> str:
        content = f"""
        <form hx-post="/setup/step/4" hx-target="#wizard-step" hx-swap="outerHTML">
            <p class="text-gray-400 mb-4">Виберіть месенджери (можна декілька):</p>
            <div class="space-y-3">
                <label class="flex items-center gap-3 p-3 bg-gray-700 rounded cursor-pointer
                              hover:bg-gray-600">
                    <input type="checkbox" name="channels" value="telegram" checked
                           class="w-4 h-4">
                    <span>Telegram (найпростіший старт)</span>
                </label>
                <label class="flex items-center gap-3 p-3 bg-gray-700 rounded cursor-pointer
                              hover:bg-gray-600">
                    <input type="checkbox" name="channels" value="discord" class="w-4 h-4">
                    <span>Discord</span>
                </label>
                <label class="flex items-center gap-3 p-3 bg-gray-700 rounded cursor-pointer
                              hover:bg-gray-600">
                    <input type="checkbox" name="channels" value="slack" class="w-4 h-4">
                    <span>Slack</span>
                </label>
                <label class="flex items-center gap-3 p-3 bg-gray-700 rounded cursor-pointer
                              hover:bg-gray-600">
                    <input type="checkbox" name="channels" value="whatsapp" class="w-4 h-4">
                    <span>WhatsApp</span>
                </label>
                <label class="flex items-center gap-3 p-3 bg-gray-700 rounded cursor-pointer
                              hover:bg-gray-600">
                    <input type="checkbox" name="channels" value="signal" class="w-4 h-4">
                    <span>Signal</span>
                </label>
            </div>
            {self._nav_buttons(3)}
        </form>
        """
        return self._step_wrapper(3, "Месенджери", content)

    def _render_telegram(self) -> str:
        if "telegram" not in self.config.get("enabled_channels", ["telegram"]):
            return self.render_step(5)
        content = f"""
        <form hx-post="/setup/step/5" hx-target="#wizard-step" hx-swap="outerHTML">
            <div class="bg-gray-700 p-4 rounded mb-4 text-sm text-gray-300">
                <p class="mb-2">Інструкція:</p>
                <ol class="list-decimal list-inside space-y-1">
                    <li>Відкрийте <strong>@BotFather</strong> в Telegram</li>
                    <li>Напишіть <code>/newbot</code></li>
                    <li>Введіть ім'я та username бота</li>
                    <li>Скопіюйте токен</li>
                </ol>
            </div>

            <label class="block mb-2 text-sm text-gray-300">Bot Token</label>
            <input type="text" name="telegram_token" placeholder="123456789:ABCdef..."
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4"
                   value="{self.config.get("telegram_token", "")}">

            <div id="tg-test-result" class="mb-4"></div>
            <button type="button"
                    hx-post="/setup/test-telegram" hx-target="#tg-test-result"
                    hx-include="[name=telegram_token]"
                    class="px-3 py-1 bg-gray-600 hover:bg-gray-500 rounded text-sm mb-4">
                Перевірити токен
            </button>

            <label class="block mb-2 text-sm text-gray-300">
                Ваш Telegram ID (через @userinfobot)
            </label>
            <input type="number" name="telegram_owner_id" placeholder="123456789"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4"
                   value="{self.config.get("telegram_owner_id", "")}">

            {self._nav_buttons(4)}
        </form>
        """
        return self._step_wrapper(4, "Telegram", content)

    def _render_discord(self) -> str:
        if "discord" not in self.config.get("enabled_channels", []):
            return self.render_step(6)
        content = f"""
        <form hx-post="/setup/step/6" hx-target="#wizard-step" hx-swap="outerHTML">
            <div class="bg-gray-700 p-4 rounded mb-4 text-sm text-gray-300">
                <p>Створіть бота на Discord Developer Portal та скопіюйте Bot Token.</p>
            </div>
            <label class="block mb-2 text-sm text-gray-300">Bot Token</label>
            <input type="password" name="discord_token"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4"
                   value="{self.config.get("discord_token", "")}">

            <label class="block mb-2 text-sm text-gray-300">Server (Guild) ID</label>
            <input type="text" name="discord_guild_id" placeholder="(опційно)"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4"
                   value="{self.config.get("discord_guild_id", "")}">

            {self._nav_buttons(5)}
        </form>
        """
        return self._step_wrapper(5, "Discord", content)

    def _render_slack(self) -> str:
        if "slack" not in self.config.get("enabled_channels", []):
            return self.render_step(7)
        content = f"""
        <form hx-post="/setup/step/7" hx-target="#wizard-step" hx-swap="outerHTML">
            <div class="bg-gray-700 p-4 rounded mb-4 text-sm text-gray-300">
                <p>Створіть Slack App, додайте Socket Mode та Bot Token.</p>
            </div>
            <label class="block mb-2 text-sm text-gray-300">Bot Token (xoxb-...)</label>
            <input type="password" name="slack_bot_token"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4"
                   value="{self.config.get("slack_bot_token", "")}">

            <label class="block mb-2 text-sm text-gray-300">App Token (xapp-...)</label>
            <input type="password" name="slack_app_token"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4"
                   value="{self.config.get("slack_app_token", "")}">

            {self._nav_buttons(6)}
        </form>
        """
        return self._step_wrapper(6, "Slack", content)

    def _render_whatsapp(self) -> str:
        if "whatsapp" not in self.config.get("enabled_channels", []):
            return self.render_step(8)
        content = f"""
        <form hx-post="/setup/step/8" hx-target="#wizard-step" hx-swap="outerHTML">
            <div class="bg-gray-700 p-4 rounded mb-4 text-sm text-gray-300">
                <p>WhatsApp через Twilio API. Зареєструйтесь на twilio.com.</p>
            </div>
            <label class="block mb-2 text-sm text-gray-300">Account SID</label>
            <input type="password" name="whatsapp_account_sid"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">

            <label class="block mb-2 text-sm text-gray-300">Auth Token</label>
            <input type="password" name="whatsapp_auth_token"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">

            <label class="block mb-2 text-sm text-gray-300">Номер (whatsapp:+380...)</label>
            <input type="text" name="whatsapp_from_number"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">

            {self._nav_buttons(7)}
        </form>
        """
        return self._step_wrapper(7, "WhatsApp", content)

    def _render_signal(self) -> str:
        if "signal" not in self.config.get("enabled_channels", []):
            return self.render_step(9)
        content = f"""
        <form hx-post="/setup/step/9" hx-target="#wizard-step" hx-swap="outerHTML">
            <div class="bg-gray-700 p-4 rounded mb-4 text-sm text-gray-300">
                <p>Signal через signal-cli REST API. Переконайтесь що signal-cli запущено.</p>
            </div>
            <label class="block mb-2 text-sm text-gray-300">Номер телефону</label>
            <input type="text" name="signal_phone_number" placeholder="+380..."
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">

            <label class="block mb-2 text-sm text-gray-300">signal-cli URL</label>
            <input type="text" name="signal_cli_url" value="http://localhost:8080"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">

            {self._nav_buttons(8)}
        </form>
        """
        return self._step_wrapper(8, "Signal", content)

    def _render_google(self) -> str:
        content = f"""
        <form hx-post="/setup/step/10" hx-target="#wizard-step" hx-swap="outerHTML">
            <p class="text-gray-400 mb-4">Опційно: підключіть Google сервіси.</p>
            <div class="space-y-3 mb-4">
                <label class="flex items-center gap-3 p-3 bg-gray-700 rounded cursor-pointer
                              hover:bg-gray-600">
                    <input type="checkbox" name="google_services" value="gmail" class="w-4 h-4">
                    <span>Gmail</span>
                </label>
                <label class="flex items-center gap-3 p-3 bg-gray-700 rounded cursor-pointer
                              hover:bg-gray-600">
                    <input type="checkbox" name="google_services" value="calendar"
                           class="w-4 h-4">
                    <span>Google Calendar</span>
                </label>
            </div>

            <label class="block mb-2 text-sm text-gray-300">
                Шлях до credentials.json (Google Cloud Console)
            </label>
            <input type="text" name="google_credentials_path"
                   placeholder="~/.posipaka/credentials.json"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">
            <p class="text-xs text-gray-500 mb-4">
                Інструкція: console.cloud.google.com &rarr; APIs &rarr; Credentials &rarr;
                OAuth 2.0 Client ID &rarr; Download JSON
            </p>

            {self._nav_buttons(9)}
        </form>
        """
        return self._step_wrapper(9, "Google (опційно)", content)

    def _render_agent(self) -> str:
        soul_content = SOUL_DEFAULT_CONTENT
        content = f"""
        <form hx-post="/setup/step/11" hx-target="#wizard-step" hx-swap="outerHTML">
            <label class="block mb-2 text-sm text-gray-300">Ім'я агента</label>
            <input type="text" name="soul_name" value="Posipaka"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">

            <label class="block mb-2 text-sm text-gray-300">Мова відповідей</label>
            <select name="soul_language"
                    class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">
                <option value="auto" selected>Авто (визначається з повідомлення)</option>
                <option value="uk">Українська</option>
                <option value="en">English</option>
                <option value="ru">Русский</option>
            </select>

            <label class="block mb-2 text-sm text-gray-300">Часовий пояс</label>
            <input type="text" name="soul_timezone" value="Europe/Kyiv"
                   class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4">

            <label class="block mb-2 text-sm text-gray-300">
                Особистість (SOUL.md) — можна редагувати
            </label>
            <textarea name="soul_content" rows="10"
                      class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4
                             font-mono text-sm">{soul_content}</textarea>

            {self._nav_buttons(10)}
        </form>
        """
        return self._step_wrapper(10, "Персоналізація агента", content)

    def _render_summary(self) -> str:
        channels = ", ".join(self.config.get("enabled_channels", ["cli"]))
        content = f"""
        <form hx-post="/setup/save" hx-target="#wizard-step" hx-swap="outerHTML">
            <table class="w-full text-sm mb-6">
                <tr class="border-b border-gray-700">
                    <td class="py-2 text-gray-400">LLM</td>
                    <td class="py-2">{self.config.get("llm_provider", "anthropic")} /
                        {self.config.get("llm_model", "claude-sonnet-4-20250514")}</td>
                </tr>
                <tr class="border-b border-gray-700">
                    <td class="py-2 text-gray-400">Месенджери</td>
                    <td class="py-2">{channels}</td>
                </tr>
                <tr class="border-b border-gray-700">
                    <td class="py-2 text-gray-400">Ім'я агента</td>
                    <td class="py-2">{self.config.get("soul_name", "Posipaka")}</td>
                </tr>
                <tr class="border-b border-gray-700">
                    <td class="py-2 text-gray-400">Мова</td>
                    <td class="py-2">{self.config.get("soul_language", "auto")}</td>
                </tr>
                <tr class="border-b border-gray-700">
                    <td class="py-2 text-gray-400">Часовий пояс</td>
                    <td class="py-2">{self.config.get("soul_timezone", "Europe/Kyiv")}</td>
                </tr>
                <tr class="border-b border-gray-700">
                    <td class="py-2 text-gray-400">Telegram</td>
                    <td class="py-2">{
            "налаштовано" if self.config.get("telegram_token") else "---"
        }</td>
                </tr>
                <tr class="border-b border-gray-700">
                    <td class="py-2 text-gray-400">Discord</td>
                    <td class="py-2">{
            "налаштовано" if self.config.get("discord_token") else "---"
        }</td>
                </tr>
                <tr class="border-b border-gray-700">
                    <td class="py-2 text-gray-400">Google</td>
                    <td class="py-2">{
            "налаштовано" if self.config.get("google_credentials_path") else "---"
        }</td>
                </tr>
            </table>

            <label class="flex items-center gap-3 mb-4">
                <input type="checkbox" name="generate_docker" class="w-4 h-4">
                <span class="text-sm text-gray-300">
                    Згенерувати docker-compose.yml
                </span>
            </label>

            <button type="submit"
                    class="w-full px-4 py-3 bg-green-600 hover:bg-green-700 rounded
                           font-bold text-lg">
                Зберегти та завершити
            </button>
            <button type="button"
                    hx-get="/setup/step/10" hx-target="#wizard-step" hx-swap="outerHTML"
                    class="w-full px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded mt-2">
                &larr; Назад
            </button>
        </form>
        """
        return self._step_wrapper(11, "Підсумок", content)

    def _render_done(self) -> str:
        content = """
        <div class="text-center">
            <div class="text-4xl mb-4">&#10003;</div>
            <p class="text-lg mb-6">Налаштування завершено!</p>
            <div class="bg-gray-700 p-4 rounded text-left text-sm font-mono space-y-2 mb-6">
                <p><strong>posipaka start</strong> — запустити агента</p>
                <p><strong>posipaka chat</strong> — CLI чат для тестування</p>
                <p><strong>posipaka status</strong> — перевірити статус</p>
            </div>
            <a href="/"
               class="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded font-bold inline-block">
                Перейти до Dashboard
            </a>
        </div>
        """
        return self._step_wrapper(12, "Готово!", content)

    # ─── Form Processing ───────────────────────────────────────────

    def process_step(self, step: int, form_data: dict[str, Any]) -> None:
        """Process form data for a step."""
        if step == 2:
            # LLM
            self.config["llm_provider"] = form_data.get("llm_provider", "anthropic")
            self.config["llm_api_key"] = form_data.get("llm_api_key", "")
            model_defaults = {
                "anthropic": "claude-sonnet-4-20250514",
                "openai": "gpt-4o-mini",
                "ollama": "llama3",
                "mistral": "mistral-large-latest",
                "gemini": "gemini-2.0-flash",
                "groq": "llama-3.3-70b-versatile",
                "deepseek": "deepseek-chat",
                "xai": "grok-3-mini",
            }
            self.config["llm_model"] = model_defaults.get(self.config["llm_provider"], "llama3")
        elif step == 3:
            # Messengers
            channels = form_data.getlist("channels") if hasattr(form_data, "getlist") else []
            if not channels:
                channels = [form_data.get("channels", "cli")]
                if isinstance(channels[0], list):
                    channels = channels[0]
            self.config["enabled_channels"] = channels if channels else ["cli"]
        elif step == 4:
            # Telegram
            self.config["telegram_token"] = form_data.get("telegram_token", "")
            owner_id = form_data.get("telegram_owner_id", "0")
            self.config["telegram_owner_id"] = int(owner_id) if owner_id else 0
        elif step == 5:
            # Discord
            self.config["discord_token"] = form_data.get("discord_token", "")
            self.config["discord_guild_id"] = form_data.get("discord_guild_id", "")
        elif step == 6:
            # Slack
            self.config["slack_bot_token"] = form_data.get("slack_bot_token", "")
            self.config["slack_app_token"] = form_data.get("slack_app_token", "")
        elif step == 7:
            # WhatsApp
            self.config["whatsapp_account_sid"] = form_data.get("whatsapp_account_sid", "")
            self.config["whatsapp_auth_token"] = form_data.get("whatsapp_auth_token", "")
            self.config["whatsapp_from_number"] = form_data.get("whatsapp_from_number", "")
        elif step == 8:
            # Signal
            self.config["signal_phone_number"] = form_data.get("signal_phone_number", "")
            self.config["signal_cli_url"] = form_data.get("signal_cli_url", "http://localhost:8080")
        elif step == 9:
            # Google
            self.config["google_credentials_path"] = form_data.get("google_credentials_path", "")
            services = form_data.getlist("google_services") if hasattr(form_data, "getlist") else []
            self.config["google_services"] = services
        elif step == 10:
            # Agent
            self.config["soul_name"] = form_data.get("soul_name", "Posipaka")
            self.config["soul_language"] = form_data.get("soul_language", "auto")
            self.config["soul_timezone"] = form_data.get("soul_timezone", "Europe/Kyiv")
            self.config["soul_content"] = form_data.get("soul_content", SOUL_DEFAULT_CONTENT)

    def get_next_step(self, current: int) -> int:
        """Determine which step to show next (skip unconfigured messengers)."""
        channels = self.config.get("enabled_channels", ["telegram"])
        skip_map = {
            4: "telegram",
            5: "discord",
            6: "slack",
            7: "whatsapp",
            8: "signal",
        }
        nxt = current + 1
        while nxt in skip_map and skip_map[nxt] not in channels:
            nxt += 1
        return min(nxt, self.TOTAL_STEPS)

    # ─── Save Config ───────────────────────────────────────────────

    def save(self, generate_docker: bool = False) -> Path:
        """Save configuration to ~/.posipaka/."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for subdir in ("logs", "skills", "chroma", "tantivy", "backups", "personas", "workflows"):
            (self.data_dir / subdir).mkdir(exist_ok=True)

        # .env
        env_lines = [
            f"LLM_PROVIDER={self.config.get('llm_provider', 'anthropic')}",
            f"LLM_MODEL={self.config.get('llm_model', 'claude-sonnet-4-20250514')}",
            f"LLM_API_KEY={self.config.get('llm_api_key', '')}",
        ]

        if self.config.get("telegram_token"):
            env_lines.append(f"TELEGRAM_TOKEN={self.config['telegram_token']}")
            env_lines.append(f"TELEGRAM_OWNER_ID={self.config.get('telegram_owner_id', 0)}")
        if self.config.get("discord_token"):
            env_lines.append(f"DISCORD_TOKEN={self.config['discord_token']}")
            if self.config.get("discord_guild_id"):
                env_lines.append(f"DISCORD_GUILD_ID={self.config['discord_guild_id']}")
        if self.config.get("slack_bot_token"):
            env_lines.append(f"SLACK_BOT_TOKEN={self.config['slack_bot_token']}")
            env_lines.append(f"SLACK_APP_TOKEN={self.config.get('slack_app_token', '')}")
        if self.config.get("whatsapp_account_sid"):
            env_lines.append(f"WHATSAPP_ACCOUNT_SID={self.config['whatsapp_account_sid']}")
            env_lines.append(f"WHATSAPP_AUTH_TOKEN={self.config.get('whatsapp_auth_token', '')}")
            env_lines.append(f"WHATSAPP_FROM_NUMBER={self.config.get('whatsapp_from_number', '')}")
        if self.config.get("signal_phone_number"):
            env_lines.append(f"SIGNAL_PHONE_NUMBER={self.config['signal_phone_number']}")
            env_lines.append(
                f"SIGNAL_CLI_URL={self.config.get('signal_cli_url', 'http://localhost:8080')}"
            )
        if self.config.get("google_credentials_path"):
            env_lines.append(f"GOOGLE_CREDENTIALS_PATH={self.config['google_credentials_path']}")

        env_lines.append(f"SOUL_NAME={self.config.get('soul_name', 'Posipaka')}")
        env_lines.append(f"SOUL_LANGUAGE={self.config.get('soul_language', 'auto')}")
        env_lines.append(f"SOUL_TIMEZONE={self.config.get('soul_timezone', 'Europe/Kyiv')}")

        channels = self.config.get("enabled_channels", ["cli"])
        env_lines.append(f"ENABLED_CHANNELS={channels}")

        env_path = self.data_dir / ".env"
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        env_path.chmod(0o600)

        # Default files
        soul_content = self.config.get("soul_content", SOUL_DEFAULT_CONTENT)
        for path, content in [
            (self.data_dir / "SOUL.md", soul_content),
            (self.data_dir / "USER.md", USER_DEFAULT_CONTENT),
            (self.data_dir / "MEMORY.md", MEMORY_DEFAULT_CONTENT),
        ]:
            if not path.exists():
                path.write_text(content, encoding="utf-8")

        # config.yaml (no secrets)
        safe_config = {
            k: v
            for k, v in self.config.items()
            if "key" not in k
            and "token" not in k
            and "secret" not in k
            and "sid" not in k
            and "content" not in k
        }
        config_yaml = self.data_dir / "config.yaml"
        config_yaml.write_text(yaml.dump(safe_config, allow_unicode=True), encoding="utf-8")

        # docker-compose.yml
        if generate_docker:
            self._generate_docker_compose()

        logger.info(f"Web wizard: config saved to {self.data_dir}")
        return self.data_dir

    def _generate_docker_compose(self) -> None:
        """Generate docker-compose.yml for the user."""
        compose = {
            "version": "3.8",
            "services": {
                "posipaka": {
                    "build": ".",
                    "restart": "unless-stopped",
                    "env_file": [".env"],
                    "volumes": [
                        f"{self.data_dir}:/home/posipaka/.posipaka",
                    ],
                    "ports": ["8080:8080"],
                }
            },
        }
        compose_path = self.data_dir / "docker-compose.yml"
        compose_path.write_text(yaml.dump(compose, default_flow_style=False), encoding="utf-8")

    # ─── Test Helpers ──────────────────────────────────────────────

    def test_llm(self, provider: str, api_key: str) -> str:
        """Test LLM connection. Returns HTML fragment."""
        openai_compatible = {
            "openai": ("https://api.openai.com/v1/models", "gpt-4o-mini", "OpenAI"),
            "mistral": ("https://api.mistral.ai/v1/models", "mistral-large-latest", "Mistral"),
            "gemini": (
                "https://generativelanguage.googleapis.com/v1beta/openai/models",
                "gemini-2.0-flash",
                "Gemini",
            ),
            "groq": ("https://api.groq.com/openai/v1/models", "llama-3.3-70b-versatile", "Groq"),
            "deepseek": ("https://api.deepseek.com/v1/models", "deepseek-chat", "DeepSeek"),
            "xai": ("https://api.x.ai/v1/models", "grok-3-mini", "xAI"),
        }
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
                    model = resp.json().get("model", "claude-sonnet-4-20250514")
                    self.config["llm_model"] = model
                    return (
                        '<p class="text-green-400">&#10003; Підключення успішне! '
                        f"Модель: {model}</p>"
                    )
                return f'<p class="text-red-400">&#10007; Помилка: {resp.status_code}</p>'
            elif provider in openai_compatible:
                base_url, default_model, name = openai_compatible[provider]
                resp = httpx.get(
                    base_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    self.config["llm_model"] = default_model
                    return f'<p class="text-green-400">&#10003; {name} підключено!</p>'
                return f'<p class="text-red-400">&#10007; Помилка: {resp.status_code}</p>'
            elif provider == "ollama":
                self.config["llm_model"] = "llama3"
                return (
                    '<p class="text-yellow-400">&#9888; Ollama — перевірте що сервер запущено</p>'
                )
        except Exception as e:
            return f'<p class="text-red-400">&#10007; {e}</p>'
        return '<p class="text-red-400">&#10007; Невідомий провайдер</p>'

    def test_telegram(self, token: str) -> str:
        """Test Telegram bot token. Returns HTML fragment."""
        try:
            resp = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    username = data["result"].get("username", "")
                    return f'<p class="text-green-400">&#10003; Бот: @{username}</p>'
            return '<p class="text-red-400">&#10007; Невірний токен</p>'
        except Exception as e:
            return f'<p class="text-red-400">&#10007; {e}</p>'

    # ─── Full Page Wrapper ─────────────────────────────────────────

    def render_full_page(self, step: int = 1) -> str:
        """Render complete HTML page with wizard step."""
        step_html = self.render_step(step)
        return f"""<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Posipaka — Setup Wizard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen flex items-center justify-center p-4">
    {step_html}
</body>
</html>"""
