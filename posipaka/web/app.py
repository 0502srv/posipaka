"""FastAPI Web Application — Setup UI + Dashboard + API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from posipaka.web.auth import AuthManager, AuthMiddleware
from posipaka.web.middleware import RequestValidationMiddleware


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

        logger.info(f"Web UI password (first run): {password}")
        logger.info("Save this password! It won't be shown again.")

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
