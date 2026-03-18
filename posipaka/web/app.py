"""FastAPI Web Application — Setup UI + Dashboard + API."""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from posipaka.web.auth import AuthManager, AuthMiddleware
from posipaka.web.middleware import RequestValidationMiddleware

# ─── Model catalog per provider ────────────────────────────────────────
_PROVIDER_MODELS: dict[str, list[tuple[str, str]]] = {
    "mistral": [
        ("mistral-large-latest", "Mistral Large ($2/M in)"),
        ("mistral-small-latest", "Mistral Small ($0.1/M in)"),
        ("ministral-8b-latest", "Ministral 8B ($0.1/M in)"),
        ("ministral-3b-latest", "Ministral 3B ($0.06/M in)"),
        ("codestral-latest", "Codestral (code, free)"),
    ],
    "anthropic": [
        ("claude-sonnet-4-20250514", "Claude Sonnet 4"),
        ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
        ("claude-opus-4-20250514", "Claude Opus 4"),
    ],
    "openai": [
        ("gpt-4o", "GPT-4o"),
        ("gpt-4o-mini", "GPT-4o Mini"),
    ],
    "gemini": [
        ("gemini-2.0-flash", "Gemini 2.0 Flash"),
        ("gemini-2.5-pro-preview-06-05", "Gemini 2.5 Pro"),
    ],
    "groq": [
        ("llama-3.3-70b-versatile", "Llama 3.3 70B"),
        ("llama-3.1-8b-instant", "Llama 3.1 8B"),
    ],
    "deepseek": [
        ("deepseek-chat", "DeepSeek Chat"),
        ("deepseek-reasoner", "DeepSeek Reasoner"),
    ],
    "xai": [
        ("grok-3", "Grok 3"),
        ("grok-3-mini", "Grok 3 Mini"),
    ],
    "ollama": [
        ("llama3", "Llama 3"),
        ("mistral", "Mistral"),
    ],
}


def _all_model_options(selected: str = "") -> str:
    """Build <option> elements for ALL providers combined (for routing selects)."""
    seen: set[str] = set()
    opts: list[str] = []
    for models in _PROVIDER_MODELS.values():
        for val, label in models:
            if val not in seen:
                seen.add(val)
                sel = " selected" if val == selected else ""
                opts.append(f'<option value="{val}"{sel}>{label}</option>')
    return "".join(opts)


def _extract_md_field(content: str, field: str, default: str = "") -> str:
    """Extract a field value from markdown content by heading or pattern."""
    patterns = {
        "identity": r"(?:^|\n)##?\s*(?:Identity|Хто я)\s*\n(.*?)(?:\n#|\Z)",
        "language": r"(?:^|\n)##?\s*(?:Language|Мова)\s*\n(.*?)(?:\n#|\Z)",
        "style": r"(?:^|\n)##?\s*(?:Style|Стиль)\s*\n(.*?)(?:\n#|\Z)",
        "extra": r"(?:^|\n)##?\s*(?:Extra|Додатково|Обмеження)\s*\n(.*?)(?:\n#|\Z)",
        "name": r"(?:^|\n)##?\s*(?:Name|Ім.я|Як вас звати)\s*\n(.*?)(?:\n#|\Z)",
        "work": r"(?:^|\n)##?\s*(?:Work|Робота|Сфера)\s*\n(.*?)(?:\n#|\Z)",
        "preferences": r"(?:^|\n)##?\s*(?:Preferences|Вподобання)\s*\n(.*?)(?:\n#|\Z)",
    }
    pattern = patterns.get(field)
    if not pattern:
        return default
    m = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else default


