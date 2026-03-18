"""SetupWizard — інтерактивне налаштування через Rich TUI (12 кроків)."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

import httpx
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from posipaka.config.defaults import (
    MEMORY_DEFAULT_CONTENT,
    SOUL_DEFAULT_CONTENT,
    USER_DEFAULT_CONTENT,
)

TOTAL_STEPS = 12


class SetupWizard:
    """Покроковий wizard для налаштування Posipaka (12 кроків)."""

    def __init__(self) -> None:
        self.console = Console()
        self.config: dict = {}
        self.data_dir = Path.home() / ".posipaka"

    def run(self) -> None:
        """Запустити wizard."""
        self._step_welcome()  # 1
        self._step_llm_provider()  # 2
        self._step_messengers()  # 3
        self._step_telegram()  # 4
        self._step_discord()  # 5
        self._step_slack()  # 6
        self._step_whatsapp()  # 7
        self._step_signal()  # 8
        self._step_google()  # 9
        self._step_agent_settings()  # 10
        self._step_summary()  # 11
        self._step_save()  # 11 (save)
        self._step_launch()  # 12

    # ─── Step 1: Welcome ──────────────────────────────────────────

    def _step_welcome(self) -> None:
        """Крок 1: Привітання + перевірка системи."""
        self.console.print(
            Panel(
                "[bold blue]POSIPAKA[/bold blue] — Майстер налаштування\n\n"
                "Ласкаво просимо! Налаштування займе ~5 хвилин.",
                title=f"Крок 1/{TOTAL_STEPS} — Привітання",
                border_style="blue",
            )
        )

        table = Table(show_header=False, box=None)
        table.add_column(width=3)
        table.add_column()

        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        py_ok = sys.version_info >= (3, 11)
        table.add_row("ok" if py_ok else "!!", f"Python {py_ver}")

        disk = shutil.disk_usage(Path.home())
        disk_gb = disk.free / (1024**3)
        table.add_row("ok" if disk_gb > 1 else "!!", f"Диск: {disk_gb:.1f} GB вільно")

        try:
            httpx.get("https://httpbin.org/get", timeout=5)
            table.add_row("ok", "Мережа: доступна")
        except Exception:
            table.add_row("!!", "Мережа: недоступна (деякі функції не працюватимуть)")

        table.add_row("--", f"ОС: {platform.system()} {platform.release()}")
        self.console.print(table)
        self.console.print()

        if not py_ok:
            self.console.print("[red]Python 3.11+ обов'язковий![/red]")
            sys.exit(1)

    # ─── Step 2: LLM Provider ────────────────────────────────────

    def _step_llm_provider(self) -> None:
        """Крок 2: Вибір LLM провайдера."""
        self.console.print(
            Panel(
                "Оберіть AI-модель для агента:",
                title=f"Крок 2/{TOTAL_STEPS} — AI модель",
                border_style="blue",
            )
        )

        providers = {
            "1": ("mistral", "Mistral AI (рекомендовано)"),
            "2": ("anthropic", "Anthropic Claude"),
            "3": ("openai", "OpenAI GPT-4o"),
            "4": ("ollama", "Ollama (локально, безкоштовно)"),
            "5": ("gemini", "Google Gemini"),
            "6": ("groq", "Groq (швидко, безкоштовно)"),
            "7": ("deepseek", "DeepSeek"),
            "8": ("xai", "xAI Grok"),
        }

        for key, (_, desc) in providers.items():
            self.console.print(f"  [{key}] {desc}")
        self.console.print()

        choice = Prompt.ask("Ваш вибір", choices=list(providers.keys()), default="1")
        provider, desc = providers[choice]
        self.config["llm_provider"] = provider

        if provider == "ollama":
            base_url = Prompt.ask("Ollama URL", default="http://localhost:11434/v1")
            self.config["llm_base_url"] = base_url
            self.config["llm_model"] = Prompt.ask("Модель", default="llama3")
            self.config["llm_api_key"] = ""
        else:
            api_key = Prompt.ask(f"API ключ для {desc}", password=True)
            self.config["llm_api_key"] = api_key

            self.console.print("[dim]Перевіряю підключення...[/dim]")
            model = self._test_llm(provider, api_key)
            if model:
                self.console.print(f"[green]Підключення успішне! Модель: {model}[/green]")
                self.config["llm_model"] = model
            else:
                self.console.print(
                    "[yellow]Не вдалось підключитись. Перевірте ключ пізніше.[/yellow]"
                )
                default_models = {
                    "anthropic": "claude-sonnet-4-20250514",
                    "openai": "gpt-4o-mini",
                    "mistral": "mistral-large-latest",
                    "gemini": "gemini-2.0-flash",
                    "groq": "llama-3.3-70b-versatile",
                    "deepseek": "deepseek-chat",
                    "xai": "grok-3-mini",
                }
                self.config["llm_model"] = default_models.get(provider, "gpt-4o-mini")

    # ─── Step 3: Messenger Selection ─────────────────────────────

    def _step_messengers(self) -> None:
        """Крок 3: Вибір месенджерів."""
        self.console.print(
            Panel(
                "Виберіть месенджери (можна декілька):",
                title=f"Крок 3/{TOTAL_STEPS} — Месенджери",
                border_style="blue",
            )
        )

        messengers = {
            "telegram": "Telegram (найпростіший старт)",
            "discord": "Discord",
            "slack": "Slack",
            "whatsapp": "WhatsApp",
            "signal": "Signal",
        }

        selected = []
        for key, desc in messengers.items():
            default = key == "telegram"
            if Confirm.ask(f"  {desc}", default=default):
                selected.append(key)

        self.config["enabled_channels"] = selected if selected else ["cli"]

    # ─── Step 4: Telegram ─────────────────────────────────────────

    def _step_telegram(self) -> None:
        """Крок 4: Налаштування Telegram."""
        if "telegram" not in self.config.get("enabled_channels", []):
            return

        self.console.print(
            Panel(
                "Налаштування Telegram:\n"
                "1. Відкрийте @BotFather в Telegram\n"
                "2. Напишіть /newbot\n"
                "3. Введіть ім'я та username бота\n"
                "4. Скопіюйте токен",
                title=f"Крок 4/{TOTAL_STEPS} — Telegram",
                border_style="blue",
            )
        )
        token = Prompt.ask("Bot Token")
        self.config["telegram_token"] = token

        self.console.print("[dim]Перевіряю токен...[/dim]")
        bot_info = self._test_telegram_token(token)
        if bot_info:
            self.console.print(f"[green]Бот: @{bot_info}[/green]")
        else:
            self.console.print("[yellow]Не вдалось перевірити токен[/yellow]")

        owner_id = Prompt.ask(
            "Ваш Telegram ID (знайдіть через @userinfobot)",
            default="0",
        )
        self.config["telegram_owner_id"] = int(owner_id)

    # ─── Step 5: Discord ──────────────────────────────────────────

    def _step_discord(self) -> None:
        """Крок 5: Налаштування Discord."""
        if "discord" not in self.config.get("enabled_channels", []):
            return

        self.console.print(
            Panel(
                "Налаштування Discord:\n"
                "1. Discord Developer Portal -> Applications -> New\n"
                "2. Bot -> Add Bot -> Copy Token\n"
                "3. OAuth2 -> URL Generator -> bot + applications.commands",
                title=f"Крок 5/{TOTAL_STEPS} — Discord",
                border_style="blue",
            )
        )
        self.config["discord_token"] = Prompt.ask("Bot Token", password=True)
        self.config["discord_guild_id"] = Prompt.ask("Server (Guild) ID", default="")

        # Test
        self.console.print("[dim]Перевіряю токен...[/dim]")
        ok = self._test_discord_token(self.config["discord_token"])
        if ok:
            self.console.print("[green]Discord токен дійсний[/green]")
        else:
            self.console.print("[yellow]Не вдалось перевірити токен[/yellow]")

    # ─── Step 6: Slack ────────────────────────────────────────────

    def _step_slack(self) -> None:
        """Крок 6: Налаштування Slack."""
        if "slack" not in self.config.get("enabled_channels", []):
            return

        self.console.print(
            Panel(
                "Налаштування Slack:\n"
                "1. api.slack.com/apps -> Create New App\n"
                "2. Socket Mode -> Enable\n"
                "3. OAuth & Permissions -> Install -> Copy Bot Token\n"
                "4. Basic Information -> App-Level Tokens -> Generate",
                title=f"Крок 6/{TOTAL_STEPS} — Slack",
                border_style="blue",
            )
        )
        self.config["slack_bot_token"] = Prompt.ask("Bot Token (xoxb-...)", password=True)
        self.config["slack_app_token"] = Prompt.ask("App Token (xapp-...)", password=True)

    # ─── Step 7: WhatsApp ─────────────────────────────────────────

    def _step_whatsapp(self) -> None:
        """Крок 7: Налаштування WhatsApp."""
        if "whatsapp" not in self.config.get("enabled_channels", []):
            return

        self.console.print(
            Panel(
                "Налаштування WhatsApp через Twilio:\n"
                "1. Зареєструйтесь на twilio.com\n"
                "2. Console -> Account SID та Auth Token\n"
                "3. Messaging -> WhatsApp Sandbox -> Активуйте",
                title=f"Крок 7/{TOTAL_STEPS} — WhatsApp",
                border_style="blue",
            )
        )
        self.config["whatsapp_account_sid"] = Prompt.ask("Account SID", password=True)
        self.config["whatsapp_auth_token"] = Prompt.ask("Auth Token", password=True)
        self.config["whatsapp_from_number"] = Prompt.ask("Номер (whatsapp:+...)", default="")

    # ─── Step 8: Signal ───────────────────────────────────────────

    def _step_signal(self) -> None:
        """Крок 8: Налаштування Signal."""
        if "signal" not in self.config.get("enabled_channels", []):
            return

        self.console.print(
            Panel(
                "Налаштування Signal:\n"
                "1. Встановіть signal-cli: apt install signal-cli\n"
                "2. Запустіть REST API: signal-cli-rest-api\n"
                "3. Зареєструйте номер або прив'яжіть через QR-код",
                title=f"Крок 8/{TOTAL_STEPS} — Signal",
                border_style="blue",
            )
        )

        # Check if signal-cli is installed
        import shutil as sh

        if sh.which("signal-cli"):
            self.console.print("[green]signal-cli знайдено[/green]")
        else:
            self.console.print("[yellow]signal-cli не знайдено. Встановіть окремо.[/yellow]")

        self.config["signal_phone_number"] = Prompt.ask("Номер телефону (+380...)", default="")
        self.config["signal_cli_url"] = Prompt.ask(
            "signal-cli REST URL", default="http://localhost:8080"
        )

    # ─── Step 9: Google Integrations ──────────────────────────────

    def _step_google(self) -> None:
        """Крок 9: Google інтеграції (опційно)."""
        self.console.print(
            Panel(
                "Google інтеграції (опційно):\nGmail, Calendar, Drive",
                title=f"Крок 9/{TOTAL_STEPS} — Google",
                border_style="blue",
            )
        )

        if not Confirm.ask("Налаштувати Google інтеграції?", default=False):
            return

        google_services = []
        if Confirm.ask("  Gmail", default=True):
            google_services.append("gmail")
        if Confirm.ask("  Calendar", default=True):
            google_services.append("calendar")
        self.config["google_services"] = google_services

        self.console.print(
            "\n[dim]Інструкція:[/dim]\n"
            "1. console.cloud.google.com -> Create Project\n"
            "2. APIs & Services -> Enable Gmail API / Calendar API\n"
            "3. Credentials -> Create OAuth 2.0 Client ID\n"
            "4. Download JSON -> збережіть як credentials.json\n"
        )

        cred_path = Prompt.ask(
            "Шлях до credentials.json",
            default=str(self.data_dir / "credentials.json"),
        )
        self.config["google_credentials_path"] = cred_path

        cred_file = Path(cred_path).expanduser()
        if cred_file.exists():
            self.console.print("[green]credentials.json знайдено[/green]")

            if Confirm.ask("Авторизуватись зараз (відкриє браузер)?", default=True):
                self._run_google_oauth(cred_file)
        else:
            self.console.print("[yellow]Файл не знайдено. Додайте його пізніше.[/yellow]")

    def _run_google_oauth(self, cred_path: Path) -> None:
        """Run Google OAuth flow (opens browser)."""
        try:
            from google.auth.transport.requests import Request as GRequest
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow

            SCOPES = [
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/calendar",
            ]

            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
            creds = flow.run_local_server(port=0)

            token_path = self.data_dir / "google_token.json"
            token_path.write_text(creds.to_json(), encoding="utf-8")
            token_path.chmod(0o600)
            self.config["google_token_path"] = str(token_path)
            self.console.print("[green]Google авторизація успішна![/green]")
        except ImportError:
            self.console.print(
                "[yellow]google-auth-oauthlib не встановлено. "
                "Запустіть: pip install posipaka[google][/yellow]"
            )
        except Exception as e:
            self.console.print(f"[yellow]Помилка OAuth: {e}[/yellow]")

    # ─── Step 10: Agent Settings ──────────────────────────────────

    def _step_agent_settings(self) -> None:
        """Крок 10: Налаштування агента та SOUL.md."""
        self.console.print(
            Panel(
                "Персоналізація агента:",
                title=f"Крок 10/{TOTAL_STEPS} — Агент",
                border_style="blue",
            )
        )

        self.config["soul_name"] = Prompt.ask("Ім'я агента", default="Posipaka")
        self.config["soul_language"] = Prompt.ask(
            "Мова відповідей", default="auto", choices=["auto", "uk", "en", "ru"]
        )
        self.config["soul_timezone"] = Prompt.ask("Часовий пояс", default="Europe/Kyiv")

        # SOUL.md editing
        if Confirm.ask("Редагувати SOUL.md (особистість агента)?", default=False):
            self.console.print(
                Panel(SOUL_DEFAULT_CONTENT, title="SOUL.md (поточний)", border_style="dim")
            )
            self.console.print(
                "[dim]Щоб редагувати, відкрийте файл після збереження: "
                f"nano {self.data_dir}/SOUL.md[/dim]"
            )

    # ─── Step 11: Summary ─────────────────────────────────────────

    def _step_summary(self) -> None:
        """Крок 11: Підсумок."""
        self.console.print(
            Panel(
                "Підсумок налаштувань:",
                title=f"Крок 11/{TOTAL_STEPS} — Підсумок",
                border_style="green",
            )
        )

        table = Table(show_header=True, header_style="bold")
        table.add_column("Параметр")
        table.add_column("Значення")

        table.add_row(
            "LLM",
            f"{self.config.get('llm_provider')} / {self.config.get('llm_model')}",
        )
        table.add_row("Месенджери", ", ".join(self.config.get("enabled_channels", [])))
        table.add_row("Ім'я агента", self.config.get("soul_name", "Posipaka"))
        table.add_row("Мова", self.config.get("soul_language", "auto"))
        table.add_row("Часовий пояс", self.config.get("soul_timezone", "Europe/Kyiv"))

        if self.config.get("telegram_token"):
            table.add_row("Telegram", "налаштовано")
        if self.config.get("discord_token"):
            table.add_row("Discord", "налаштовано")
        if self.config.get("slack_bot_token"):
            table.add_row("Slack", "налаштовано")
        if self.config.get("whatsapp_account_sid"):
            table.add_row("WhatsApp", "налаштовано")
        if self.config.get("signal_phone_number"):
            table.add_row("Signal", "налаштовано")
        if self.config.get("google_credentials_path"):
            table.add_row("Google", "налаштовано")

        self.console.print(table)

    # ─── Save ─────────────────────────────────────────────────────

    def _step_save(self) -> None:
        """Збереження конфігурації."""
        self.console.print(
            Panel(
                "Збереження...",
                title=f"Крок 11/{TOTAL_STEPS} — Збереження",
                border_style="blue",
            )
        )

        self.data_dir.mkdir(parents=True, exist_ok=True)
        for subdir in (
            "logs",
            "skills",
            "chroma",
            "tantivy",
            "backups",
            "personas",
            "workflows",
        ):
            (self.data_dir / subdir).mkdir(exist_ok=True)

        # Generate .env
        env_lines = [
            f"LLM_PROVIDER={self.config.get('llm_provider', 'anthropic')}",
            f"LLM_MODEL={self.config.get('llm_model', 'claude-sonnet-4-20250514')}",
            f"LLM_API_KEY={self.config.get('llm_api_key', '')}",
        ]

        if self.config.get("llm_base_url"):
            env_lines.append(f"LLM_BASE_URL={self.config['llm_base_url']}")

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
            if self.config.get("google_token_path"):
                env_lines.append(f"GOOGLE_TOKEN_PATH={self.config['google_token_path']}")

        env_lines.append(f"SOUL_NAME={self.config.get('soul_name', 'Posipaka')}")
        env_lines.append(f"SOUL_LANGUAGE={self.config.get('soul_language', 'auto')}")
        env_lines.append(f"SOUL_TIMEZONE={self.config.get('soul_timezone', 'Europe/Kyiv')}")

        channels = self.config.get("enabled_channels", ["cli"])
        env_lines.append(f"ENABLED_CHANNELS={channels}")

        env_path = self.data_dir / ".env"
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        env_path.chmod(0o600)

        # Create default files
        for path, content in [
            (self.data_dir / "SOUL.md", SOUL_DEFAULT_CONTENT),
            (self.data_dir / "USER.md", USER_DEFAULT_CONTENT),
            (self.data_dir / "MEMORY.md", MEMORY_DEFAULT_CONTENT),
        ]:
            if not path.exists():
                path.write_text(content, encoding="utf-8")

        # config.yaml (no secrets)
        safe_config = {
            k: v
            for k, v in self.config.items()
            if "key" not in k and "token" not in k and "secret" not in k and "sid" not in k
        }
        config_yaml = self.data_dir / "config.yaml"
        config_yaml.write_text(yaml.dump(safe_config, allow_unicode=True), encoding="utf-8")

        # docker-compose.yml (optional)
        if Confirm.ask("Згенерувати docker-compose.yml?", default=False):
            self._generate_docker_compose()

        self.console.print(f"[green]Конфігурація збережена в {self.data_dir}[/green]")

    def _generate_docker_compose(self) -> None:
        """Generate docker-compose.yml."""
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
        self.console.print(f"[green]docker-compose.yml збережено в {compose_path}[/green]")

    # ─── Step 12: Launch ──────────────────────────────────────────

    def _step_launch(self) -> None:
        """Крок 12: Запуск."""
        self.console.print()
        self.console.print(
            Panel(
                "[bold green]Налаштування завершено![/bold green]\n\n"
                "Запустити агента:\n"
                "  [bold]posipaka start[/bold]     — запустити\n"
                "  [bold]posipaka chat[/bold]      — CLI чат для тестування\n"
                "  [bold]posipaka status[/bold]    — перевірити статус\n\n"
                "Deployment:\n"
                "  [bold]systemd[/bold]             — systemctl enable posipaka\n"
                "  [bold]docker[/bold]              — docker compose up -d\n"
                "  [bold]manual[/bold]              — posipaka start\n",
                title=f"Крок {TOTAL_STEPS}/{TOTAL_STEPS} — Готово!",
                border_style="green",
            )
        )

        if Confirm.ask("Надіслати тестове повідомлення?", default=False):
            self._send_test_message()

    def _send_test_message(self) -> None:
        """Send a test message through configured channel."""
        token = self.config.get("telegram_token", "")
        owner_id = self.config.get("telegram_owner_id", 0)

        if token and owner_id:
            try:
                resp = httpx.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": owner_id,
                        "text": (
                            "Posipaka працює!\n\n"
                            "Напишіть мені будь-що, і я відповім.\n"
                            "Команди: /help /status /skills"
                        ),
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    self.console.print("[green]Тестове повідомлення надіслано в Telegram![/green]")
                else:
                    self.console.print(f"[yellow]Помилка відправки: {resp.status_code}[/yellow]")
            except Exception as e:
                self.console.print(f"[yellow]Помилка: {e}[/yellow]")
        else:
            self.console.print("[dim]Telegram не налаштовано — тест пропущено[/dim]")

    # ─── Test Helpers ─────────────────────────────────────────────

    def _test_llm(self, provider: str, api_key: str) -> str | None:
        """Тест підключення до LLM."""
        openai_compatible = {
            "openai": ("https://api.openai.com/v1/models", "gpt-4o-mini"),
            "mistral": ("https://api.mistral.ai/v1/models", "mistral-large-latest"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/models", "gemini-2.0-flash"),
            "groq": ("https://api.groq.com/openai/v1/models", "llama-3.3-70b-versatile"),
            "deepseek": ("https://api.deepseek.com/v1/models", "deepseek-chat"),
            "xai": ("https://api.x.ai/v1/models", "grok-3-mini"),
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
                    return resp.json().get("model", "claude-sonnet-4-20250514")
                return None
            elif provider in openai_compatible:
                base_url, default_model = openai_compatible[provider]
                resp = httpx.get(
                    base_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return default_model
                return None
        except Exception:
            return None

    def _test_telegram_token(self, token: str) -> str | None:
        """Тест Telegram bot token."""
        try:
            resp = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data["result"].get("username", "")
            return None
        except Exception:
            return None

    def _test_discord_token(self, token: str) -> bool:
        """Тест Discord bot token."""
        try:
            resp = httpx.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token}"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False
