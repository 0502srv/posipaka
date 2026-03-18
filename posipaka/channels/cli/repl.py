"""Posipaka — CLI REPL для тестування."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from posipaka.channels.base import BaseChannel

if TYPE_CHECKING:
    from posipaka.config.settings import Settings
    from posipaka.core.agent import Agent


class CLIChannel(BaseChannel):
    """Інтерактивний CLI для тестування агента."""

    def __init__(self, agent: Agent, settings: Settings) -> None:
        super().__init__(agent)
        self.settings = settings
        self.console = Console()
        self._running = False

    @property
    def name(self) -> str:
        return "cli"

    async def start(self) -> None:
        """Запустити REPL."""
        self._running = True
        session = self.agent.sessions.get_or_create("cli_user", "cli")

        self.console.print(
            Panel(
                f"[bold blue]Posipaka[/bold blue] — CLI Chat\n"
                f"LLM: {self.settings.llm.provider}/{self.settings.llm.model}\n"
                f"Введіть повідомлення або /help для довідки. /quit для виходу.",
                title="Posipaka",
                border_style="blue",
            )
        )

        while self._running:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.console.input("[bold green]Ви>[/bold green] ")
                )
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input.strip():
                continue

            # Commands
            if user_input.startswith("/"):
                parts = user_input[1:].split(maxsplit=1)
                command = parts[0]
                args = parts[1] if len(parts) > 1 else ""

                if command == "quit" or command == "exit":
                    break
                if command == "help":
                    self.console.print(
                        "/help — довідка\n"
                        "/status — статус агента\n"
                        "/reset — скинути сесію\n"
                        "/memory — факти\n"
                        "/skills — список навичок\n"
                        "/cost — витрати\n"
                        "/quit — вихід"
                    )
                    continue

                result = await self.agent.handle_command(command, args, "cli_user")
                self.console.print(f"[dim]{result}[/dim]")
                continue

            # Regular message
            self.console.print("[dim]Думаю...[/dim]")
            async for chunk in self.agent.handle_message(user_input, session.id):
                try:
                    self.console.print(
                        Panel(
                            Markdown(chunk),
                            title="Posipaka",
                            border_style="blue",
                        )
                    )
                except Exception:
                    self.console.print(f"[blue]Posipaka>[/blue] {chunk}")

        self.console.print("[dim]До побачення![/dim]")

    async def stop(self) -> None:
        self._running = False

    async def send_message(self, user_id: str, text: str) -> None:
        self.console.print(f"[blue]Posipaka>[/blue] {text}")
