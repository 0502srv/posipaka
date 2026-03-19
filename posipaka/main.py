"""Posipaka CLI — головна точка входу."""

from __future__ import annotations

import asyncio
import sys

import click
from loguru import logger

from posipaka import __version__


def setup_logging(verbose: bool = False) -> None:
    """Налаштування loguru."""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level>"
            " | <cyan>{name}</cyan> — <level>{message}</level>"
        ),
    )


@click.group()
@click.version_option(version=__version__, prog_name="posipaka")
@click.option("-v", "--verbose", is_flag=True, help="Детальний вивід")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Posipaka — персональний AI-агент для месенджерів."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@cli.command()
@click.pass_context
def start(ctx: click.Context) -> None:
    """Запустити агента."""
    from posipaka.config.settings import get_settings

    settings = get_settings()
    logger.info(f"Posipaka v{__version__} запускається...")

    async def _run() -> None:
        from posipaka.core.agent import Agent

        agent = Agent(settings)
        await agent.initialize()
        logger.info(f"LLM: {agent.settings.llm.provider}/{agent.settings.llm.model}")
        try:
            tasks = []

            # Start web server
            from posipaka.web.app import create_app

            app = create_app(agent, settings.data_dir)
            import uvicorn

            config = uvicorn.Config(
                app,
                host=settings.web.host,
                port=settings.web.port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            tasks.append(asyncio.create_task(server.serve()))
            logger.info(f"Web UI: http://{settings.web.host}:{settings.web.port}")

            # Start messenger channels
            from posipaka.core.gateway import MessageGateway

            gateway = MessageGateway(agent, settings)
            tasks.append(asyncio.create_task(gateway.start()))

            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("Зупинка...")
        finally:
            await agent.shutdown()

    asyncio.run(_run())


@cli.command()
def setup() -> None:
    """Запустити майстер налаштування."""
    from posipaka.setup.wizard import SetupWizard

    wizard = SetupWizard()
    wizard.run()


@cli.command()
@click.pass_context
def chat(ctx: click.Context) -> None:
    """Інтерактивний CLI-чат для тестування."""
    from posipaka.config.settings import get_settings

    settings = get_settings()

    async def _run() -> None:
        from posipaka.channels.cli.repl import CLIChannel
        from posipaka.core.agent import Agent

        agent = Agent(settings)
        await agent.initialize()
        try:
            repl = CLIChannel(agent, settings)
            await repl.start()
        finally:
            await agent.shutdown()

    asyncio.run(_run())


@cli.command()
def status() -> None:
    """Показати статус агента."""
    click.echo(f"Posipaka v{__version__}")
    click.echo("Статус: не запущено")


@cli.command()
def doctor() -> None:
    """Діагностика системи."""
    from posipaka.utils.doctor import format_doctor_report, run_doctor

    checks = run_doctor()
    click.echo(format_doctor_report(checks))


@cli.command("reset-password")
def reset_password() -> None:
    """Скинути пароль Web UI та показати новий."""
    from pathlib import Path

    from posipaka.web.auth import AuthManager

    data_dir = Path.home() / ".posipaka"
    auth = AuthManager(data_dir)

    # Видалити старий пароль
    pw_file = data_dir / ".web_password"
    if pw_file.exists():
        pw_file.unlink()

    # Згенерувати новий
    password = auth.setup_password()
    click.echo("=" * 50)
    click.echo(f"  NEW WEB UI PASSWORD: {password}")
    click.echo("=" * 50)
    click.echo("  Restart the agent for the new password to take effect.")


@cli.group()
def config() -> None:
    """Керування конфігурацією."""


@config.command("show")
def config_show() -> None:
    """Показати поточну конфігурацію."""
    from posipaka.config.settings import get_settings

    settings = get_settings()
    click.echo(settings.model_dump_json(indent=2))


@cli.group()
def channels() -> None:
    """Керування каналами месенджерів."""


@channels.command("list")
def channels_list() -> None:
    """Список підключених каналів."""
    from posipaka.config.settings import get_settings

    settings = get_settings()
    enabled = settings.enabled_channels
    all_channels = {
        "telegram": "Telegram Bot",
        "discord": "Discord Bot",
        "slack": "Slack Bot (Socket Mode)",
        "whatsapp": "WhatsApp (Twilio)",
        "signal": "Signal (signal-cli)",
        "cli": "CLI REPL",
    }
    for name, desc in all_channels.items():
        status = "ON" if name in enabled else "OFF"
        icon = "+" if name in enabled else "-"
        click.echo(f"  [{icon}] {name:<12} {desc:<30} [{status}]")


@cli.group()
def integrations() -> None:
    """Керування інтеграціями."""


@integrations.command("list")
def integrations_list() -> None:
    """Список інтеграцій."""
    from pathlib import Path

    integrations_dir = Path(__file__).parent / "integrations"
    click.echo("Інтеграції:")
    for d in sorted(integrations_dir.iterdir()):
        if d.is_dir() and (d / "tools.py").exists():
            name = d.name
            # Зчитати docstring з tools.py
            tools_py = d / "tools.py"
            desc = ""
            for line in tools_py.read_text(encoding="utf-8").splitlines()[:3]:
                if line.startswith('"""'):
                    desc = line.strip('"').strip()
                    break
            click.echo(f"  {name:<20} {desc}")


@cli.group()
def skills() -> None:
    """Керування скілами."""


@skills.command("list")
def skills_list() -> None:
    """Список скілів."""
    from pathlib import Path

    # Builtin skills
    builtin_dir = Path(__file__).parent / "skills" / "builtin"
    click.echo("Вбудовані скіли:")
    if builtin_dir.exists():
        for d in sorted(builtin_dir.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                skill_md = d / "SKILL.md"
                name = d.name
                desc = ""
                for line in skill_md.read_text(encoding="utf-8").splitlines():
                    if line and not line.startswith("#"):
                        desc = line.strip()
                        break
                click.echo(f"  {name:<16} {desc}")

    # Workspace skills
    from posipaka.config.settings import get_settings

    settings = get_settings()
    ws_dir = settings.data_dir / "skills"
    if ws_dir.exists():
        ws_skills = [d for d in ws_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
        if ws_skills:
            click.echo("\nКористувацькі скіли:")
            for d in sorted(ws_skills):
                click.echo(f"  {d.name}")


@cli.group()
def memory() -> None:
    """Керування пам'яттю."""


@memory.command("show")
def memory_show() -> None:
    """Показати MEMORY.md."""
    from posipaka.config.settings import get_settings

    settings = get_settings()
    memory_path = settings.data_dir / "MEMORY.md"
    if memory_path.exists():
        content = memory_path.read_text(encoding="utf-8")
        if content.strip():
            click.echo(content)
        else:
            click.echo("MEMORY.md порожній.")
    else:
        click.echo("MEMORY.md ще не створено.")


@cli.group()
def audit() -> None:
    """Безпека та аудит."""


@audit.command("verify")
def audit_verify() -> None:
    """Перевірити цілісність audit log."""
    from posipaka.config.settings import get_settings
    from posipaka.security.audit import AuditLogger

    settings = get_settings()
    audit_logger = AuditLogger(settings.audit_log_path)
    valid, count, msg = audit_logger.verify_integrity()
    if valid:
        click.echo(f"Audit log intact: {msg}")
    else:
        click.echo(f"INTEGRITY ERROR: {msg}")


@cli.group()
def backup() -> None:
    """Backup та restore."""


@backup.command("create")
@click.option("--name", default=None, help="Назва бекапу")
def backup_create(name: str | None) -> None:
    """Створити backup."""
    from posipaka.config.settings import get_settings
    from posipaka.utils.backup import BackupManager

    settings = get_settings()
    bm = BackupManager(settings.data_dir)
    path = bm.create_backup(name)
    click.echo(f"Backup: {path}")


@backup.command("list")
def backup_list() -> None:
    """Список бекапів."""
    from posipaka.config.settings import get_settings
    from posipaka.utils.backup import BackupManager

    settings = get_settings()
    bm = BackupManager(settings.data_dir)
    for b in bm.list_backups():
        click.echo(f"  {b['name']}  {b['size_mb']:.1f} MB  {b['created']}")


@backup.command("restore")
@click.argument("path")
def backup_restore(path: str) -> None:
    """Відновити з backup."""
    from pathlib import Path

    from posipaka.config.settings import get_settings
    from posipaka.utils.backup import BackupManager

    settings = get_settings()
    bm = BackupManager(settings.data_dir)
    bm.restore_backup(Path(path))
    click.echo("Restored.")


@cli.group()
def db() -> None:
    """Керування базою даних (міграції)."""


@db.command("upgrade")
@click.option("--revision", default="head", help="Target revision")
def db_upgrade(revision: str) -> None:
    """Застосувати міграції (alembic upgrade)."""
    from alembic.config import Config

    from alembic import command as alembic_cmd

    alembic_cfg = Config("alembic.ini")
    alembic_cmd.upgrade(alembic_cfg, revision)
    click.echo(f"Database upgraded to {revision}")


@db.command("downgrade")
@click.option("--revision", default="-1", help="Target revision")
def db_downgrade(revision: str) -> None:
    """Відкотити міграцію (alembic downgrade)."""
    from alembic.config import Config

    from alembic import command as alembic_cmd

    alembic_cfg = Config("alembic.ini")
    alembic_cmd.downgrade(alembic_cfg, revision)
    click.echo(f"Database downgraded to {revision}")


@db.command("current")
def db_current() -> None:
    """Показати поточну версію бази."""
    from alembic.config import Config

    from alembic import command as alembic_cmd

    alembic_cfg = Config("alembic.ini")
    alembic_cmd.current(alembic_cfg)


@cli.command("eval")
@click.option(
    "--set",
    "eval_set",
    default="all",
    help="Eval set: safety, clean, sandbox, routing, all",
)
@click.option(
    "--fail-on-regression",
    is_flag=True,
    help="Exit code 1 якщо eval fails",
)
def run_eval(eval_set: str, fail_on_regression: bool) -> None:
    """Запустити eval tests для регресійного тестування."""
    from tests.evals.eval_runner import EvalRunner

    runner = EvalRunner()

    if eval_set == "all":
        results = runner.run_all()
    elif eval_set == "safety":
        results = [runner.run_safety_evals()]
    elif eval_set == "clean":
        results = [runner.run_clean_input_evals()]
    elif eval_set == "sandbox":
        results = [runner.run_sandbox_evals()]
    elif eval_set == "routing":
        results = [runner.run_model_routing_evals()]
    else:
        click.echo(f"Unknown eval set: {eval_set}")
        return

    for r in results:
        click.echo(r.summary())
        for d in r.details:
            click.echo(f"  FAILED: {d}")

    total = sum(r.total for r in results)
    passed = sum(r.passed for r in results)
    click.echo(f"\nTotal: {passed}/{total} ({passed / total * 100:.0f}%)")

    if fail_on_regression and passed < total:
        raise SystemExit(1)