def _update_env(data_dir: Path, updates: dict[str, str]) -> None:
    """Update .env file with new values."""
    env_path = data_dir / ".env"
    # If running from /opt/posipaka, use that .env
    if not env_path.exists():
        env_path = Path("/opt/posipaka/.env")
    if not env_path.exists():
        # Create in data_dir
        env_path = data_dir / ".env"

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    for key, value in updates.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_app(
    agent: Any = None,
    data_dir: Path | None = None,
) -> FastAPI:
    """Створити FastAPI application."""
    app = FastAPI(
        title="Posipaka",
        description="Posipaka AI Agent — Web UI",
        version="0.1.0",
    )

    # Auth
    _data_dir = data_dir or Path.home() / ".posipaka"
    _data_dir.mkdir(parents=True, exist_ok=True)
    auth = AuthManager(_data_dir)
    if not auth.is_configured():
        password = auth.setup_password()
        from loguru import logger

        # Показати пароль яскраво — stdout + logger
        banner = (
            "\n"
            "=" * 50 + "\n"
            f"  WEB UI PASSWORD: {password}\n"
            "=" * 50 + "\n"
            "  Save this password! It won't be shown again.\n"
            "  Reset: posipaka reset-password\n"
            "=" * 50 + "\n"
        )
        print(banner, flush=True)  # noqa: T201
        logger.info("Web UI password generated (first run)")

    # Middleware (order: last added = first executed)
    app.add_middleware(RequestValidationMiddleware)
    app.add_middleware(AuthMiddleware, auth_manager=auth)

    from posipaka.web.middleware import WebhookRateLimiter
    from posipaka.web.security_headers import SecurityHeadersMiddleware

    app.add_middleware(WebhookRateLimiter, max_requests=120, window_seconds=60)
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS — з підтримкою custom domains
    import os

    from fastapi.middleware.cors import CORSMiddleware

    origins = ["http://127.0.0.1:8080", "http://localhost:8080"]
    custom_domain = os.getenv("POSIPAKA_DOMAIN", "")
    if custom_domain:
        origins.append(f"https://{custom_domain}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ─── Health ──────────────────────────────────────────────────────
    @app.get("/api/v1/health")
    async def health():
        from posipaka.core.health import check_health

        report = await check_health(agent)
        return {
            "status": report.overall,
            "version": "0.1.0",
            **report.to_dict(),
        }

    # ─── Update check ────────────────────────────────────────────────
    @app.post("/api/v1/check-update", response_class=HTMLResponse)
    async def check_update():
        try:
            from posipaka.core.auto_update import AutoUpdater

            data_dir = agent.settings.data_dir if agent else Path.home() / ".posipaka"
            updater = AutoUpdater(data_dir=data_dir)
            info = await updater.check_for_updates()
            if info.update_available:
                return (
                    f'<div class="text-yellow-400">'
                    f"Доступне оновлення: v{info.latest_version} "
                    f"(поточна: v{info.current_version})"
                    f"</div>"
                )
            return f'<div class="text-green-400">v{info.current_version} — актуальна версія</div>'
        except Exception as e:
            return f'<div class="text-red-400">Помилка: {e}</div>'

    # ─── Login ───────────────────────────────────────────────────────
    @app.get("/login", response_class=HTMLResponse)
    async def login_page():
        return """
        <!DOCTYPE html>
        <html lang="uk">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Posipaka — Вхід</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-900 text-white min-h-screen flex items-center justify-center">
            <div class="bg-gray-800 p-8 rounded-xl shadow-lg w-96">
                <h1 class="text-2xl font-bold mb-6 text-center">🐾 Posipaka</h1>
                <form method="POST" action="/login">
                    <label class="block mb-2 text-sm">Пароль</label>
                    <input type="password" name="password"
                           class="w-full p-2 rounded bg-gray-700 border border-gray-600 mb-4"
                           autofocus required>
                    <button type="submit"
                            class="w-full p-2 bg-blue-600 hover:bg-blue-700 rounded font-bold">
                        Увійти
                    </button>
                </form>
            </div>
        </body>
        </html>
        """

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        password = form.get("password", "")
        client_ip = request.client.host if request.client else "unknown"

        lockout = auth.remaining_lockout_seconds(client_ip)
        if lockout > 0:
            return JSONResponse(
                {"detail": f"Заблоковано. Спробуйте через {lockout} секунд."},
                status_code=429,
            )

        if auth.verify_password(str(password), client_ip):
            # Session fixation prevention — invalidate old session
            old_token = request.cookies.get("posipaka_session")
            if old_token:
                auth.invalidate_session(old_token)
            token = auth.create_session(client_ip)
            nonce = getattr(request.state, "csp_nonce", "")
            response = HTMLResponse(
                f'<script nonce="{nonce}">window.location="/"</script>',
                status_code=200,
            )
            response.set_cookie(
                "posipaka_session",
                token,
                httponly=True,
                samesite="strict",
                secure=request.url.scheme == "https",
            )
            return response

        nonce = getattr(request.state, "csp_nonce", "")
        return HTMLResponse(
            f'<script nonce="{nonce}">alert("Невірний пароль");window.location="/login"</script>',
            status_code=401,
        )

    # ─── Setup Wizard (Web) ────────────────────────────────────────────
    from posipaka.setup.wizard_web import WebSetupWizard

    _web_wizard = WebSetupWizard(data_dir=_data_dir)

    @app.get("/setup", response_class=HTMLResponse)
    async def setup_page():
        """Web-based setup wizard — повний 12-кроковий flow."""
        return HTMLResponse(_web_wizard.render_full_page(step=1))

    @app.get("/setup/step/{step}", response_class=HTMLResponse)
    async def setup_step_get(step: int):
        """Get a specific wizard step (htmx partial)."""
        return HTMLResponse(_web_wizard.render_step(step))

    @app.post("/setup/step/{step}", response_class=HTMLResponse)
    async def setup_step_post(step: int, request: Request):
        """Process form data and render next step."""
        form = await request.form()
        form_dict = dict(form)
        # Handle multi-value fields (checkboxes)
        form_dict_multi = form.multi_items() if hasattr(form, "multi_items") else []
        multi_keys: dict[str, list] = {}
        for k, v in form_dict_multi:
            multi_keys.setdefault(k, []).append(v)
        for k, values in multi_keys.items():
            if len(values) > 1:
                form_dict[k] = values

        prev_step = step - 1
        _web_wizard.process_step(prev_step, form_dict)
        return HTMLResponse(_web_wizard.render_step(step, _web_wizard.config))

    @app.post("/setup/test-llm", response_class=HTMLResponse)
    async def setup_test_llm(request: Request):
        """Test LLM connection (htmx fragment)."""
        form = await request.form()
        provider = str(form.get("llm_provider", "anthropic"))
        api_key = str(form.get("llm_api_key", ""))
        return HTMLResponse(_web_wizard.test_llm(provider, api_key))

    @app.post("/setup/test-telegram", response_class=HTMLResponse)
    async def setup_test_telegram(request: Request):
        """Test Telegram token (htmx fragment)."""
        form = await request.form()
        token = str(form.get("telegram_token", ""))
        return HTMLResponse(_web_wizard.test_telegram(token))

    @app.post("/setup/save", response_class=HTMLResponse)
    async def setup_save(request: Request):
        """Save config and show done step."""
        form = await request.form()
        generate_docker = form.get("generate_docker") == "on"
        _web_wizard.save(generate_docker=generate_docker)
        return HTMLResponse(_web_wizard.render_step(12))

    def _tool_row(t: dict) -> str:
        icon = "✅" if t["enabled"] else "❌"
        name = t["name"]
        desc = t["description"][:60]
        return (
            '<div class="flex items-center gap-2">'
            f"<span>{icon}</span>"
            f'<span class="font-mono text-sm">{name}</span>'
            '<span class="text-gray-400 text-sm">'
            f"— {desc}</span></div>"
        )

    # ─── Dashboard ───────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        agent_status = agent.status.value if agent else "not_initialized"
        tools_count = len(agent.tools.list_tools()) if agent else 0
        cost_report = agent.cost_guard.get_daily_report() if agent else "N/A"
        nonce = getattr(request.state, "csp_nonce", "")

        return f"""
        <!DOCTYPE html>
        <html lang="uk">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Posipaka — Dashboard</title>
            <script nonce="{nonce}" src="https://cdn.tailwindcss.com"></script>
            <script nonce="{nonce}" src="https://unpkg.com/htmx.org@1.9.10"></script>
        </head>
        <body class="bg-gray-900 text-white min-h-screen p-8">
            <div class="max-w-4xl mx-auto">
                <h1 class="text-3xl font-bold mb-8">🐾 Posipaka Dashboard</h1>

                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
                    <div class="bg-gray-800 p-4 rounded-lg">
                        <div class="text-sm text-gray-400">Статус</div>
                        <div class="text-2xl font-bold text-green-400">{agent_status}</div>
                    </div>
                    <div class="bg-gray-800 p-4 rounded-lg">
                        <div class="text-sm text-gray-400">Інструменти</div>
                        <div class="text-2xl font-bold">{tools_count}</div>
                    </div>
                    <div class="bg-gray-800 p-4 rounded-lg">
                        <div class="text-sm text-gray-400">Витрати</div>
                        <div class="text-sm font-mono mt-1">{
            cost_report.replace(chr(10), "<br>")
        }</div>
                    </div>
                </div>

                <div class="bg-gray-800 p-6 rounded-lg mb-8">
                    <h2 class="text-xl font-bold mb-4">Інструменти</h2>
                    <div class="space-y-2">
                        {
            "".join(_tool_row(t) for t in (agent.tools.list_tools() if agent else []))
            or '<div class="text-gray-500">Немає інструментів</div>'
        }
                    </div>
                </div>

                <div class="bg-gray-800 p-6 rounded-lg mb-8"
                     id="update-section">
                    <h2 class="text-xl font-bold mb-4">Оновлення</h2>
                    <button hx-post="/api/v1/check-update"
                            hx-target="#update-result"
                            hx-indicator="#update-spinner"
                            class="px-4 py-2 bg-green-600 rounded hover:bg-green-700">
                        Перевірити оновлення
                    </button>
                    <span id="update-spinner"
                          class="htmx-indicator text-gray-400 ml-2">
                        Перевіряю...
                    </span>
                    <div id="update-result" class="mt-3 text-sm"></div>
                </div>

                <div class="bg-gray-800 p-6 rounded-lg">
                    <h2 class="text-xl font-bold mb-4">Швидкі дії</h2>
                    <div class="flex gap-4">
                        <a href="/api/v1/health"
                           class="px-4 py-2 bg-blue-600 rounded hover:bg-blue-700">
                            Health Check
                        </a>
                        <a href="/settings"
                           class="px-4 py-2 bg-purple-600 rounded hover:bg-purple-700">
                            Налаштування
                        </a>
                        <a href="/logout"
                           class="px-4 py-2 bg-gray-600 rounded hover:bg-gray-700">
                            Вийти
                        </a>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    @app.get("/logout")
    async def logout(request: Request):
        token = request.cookies.get("posipaka_session")
        if token:
            auth.invalidate_session(token)
        nonce = getattr(request.state, "csp_nonce", "")
        response = HTMLResponse(f'<script nonce="{nonce}">window.location="/login"</script>')
        response.delete_cookie("posipaka_session")
        return response

    # Explicit logout API endpoint
    @app.post("/api/v1/logout")
    async def api_logout(request: Request):
        """API logout — invalidate session token."""
        token = request.cookies.get("posipaka_session")
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if token:
            auth.invalidate_session(token)
        response = JSONResponse({"status": "logged_out"})
        response.delete_cookie("posipaka_session")
        return response

    # ─── Settings Page ─────────────────────────────────────────────────
    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        nonce = getattr(request.state, "csp_nonce", "")
        session_token = request.cookies.get("posipaka_session", "")
        csrf_token = auth.get_csrf_token(session_token) or ""

        # Read current values
        llm_provider = ""
        llm_model = ""
        llm_api_key_display = ""
        llm_api_key_raw = ""
        llm_temperature = 0.7
        llm_max_tokens = 4096
        soul_name = "Posipaka"
        soul_language = "auto"
        soul_timezone = "Europe/Kyiv"
        cost_daily = 5.0
        cost_per_request = 0.50
        cost_per_session = 2.0
        soul_md_content = ""
        user_md_content = ""
        memory_md_content = ""

        if agent:
            s = agent.settings
            llm_provider = s.llm.provider
            llm_model = s.llm.model
            raw_key = s.llm.api_key.get_secret_value()
            llm_api_key_raw = raw_key
            if raw_key:
                llm_api_key_display = (
                    raw_key[:4] + "..." + raw_key[-4:] if len(raw_key) > 8 else "****"
                )
            else:
                llm_api_key_display = ""
            llm_temperature = s.llm.temperature
            llm_max_tokens = s.llm.max_tokens
            soul_name = s.soul.name
            soul_language = s.soul.language
            soul_timezone = s.soul.timezone
            cost_daily = s.cost.daily_budget_usd
            cost_per_request = s.cost.per_request_max_usd
            cost_per_session = s.cost.per_session_max_usd

            if s.soul_md_path.exists():
                soul_md_content = s.soul_md_path.read_text(encoding="utf-8")
            if s.user_md_path.exists():
                user_md_content = s.user_md_path.read_text(encoding="utf-8")
            if agent.memory:
                memory_md_content = agent.memory.get_memory_md()

        providers = [
            "mistral",
            "anthropic",
            "openai",
            "ollama",
            "gemini",
            "groq",
            "deepseek",
            "xai",
        ]
        provider_options = "".join(
            f'<option value="{p}" {"selected" if p == llm_provider else ""}>{p}</option>'
            for p in providers
        )
        languages = [("uk", "Українська"), ("en", "English"), ("ru", "Русский"), ("auto", "Auto")]
        lang_options = "".join(
            f'<option value="{code}" {"selected" if code == soul_language else ""}>{label}</option>'
            for code, label in languages
        )

        # Build model options for current provider
        current_provider = llm_provider or "mistral"
        model_options_list = _PROVIDER_MODELS.get(current_provider, [("custom", "Custom")])
        model_options_html = "".join(
            f'<option value="{val}" {"selected" if val == llm_model else ""}>{label}</option>'
            for val, label in model_options_list
        )

        # Enabled channels
        enabled_channels: list[str] = []
        if agent:
            enabled_channels = agent.settings.enabled_channels
        if not enabled_channels:
            enabled_channels = ["cli"]

        # Telegram token
        telegram_token_display = ""
        if agent:
            try:
                telegram_token_display = agent.settings.telegram.token.get_secret_value()
            except Exception:
                telegram_token_display = ""

        # Channel checkboxes
        all_channels = ["telegram", "discord", "slack", "whatsapp", "signal"]
        channel_checkboxes = ""
        for ch in all_channels:
            checked = "checked" if ch in enabled_channels else ""
            label = ch.capitalize()
            channel_checkboxes += (
                f'<label class="flex items-center gap-3 cursor-pointer">'
                f'<input type="checkbox" name="channel_{ch}" value="{ch}" {checked} '
                f'class="w-4 h-4">'
                f"<span>{label}</span>"
                f"</label>"
            )

        tg_display = "block" if "telegram" in enabled_channels else "none"
        esc_tg_token = html.escape(telegram_token_display)

        # Model routing config
        data_dir_path = agent.settings.data_dir if agent else _data_dir
        routing_config: dict[str, Any] = {"mode": "single", "profiles": {}}
        router_path = data_dir_path / "model_router.json"
        if router_path.exists():
            try:
                routing_config = json.loads(router_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        routing_mode = routing_config.get("mode", "single")
        checked_single = "checked" if routing_mode == "single" else ""
        checked_auto = "checked" if routing_mode == "auto" else ""
        checked_advanced = "checked" if routing_mode == "advanced" else ""
        show_auto = "block" if routing_mode == "auto" else "none"
        show_advanced = "block" if routing_mode == "advanced" else "none"

        routing_profiles = routing_config.get("profiles", {})
        simple_selected = routing_profiles.get("simple", {}).get("model", "")
        default_selected = routing_profiles.get("default", {}).get("model", "")
        complex_selected = routing_profiles.get("complex", {}).get("model", "")

        simple_model_options = _all_model_options(simple_selected)
        default_model_options = _all_model_options(default_selected)
        complex_model_options = _all_model_options(complex_selected)

        adv_categories = [
            ("chat", "Чат (розмова)"),
            ("code", "Код (програмування)"),
            ("research", "Дослідження"),
            ("writing", "Написання текстів"),
            ("tools", "Використання інструментів"),
            ("reasoning", "Логіка та аналіз"),
        ]
        adv_selects_html = ""
        for cat_key, cat_name in adv_categories:
            cat_selected = routing_profiles.get(cat_key, {}).get("model", "")
            cat_opts = _all_model_options(cat_selected)
            adv_selects_html += (
                f"<div>"
                f'<label class="text-sm text-gray-400">{cat_name}</label>'
                f'<select name="model_{cat_key}" class="w-full p-2 rounded bg-gray-700 border border-gray-600">'
                f"{cat_opts}"
                f"</select>"
                f"</div>"
            )

        # SOUL.md structured fields
        soul_identity = _extract_md_field(soul_md_content, "identity", "")
        soul_style_value = _extract_md_field(soul_md_content, "style", "concise")
        soul_extra = _extract_md_field(soul_md_content, "extra", "")

        style_options_list = [
            ("concise", "Коротко та по суті"),
            ("detailed", "Розгорнуто і детально"),
            ("friendly", "Дружній і неформальний"),
            ("professional", "Професійний і формальний"),
        ]
        style_options = "".join(
            f'<option value="{v}" {"selected" if v == soul_style_value else ""}>{lbl}</option>'
            for v, lbl in style_options_list
        )

        soul_lang_options = "".join(
            f'<option value="{code}" {"selected" if code == soul_language else ""}>{label}</option>'
            for code, label in [
                ("uk", "Українська"),
                ("en", "English"),
                ("ru", "Русский"),
                ("auto", "Авто (мова запиту)"),
            ]
        )

        # USER.md structured fields
        user_name_val = _extract_md_field(user_md_content, "name", "")
        user_lang_val = _extract_md_field(user_md_content, "language", "")
        user_work_val = _extract_md_field(user_md_content, "work", "")
        user_prefs_val = _extract_md_field(user_md_content, "preferences", "")

        esc_soul = html.escape(soul_md_content)
        esc_user = html.escape(user_md_content)
        esc_memory = html.escape(memory_md_content)
        esc_api_key = html.escape(llm_api_key_raw)
        esc_api_key_display = html.escape(llm_api_key_display)
        esc_name = html.escape(soul_name)
        esc_tz = html.escape(soul_timezone)
        esc_soul_identity = html.escape(soul_identity)
        esc_soul_extra = html.escape(soul_extra)
        esc_user_name = html.escape(user_name_val)
        esc_user_lang = html.escape(user_lang_val)
        esc_user_work = html.escape(user_work_val)
        esc_user_prefs = html.escape(user_prefs_val)

        section_cls = "bg-gray-800 p-6 rounded-lg mb-6"
        input_cls = "w-full p-2 rounded bg-gray-700 border border-gray-600 text-white"
        btn_cls = "px-4 py-2 rounded font-bold text-sm"
        btn_save = f"{btn_cls} bg-blue-600 hover:bg-blue-700"
        btn_danger = f"{btn_cls} bg-red-600 hover:bg-red-700"
        btn_secondary = f"{btn_cls} bg-gray-600 hover:bg-gray-700"

        return f"""
        <!DOCTYPE html>
        <html lang="uk">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Posipaka — Налаштування</title>
            <script nonce="{nonce}" src="https://cdn.tailwindcss.com"></script>
            <script nonce="{nonce}" src="https://unpkg.com/htmx.org@1.9.10"></script>
            <style nonce="{nonce}">
                .htmx-indicator {{ opacity: 0; transition: opacity 200ms; }}
                .htmx-request .htmx-indicator, .htmx-request.htmx-indicator {{ opacity: 1; }}
            </style>
        </head>
        <body class="bg-gray-900 text-white min-h-screen p-8"
              hx-headers='{{"X-CSRF-Token": "{csrf_token}"}}'>
            <div class="max-w-4xl mx-auto">
                <div class="flex items-center justify-between mb-8">
                    <h1 class="text-3xl font-bold">Налаштування</h1>
                    <a href="/" class="{btn_secondary}">← Dashboard</a>
                </div>

                <!-- Section 1: LLM Settings -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">LLM</h2>
                    <form hx-post="/settings/llm" hx-target="#llm-result" hx-swap="innerHTML">
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Provider</label>
                                <select name="provider" id="llm-provider"
                                        id="llm-provider"
                                        class="{input_cls}">
                                    {provider_options}
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Model</label>
                                <select name="model" id="llm-model" class="{input_cls}">
                                    {model_options_html}
                                </select>
                            </div>
                        </div>
                        <div class="mb-4">
                            <label class="block text-sm text-gray-400 mb-1">API Key</label>
                            <div class="flex gap-2">
                                <input type="password" name="api_key" id="api-key-input"
                                       value="{esc_api_key}"
                                       placeholder="{esc_api_key_display}"
                                       class="{input_cls} flex-1">
                                <button type="button" id="api-key-toggle-btn" class="{btn_secondary}">
                                    <span id="api-key-toggle-text">Показати</span>
                                </button>
                            </div>
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">
                                    Temperature: <span id="temp-value">{llm_temperature}</span>
                                </label>
                                <input type="range" name="temperature" id="temp-slider"
                                       min="0" max="1" step="0.05"
                                       value="{llm_temperature}"
                                       class="w-full accent-blue-500">
                                <p class="text-xs text-gray-500 mt-1">
                                    0 = точні, передбачувані відповіді.
                                    1 = творчі, різноманітні.
                                    0.7 = баланс (рекомендовано).
                                </p>
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Max Tokens</label>
                                <input type="number" name="max_tokens" value="{llm_max_tokens}"
                                       min="100" max="200000" class="{input_cls}">
                                <p class="text-xs text-gray-500 mt-1">
                                    Максимальна довжина відповіді.
                                    4096 = ~3 сторінки тексту.
                                </p>
                            </div>
                        </div>
                        <div class="flex items-center gap-4">
                            <button type="submit" class="{btn_save}">Зберегти</button>
                            <span id="llm-result"></span>
                        </div>
                    </form>
                </div>

                <!-- Section: Model Routing -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">Розподіл моделей по задачах</h2>
                    <p class="text-gray-400 text-sm mb-4">
                        Виберіть режим: одна модель для всього, автоматичний вибір, або окрема модель для кожної категорії.
                    </p>
                    <form hx-post="/settings/routing" hx-target="#routing-result" hx-swap="innerHTML">
                        <div class="flex gap-4 mb-6">
                            <label class="flex items-center gap-2 cursor-pointer">
                                <input type="radio" name="routing_mode" value="single"
                                       {checked_single}>
                                <span>Одна модель</span>
                            </label>
                            <label class="flex items-center gap-2 cursor-pointer">
                                <input type="radio" name="routing_mode" value="auto"
                                       {checked_auto}>
                                <span>Автоматично</span>
                            </label>
                            <label class="flex items-center gap-2 cursor-pointer">
                                <input type="radio" name="routing_mode" value="advanced"
                                       {checked_advanced}>
                                <span>Розширений</span>
                            </label>
                        </div>

                        <div id="routing-auto" style="display: {show_auto}">
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div>
                                    <label class="text-sm text-gray-400">Прості запити (привіт, погода)</label>
                                    <select name="model_simple" class="w-full p-2 rounded bg-gray-700 border border-gray-600">
                                        {simple_model_options}
                                    </select>
                                </div>
                                <div>
                                    <label class="text-sm text-gray-400">Стандартні запити</label>
                                    <select name="model_default" class="w-full p-2 rounded bg-gray-700 border border-gray-600">
                                        {default_model_options}
                                    </select>
                                </div>
                                <div>
                                    <label class="text-sm text-gray-400">Складні (код, аналіз)</label>
                                    <select name="model_complex" class="w-full p-2 rounded bg-gray-700 border border-gray-600">
                                        {complex_model_options}
                                    </select>
                                </div>
                            </div>
                        </div>

                        <div id="routing-advanced" style="display: {show_advanced}">
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {adv_selects_html}
                            </div>
                        </div>

                        <div class="flex items-center gap-4 mt-4">
                            <button type="submit" class="{btn_save}">Зберегти</button>
                            <span id="routing-result"></span>
                        </div>
                    </form>
                </div>

                <!-- Section 2: SOUL.md -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">Особистість агента</h2>

                    <button type="button" hx-post="/settings/soul/wizard" hx-target="#soul-wizard-result"
                            class="mb-4 px-4 py-2 bg-purple-600 rounded hover:bg-purple-700 text-sm font-bold">
                        Налаштувати через діалог
                    </button>
                    <div id="soul-wizard-result" class="mb-4"></div>

                    <form hx-post="/settings/soul" hx-target="#soul-result" hx-swap="innerHTML">
                        <div class="space-y-4 mb-4">
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Як агент себе називає</label>
                                <input type="text" name="soul_identity"
                                       value="{esc_soul_identity}"
                                       placeholder="Я Posipaka — персональний AI-асистент"
                                       class="{input_cls}">
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Мова за замовчуванням</label>
                                <select name="soul_language" class="{input_cls}">
                                    {soul_lang_options}
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Стиль відповідей</label>
                                <select name="soul_style" class="{input_cls}">
                                    {style_options}
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Додаткові інструкції (вільний текст)</label>
                                <textarea name="soul_extra" rows="4"
                                          placeholder="Наприклад: Завжди пропонуй альтернативи. Не використовуй емодзі."
                                          class="{input_cls}">{esc_soul_extra}</textarea>
                            </div>
                        </div>

                        <details class="mb-4">
                            <summary class="text-sm text-gray-400 cursor-pointer">Редагувати SOUL.md напряму (для досвідчених)</summary>
                            <textarea name="soul_raw" rows="10"
                                      class="{input_cls} mt-2 font-mono text-sm">{esc_soul}</textarea>
                        </details>

                        <div class="flex items-center gap-4">
                            <button type="submit" class="{btn_save}">Зберегти</button>
                            <span id="soul-result"></span>
                        </div>
                    </form>
                </div>

                <!-- Section 3: USER.md -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">Профіль користувача</h2>

                    <button type="button" hx-post="/settings/user/wizard" hx-target="#user-wizard-result"
                            class="mb-4 px-4 py-2 bg-purple-600 rounded hover:bg-purple-700 text-sm font-bold">
                        Заповнити через діалог
                    </button>
                    <div id="user-wizard-result" class="mb-4"></div>

                    <form hx-post="/settings/user" hx-target="#user-result" hx-swap="innerHTML">
                        <div class="space-y-4 mb-4">
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-gray-400 mb-1">Ваше ім'я</label>
                                    <input type="text" name="user_name"
                                           value="{esc_user_name}"
                                           placeholder="Як до вас звертатися"
                                           class="{input_cls}">
                                </div>
                                <div>
                                    <label class="block text-sm text-gray-400 mb-1">Мова спілкування</label>
                                    <input type="text" name="user_language"
                                           value="{esc_user_lang}"
                                           placeholder="Українська"
                                           class="{input_cls}">
                                </div>
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Сфера діяльності</label>
                                <input type="text" name="user_work"
                                       value="{esc_user_work}"
                                       placeholder="Наприклад: розробник, маркетолог, студент"
                                       class="{input_cls}">
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Вподобання та особливості</label>
                                <textarea name="user_preferences" rows="3"
                                          placeholder="Наприклад: люблю каву, працюю вночі, вивчаю Python"
                                          class="{input_cls}">{esc_user_prefs}</textarea>
                            </div>
                        </div>

                        <details class="mb-4">
                            <summary class="text-sm text-gray-400 cursor-pointer">Редагувати USER.md напряму</summary>
                            <textarea name="user_raw" rows="8"
                                      class="{input_cls} mt-2 font-mono text-sm">{esc_user}</textarea>
                        </details>

                        <div class="flex items-center gap-4">
                            <button type="submit" class="{btn_save}">Зберегти</button>
                            <span id="user-result"></span>
                        </div>
                    </form>
                </div>

                <!-- Section 4: Agent Settings -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">Агент</h2>
                    <form hx-post="/settings/agent" hx-target="#agent-result" hx-swap="innerHTML">
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Ім'я агента</label>
                                <input type="text" name="name" value="{esc_name}" class="{input_cls}">
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Мова</label>
                                <select name="language" class="{input_cls}">
                                    {lang_options}
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Часовий пояс</label>
                                <input type="text" name="timezone" value="{esc_tz}" class="{input_cls}">
                            </div>
                        </div>
                        <div class="flex items-center gap-4">
                            <button type="submit" class="{btn_save}">Зберегти</button>
                            <span id="agent-result"></span>
                        </div>
                    </form>
                </div>

                <!-- Section: Messengers -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">Месенджери</h2>
                    <p class="text-gray-400 text-sm mb-4">
                        Виберіть через які месенджери буде працювати агент.
                    </p>
                    <form hx-post="/settings/channels" hx-target="#channels-result" hx-swap="innerHTML">
                        <div class="space-y-3 mb-4">
                            {channel_checkboxes}
                        </div>

                        <div class="p-3 bg-gray-700 rounded mb-4" id="telegram-config"
                             style="display: {tg_display}">
                            <label class="block text-sm text-gray-400 mb-1">Telegram Bot Token</label>
                            <input type="password" name="telegram_token"
                                   value="{esc_tg_token}"
                                   class="{input_cls}">
                        </div>

                        <div class="flex items-center gap-4">
                            <button type="submit" class="{btn_save}">Зберегти</button>
                            <span id="channels-result"></span>
                        </div>
                    </form>
                </div>

                <!-- Section 5: Cost Settings -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">Витрати</h2>
                    <form hx-post="/settings/cost" hx-target="#cost-result" hx-swap="innerHTML">
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Денний бюджет (USD)</label>
                                <input type="number" name="daily_budget" value="{cost_daily}"
                                       step="0.1" min="0" class="{input_cls}">
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Макс. за запит (USD)</label>
                                <input type="number" name="per_request_max" value="{cost_per_request}"
                                       step="0.01" min="0" class="{input_cls}">
                            </div>
                            <div>
                                <label class="block text-sm text-gray-400 mb-1">Макс. за сесію (USD)</label>
                                <input type="number" name="per_session_max" value="{cost_per_session}"
                                       step="0.1" min="0" class="{input_cls}">
                            </div>
                        </div>
                        <div class="flex items-center gap-4">
                            <button type="submit" class="{btn_save}">Зберегти</button>
                            <span id="cost-result"></span>
                        </div>
                    </form>
                </div>

                <!-- Section 6: Memory -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">Пам'ять (MEMORY.md)</h2>
                    <textarea readonly rows="10"
                              class="{input_cls} mb-4 font-mono text-sm overflow-y-auto">{esc_memory}</textarea>
                    <div class="flex items-center gap-4">
                        <button hx-delete="/settings/memory/clear" hx-target="#memory-result"
                                hx-confirm="Ви впевнені? Всю пам'ять буде очищено."
                                class="{btn_danger}">Очистити пам'ять</button>
                        <button hx-post="/settings/memory/compact" hx-target="#memory-result"
                                class="{btn_secondary}">Стиснути пам'ять</button>
                        <span id="memory-result"></span>
                    </div>
                </div>

                <!-- Section 7: Security -->
                <div class="{section_cls}">
                    <h2 class="text-xl font-bold mb-4">Безпека</h2>
                    <div class="flex flex-wrap items-start gap-4 mb-4">
                        <button hx-post="/settings/reset-password" hx-target="#security-result"
                                hx-confirm="Згенерувати новий пароль? Поточну сесію буде збережено."
                                class="{btn_danger}">Скинути пароль</button>
                        <button hx-get="/settings/audit" hx-target="#audit-log-content"
                                class="{btn_secondary}">Переглянути Audit Log</button>
                        <button hx-post="/settings/audit/verify" hx-target="#security-result"
                                class="{btn_secondary}">Перевірити цілісність</button>
                        <span id="security-result"></span>
                    </div>
                    <div id="audit-log-content"></div>
                </div>

            </div>

            <script nonce="{nonce}">
                // API Key show/hide
                document.getElementById('api-key-toggle-btn')
                    .addEventListener('click', function() {{
                    var inp = document.getElementById('api-key-input');
                    var txt = document.getElementById('api-key-toggle-text');
                    if (inp.type === 'password') {{
                        inp.type = 'text';
                        txt.textContent = 'Сховати';
                    }} else {{
                        inp.type = 'password';
                        txt.textContent = 'Показати';
                    }}
                }});

                // Temperature slider
                document.getElementById('temp-slider')
                    .addEventListener('input', function() {{
                    document.getElementById('temp-value').textContent = this.value;
                }});

                // Routing mode toggle
                document.querySelectorAll('input[name="routing_mode"]')
                    .forEach(function(radio) {{
                    radio.addEventListener('change', function() {{
                        var mode = this.value;
                        var autoEl = document.getElementById('routing-auto');
                        var advEl = document.getElementById('routing-advanced');
                        if (autoEl) autoEl.style.display =
                            (mode === 'auto') ? 'block' : 'none';
                        if (advEl) advEl.style.display =
                            (mode === 'advanced') ? 'block' : 'none';
                    }});
                }});

                // Provider change -> update model dropdown
                var provSelect = document.getElementById('llm-provider');
                if (provSelect) {{
                    provSelect.addEventListener('change', function() {{
                        htmx.ajax('GET',
                            '/api/v1/models/' + this.value,
                            '#llm-model');
                    }});
                }}

                // Telegram config show/hide
                document.addEventListener('change', function(e) {{
                    if (e.target && e.target.name === 'channel_telegram') {{
                        var cfg = document.getElementById('telegram-config');
                        if (cfg) cfg.style.display =
                            e.target.checked ? 'block' : 'none';
                    }}
                }});
            </script>
        </body>
        </html>
        """

    # ─── Settings POST routes ─────────────────────────────────────────

    @app.post("/settings/llm", response_class=HTMLResponse)
    async def settings_llm(request: Request):
        form = await request.form()
        data_dir_path = agent.settings.data_dir if agent else _data_dir
        _update_env(
            data_dir_path,
            {
                "LLM_PROVIDER": str(form.get("provider", "")),
                "LLM_MODEL": str(form.get("model", "")),
                "LLM_API_KEY": str(form.get("api_key", "")),
                "LLM_TEMPERATURE": str(form.get("temperature", "0.7")),
                "LLM_MAX_TOKENS": str(form.get("max_tokens", "4096")),
            },
        )
        if agent:
            agent.audit.log("settings_llm_updated", {"provider": str(form.get("provider", ""))})
        return '<span class="text-green-400">Збережено! Зміни діють після перезапуску.</span>'

    @app.post("/settings/soul", response_class=HTMLResponse)
    async def settings_soul(request: Request):
        form = await request.form()
        soul_raw = str(form.get("soul_raw", "")).strip()
        if soul_raw:
            content = soul_raw
        else:
            # Build from structured fields
            identity = str(form.get("soul_identity", "")).strip()
            language = str(form.get("soul_language", "auto")).strip()
            style = str(form.get("soul_style", "concise")).strip()
            extra = str(form.get("soul_extra", "")).strip()

            lang_map = {
                "uk": "Українська",
                "en": "English",
                "ru": "Русский",
                "auto": "Авто (мова запиту)",
            }
            style_map = {
                "concise": "Коротко та по суті",
                "detailed": "Розгорнуто і детально",
                "friendly": "Дружній і неформальний",
                "professional": "Професійний і формальний",
            }

            parts = [f"# {html.escape(identity or 'Posipaka')} — Особистість\n"]
            parts.append(f"## Хто я\n{identity or 'Я Posipaka — персональний AI-асистент.'}\n")
            parts.append(f"## Мова\n{lang_map.get(language, language)}\n")
            parts.append(f"## Стиль\n{style_map.get(style, style)}\n")
            if extra:
                parts.append(f"## Обмеження\n{extra}\n")
            content = "\n".join(parts)

        if agent:
            agent.settings.soul_md_path.write_text(content, encoding="utf-8")
            agent.audit.log("settings_soul_md_updated", {})
        return '<span class="text-green-400">Збережено! Зміни діють негайно.</span>'

    @app.post("/settings/user", response_class=HTMLResponse)
    async def settings_user(request: Request):
        form = await request.form()
        user_raw = str(form.get("user_raw", "")).strip()
        if user_raw:
            content = user_raw
        else:
            # Build from structured fields
            name = str(form.get("user_name", "")).strip()
            language = str(form.get("user_language", "")).strip()
            work = str(form.get("user_work", "")).strip()
            preferences = str(form.get("user_preferences", "")).strip()

            parts = ["# Профіль користувача\n"]
            if name:
                parts.append(f"## Ім'я\n{name}\n")
            if language:
                parts.append(f"## Мова\n{language}\n")
            if work:
                parts.append(f"## Сфера\n{work}\n")
            if preferences:
                parts.append(f"## Вподобання\n{preferences}\n")
            content = "\n".join(parts)

        if agent:
            agent.settings.user_md_path.write_text(content, encoding="utf-8")
            agent.audit.log("settings_user_md_updated", {})
        return '<span class="text-green-400">Збережено! Зміни діють негайно.</span>'

    @app.post("/settings/agent", response_class=HTMLResponse)
    async def settings_agent(request: Request):
        form = await request.form()
        data_dir_path = agent.settings.data_dir if agent else _data_dir
        _update_env(
            data_dir_path,
            {
                "SOUL_NAME": str(form.get("name", "")),
                "SOUL_LANGUAGE": str(form.get("language", "")),
                "SOUL_TIMEZONE": str(form.get("timezone", "")),
            },
        )
        if agent:
            agent.audit.log("settings_agent_updated", {"name": str(form.get("name", ""))})
        return '<span class="text-green-400">Збережено! Зміни діють після перезапуску.</span>'

    @app.post("/settings/cost", response_class=HTMLResponse)
    async def settings_cost(request: Request):
        form = await request.form()
        data_dir_path = agent.settings.data_dir if agent else _data_dir
        _update_env(
            data_dir_path,
            {
                "COST_DAILY_BUDGET_USD": str(form.get("daily_budget", "5.0")),
                "COST_PER_REQUEST_MAX_USD": str(form.get("per_request_max", "0.50")),
                "COST_PER_SESSION_MAX_USD": str(form.get("per_session_max", "2.0")),
            },
        )
        if agent:
            agent.audit.log("settings_cost_updated", {})
        return '<span class="text-green-400">Збережено! Зміни діють після перезапуску.</span>'

    @app.delete("/settings/memory/clear", response_class=HTMLResponse)
    async def settings_memory_clear(request: Request):
        if agent and agent.memory:
            agent.memory.update_memory_md("")
            agent.audit.log("memory_cleared", {})
        return '<span class="text-green-400">Пам\'ять очищено.</span>'

    @app.post("/settings/memory/compact", response_class=HTMLResponse)
    async def settings_memory_compact(request: Request):
        if agent and agent.memory:
            result = agent.memory.compact_memory_md()
            agent.audit.log("memory_compacted", {})
            esc_result = html.escape(result)
            return f'<span class="text-green-400">{esc_result}</span>'
        return '<span class="text-yellow-400">Пам\'ять не ініціалізовано.</span>'

    @app.post("/settings/reset-password", response_class=HTMLResponse)
    async def settings_reset_password(request: Request):
        new_password = auth.setup_password()
        if agent:
            agent.audit.log("password_reset_via_web", {})
        esc_pw = html.escape(new_password)
        return (
            f'<span class="text-green-400">Новий пароль: '
            f'<code class="bg-gray-700 px-2 py-1 rounded select-all">{esc_pw}</code>'
            f" — збережіть його!</span>"
        )

    @app.get("/settings/audit", response_class=HTMLResponse)
    async def settings_audit(request: Request):
        entries: list[str] = []
        if agent:
            audit_path = agent.settings.audit_log_path
            if audit_path.exists():
                lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
                last_20 = lines[-20:] if len(lines) > 20 else lines
                for line in reversed(last_20):
                    try:
                        record = json.loads(line)
                        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.get("ts", 0)))
                        event = html.escape(str(record.get("event", "")))
                        data_str = html.escape(
                            json.dumps(record.get("data", {}), ensure_ascii=False)[:120]
                        )
                        entries.append(
                            f'<tr class="border-b border-gray-700">'
                            f'<td class="px-2 py-1 text-sm text-gray-400 whitespace-nowrap">{ts}</td>'
                            f'<td class="px-2 py-1 text-sm font-mono">{event}</td>'
                            f'<td class="px-2 py-1 text-sm text-gray-400 truncate max-w-xs">{data_str}</td>'
                            f"</tr>"
                        )
                    except json.JSONDecodeError:
                        continue

        if not entries:
            return '<div class="text-gray-500 mt-2">Audit log порожній.</div>'

        rows = "".join(entries)
        return (
            '<div class="mt-4 overflow-x-auto">'
            '<table class="w-full text-left">'
            '<thead><tr class="border-b border-gray-600">'
            '<th class="px-2 py-1 text-sm text-gray-400">Час</th>'
            '<th class="px-2 py-1 text-sm text-gray-400">Подія</th>'
            '<th class="px-2 py-1 text-sm text-gray-400">Дані</th>'
            "</tr></thead>"
            f"<tbody>{rows}</tbody>"
            "</table></div>"
        )

    @app.post("/settings/audit/verify", response_class=HTMLResponse)
    async def settings_audit_verify(request: Request):
        if not agent:
            return '<span class="text-yellow-400">Агент не ініціалізовано.</span>'
        valid, count, msg = agent.audit.verify_integrity()
        esc_msg = html.escape(msg)
        if valid:
            return f'<span class="text-green-400">Цілісність OK: {count} записів. {esc_msg}</span>'
        return (
            f'<span class="text-red-400">ПОРУШЕННЯ: {esc_msg} ({count} записів до помилки)</span>'
        )

    # ─── Models API ───────────────────────────────────────────────────
    @app.get("/api/v1/models/{provider}", response_class=HTMLResponse)
    async def get_models(provider: str):
        """Return model <option> elements for a provider (htmx partial)."""
        opts = _PROVIDER_MODELS.get(provider, [("custom", "Custom")])
        return "".join(f'<option value="{val}">{label}</option>' for val, label in opts)

    # ─── Routing settings ─────────────────────────────────────────────
    @app.post("/settings/routing", response_class=HTMLResponse)
    async def save_routing(request: Request):
        form = await request.form()
        mode = str(form.get("routing_mode", "single"))

        profiles: dict[str, dict[str, Any]] = {}
        if mode == "single":
            model_val = str(form.get("model", "mistral-large-latest"))
            profiles["default"] = {
                "model": model_val,
                "temperature": 0.7,
                "max_tokens": 4096,
            }
        elif mode == "auto":
            for tier in ("simple", "default", "complex"):
                model_val = str(form.get(f"model_{tier}", ""))
                if model_val:
                    profiles[tier] = {"model": model_val, "temperature": 0.7, "max_tokens": 4096}
        elif mode == "advanced":
            for cat in ("chat", "code", "research", "writing", "tools", "reasoning"):
                model_val = str(form.get(f"model_{cat}", ""))
                if model_val:
                    profiles[cat] = {"model": model_val, "temperature": 0.7, "max_tokens": 4096}

        config = {"mode": mode, "profiles": profiles}
        data_dir_path = agent.settings.data_dir if agent else _data_dir
        config_path = data_dir_path / "model_router.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        if agent:
            agent.audit.log("settings_routing_updated", {"mode": mode})
        return '<span class="text-green-400">Збережено! Діє після перезапуску.</span>'

    # ─── Channels settings ─────────────────────────────────────────────
    @app.post("/settings/channels", response_class=HTMLResponse)
    async def save_channels(request: Request):
        form = await request.form()
        channels = []
        for ch in ("telegram", "discord", "slack", "whatsapp", "signal"):
            if form.get(f"channel_{ch}"):
                channels.append(ch)
        if not channels:
            channels = ["cli"]

        data_dir_path = agent.settings.data_dir if agent else _data_dir
        _update_env(
            data_dir_path,
            {
                "ENABLED_CHANNELS": json.dumps(channels),
            },
        )

        # Save telegram token if provided
        tg_token = str(form.get("telegram_token", ""))
        if tg_token and tg_token != "***":
            _update_env(data_dir_path, {"TELEGRAM_TOKEN": tg_token})

        if agent:
            agent.audit.log("settings_channels_updated", {"channels": channels})
        return '<span class="text-green-400">Збережено! Діє після перезапуску.</span>'

    # ─── Soul wizard ───────────────────────────────────────────────────
    @app.post("/settings/soul/wizard", response_class=HTMLResponse)
    async def soul_wizard(request: Request):
        """Start AI-guided personality setup — step 0."""
        return _soul_wizard_step(0, [])

    @app.post("/settings/soul/wizard/step", response_class=HTMLResponse)
    async def soul_wizard_step(request: Request):
        """Process wizard step via htmx."""
        form = await request.form()
        step = int(form.get("step", "0"))
        answer = str(form.get("answer", ""))
        # Collect previous answers
        prev = []
        for i in range(step):
            prev.append(str(form.get(f"a{i}", "")))
        if answer:
            prev.append(answer)
        return HTMLResponse(_soul_wizard_step(step + 1, prev))

    def _soul_wizard_step(step: int, answers: list[str]) -> str:
        questions = [
            'Як ви хочете щоб агент звертався? (на "ти" чи на "ви"?)',
            "Який стиль відповідей? (коротко / детально / дружній / професійний)",
            "Чого агент НЕ повинен робити?",
            "Як звати агента?",
        ]
        # Build chat history
        history = ""
        for i, ans in enumerate(answers):
            if i < len(questions):
                q = questions[i]
                history += (
                    f'<div class="text-blue-400 text-sm">{q}</div>'
                    f'<div class="text-gray-300 text-sm">Ви: {ans}</div>'
                )

        # Hidden fields for previous answers
        hidden = "".join(
            f'<input type="hidden" name="a{i}" value="{a}">' for i, a in enumerate(answers)
        )

        if step < len(questions):
            # Show next question
            return f'''
            <div class="bg-gray-700 p-4 rounded space-y-3">
                <div class="space-y-2">{history}</div>
                <div class="text-blue-400 text-sm">{questions[step]}</div>
                <form hx-post="/settings/soul/wizard/step"
                      hx-target="#soul-wizard-result" class="flex gap-2">
                    {hidden}
                    <input type="hidden" name="step" value="{step}">
                    <input type="text" name="answer" autofocus
                           placeholder="Ваша відповідь..."
                           class="flex-1 p-2 rounded bg-gray-600 border border-gray-500 text-sm">
                    <button type="submit"
                            class="px-3 py-2 bg-purple-600 rounded hover:bg-purple-700 text-sm">
                        Далі
                    </button>
                </form>
            </div>'''
        else:
            # All answers collected — build SOUL.md
            formality = answers[0] if len(answers) > 0 else "ви"
            style = answers[1] if len(answers) > 1 else "коротко"
            restrictions = answers[2] if len(answers) > 2 else ""
            name = answers[3] if len(answers) > 3 else "Posipaka"
            soul = (
                f"# {name} — Особистість\n\n"
                f"## Хто я\n"
                f"Я {name} — персональний AI-асистент.\n\n"
                f"## Звернення\n{formality}\n\n"
                f"## Стиль\n{style}\n\n"
            )
            if restrictions:
                soul += f"## Обмеження\n{restrictions}\n"

            # Save directly
            data_dir = Path.home() / ".posipaka"
            if agent:
                data_dir = agent.settings.data_dir
            soul_path = data_dir / "SOUL.md"
            soul_path.write_text(soul, encoding="utf-8")

            return f'''
            <div class="bg-gray-700 p-4 rounded space-y-3">
                <div class="space-y-2">{history}</div>
                <div class="text-green-400 text-sm font-bold">
                    Готово! Особистість "{name}" налаштована.
                </div>
            </div>'''

    # ─── User wizard ───────────────────────────────────────────────────
    @app.post("/settings/user/wizard", response_class=HTMLResponse)
    async def user_wizard(request: Request):
        """Start AI-guided user profile setup — step 0."""
        return _user_wizard_step(0, [])

    @app.post("/settings/user/wizard/step", response_class=HTMLResponse)
    async def user_wizard_step(request: Request):
        """Process user wizard step via htmx."""
        form = await request.form()
        step = int(form.get("step", "0"))
        answer = str(form.get("answer", ""))
        prev = []
        for i in range(step):
            prev.append(str(form.get(f"a{i}", "")))
        if answer:
            prev.append(answer)
        return HTMLResponse(_user_wizard_step(step + 1, prev))

    def _user_wizard_step(step: int, answers: list[str]) -> str:
        questions = [
            "Як вас звати?",
            "Чим ви займаєтесь?",
            "Яка ваша мова спілкування?",
            "Що вам подобається? (хобі, інтереси)",
        ]
        history = ""
        for i, ans in enumerate(answers):
            if i < len(questions):
                history += (
                    f'<div class="text-blue-400 text-sm">{questions[i]}</div>'
                    f'<div class="text-gray-300 text-sm">Ви: {ans}</div>'
                )

        hidden = "".join(
            f'<input type="hidden" name="a{i}" value="{a}">' for i, a in enumerate(answers)
        )

        if step < len(questions):
            return f'''
            <div class="bg-gray-700 p-4 rounded space-y-3">
                <div class="space-y-2">{history}</div>
                <div class="text-blue-400 text-sm">{questions[step]}</div>
                <form hx-post="/settings/user/wizard/step"
                      hx-target="#user-wizard-result" class="flex gap-2">
                    {hidden}
                    <input type="hidden" name="step" value="{step}">
                    <input type="text" name="answer" autofocus
                           placeholder="Ваша відповідь..."
                           class="flex-1 p-2 rounded bg-gray-600 border border-gray-500 text-sm">
                    <button type="submit"
                            class="px-3 py-2 bg-purple-600 rounded hover:bg-purple-700 text-sm">
                        Далі
                    </button>
                </form>
            </div>'''
        else:
            u_name = answers[0] if answers else ""
            u_work = answers[1] if len(answers) > 1 else ""
            u_lang = answers[2] if len(answers) > 2 else ""
            u_prefs = answers[3] if len(answers) > 3 else ""
            user_md = (
                f"# Профіль користувача\n\n"
                f"## Ім'я\n{u_name}\n\n"
                f"## Сфера\n{u_work}\n\n"
                f"## Мова\n{u_lang}\n\n"
                f"## Вподобання\n{u_prefs}\n"
            )
            data_dir = Path.home() / ".posipaka"
            if agent:
                data_dir = agent.settings.data_dir
            (data_dir / "USER.md").write_text(user_md, encoding="utf-8")

            return f'''
            <div class="bg-gray-700 p-4 rounded space-y-3">
                <div class="space-y-2">{history}</div>
                <div class="text-green-400 text-sm font-bold">
                    Готово! Профіль "{u_name}" збережено.
                </div>
            </div>'''

    # ─── Metrics ─────────────────────────────────────────────────────
    @app.get("/api/v1/metrics")
    async def metrics():
        """Prometheus-compatible metrics export."""
        try:
            from posipaka.core.observability import MetricsRegistry

            registry = MetricsRegistry.instance()
            from starlette.responses import Response

            return Response(
                content=registry.export_prometheus(),
                media_type="text/plain; version=0.0.4",
            )
        except Exception:
            return JSONResponse({"metrics": "not available"})

    # ─── API ─────────────────────────────────────────────────────────
    @app.get("/api/v1/config")
    async def api_config():
        """Поточна конфігурація (без секретів)."""
        if not agent:
            return {"error": "Agent not initialized"}
        s = agent.settings
        return {
            "llm": {
                "provider": s.llm.provider,
                "model": s.llm.model,
                "max_tokens": s.llm.max_tokens,
            },
            "channels": s.enabled_channels,
            "security": {
                "injection_threshold": s.security.injection_threshold,
                "max_input_length": s.security.max_input_length,
            },
            "cost": {
                "daily_budget_usd": s.cost.daily_budget_usd,
                "per_request_max_usd": s.cost.per_request_max_usd,
            },
            "soul": {
                "name": s.soul.name,
                "language": s.soul.language,
                "timezone": s.soul.timezone,
            },
        }

    @app.get("/api/v1/status")
    async def api_status():
        if not agent:
            return {"status": "not_initialized"}
        return {
            "status": agent.status.value,
            "tools": len(agent.tools.list_tools()),
            "cost": agent.cost_guard.get_daily_report(),
        }

    @app.get("/api/v1/tools")
    async def api_tools():
        if not agent:
            return []
        return agent.tools.list_tools()

    @app.get("/api/v1/audit")
    async def api_audit():
        if not agent:
            return {"valid": False, "message": "Agent not initialized"}
        valid, count, msg = agent.audit.verify_integrity()
        return {"valid": valid, "count": count, "message": msg}

    # ─── GDPR: Data Export & Delete ─────────────────────────────────
    @app.get("/api/v1/export-my-data")
    async def export_data():
        """GDPR: Експорт всіх даних користувача."""
        if not agent or not agent.memory:
            return {"error": "Agent not initialized"}

        data = {
            "soul_md": "",
            "user_md": "",
            "memory_md": "",
            "sessions": [],
        }

        soul = agent.settings.soul_md_path
        if soul.exists():
            data["soul_md"] = soul.read_text(encoding="utf-8")
        user = agent.settings.user_md_path
        if user.exists():
            data["user_md"] = user.read_text(encoding="utf-8")
        if agent.memory:
            data["memory_md"] = agent.memory.get_memory_md()

        return data

    @app.delete("/api/v1/delete-my-data")
    async def delete_data():
        """GDPR: Видалення всіх даних користувача."""
        if not agent:
            return {"error": "Agent not initialized"}

        # Clear memory
        if agent.memory:
            agent.memory.update_memory_md("")

        # Clear user profile
        user = agent.settings.user_md_path
        if user.exists():
            user.write_text("# Профіль видалено\n", encoding="utf-8")

        agent.audit.log("gdpr_data_deleted", {})
        return {"status": "deleted", "message": "Всі дані видалено"}

    return app
