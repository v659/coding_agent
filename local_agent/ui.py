from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

hacker_theme = Theme(
    {
        "primary": "bold green",
        "error": "bold red",
        "dim": "dim green",
        "panel.border": "green",
        "ascii": "bold green",
        "prompt": "bold green",
    }
)

ASCII_BANNER = r"""
  ______       __        ____        _   _     _            _      _
 |  ____|      \ \      / /  |  _ \      | | | |   | |          | |    | |
 | |__   _ __   \ \_/ /__| |_) | ___| |_| | __| | ___   ___| | __| |
 |  __| | '_ \   \   / _ \  _ < / _ \ __| |/ _` |/ _ \ / __| |/ _` |
 | |____| | | |   | ||  __/ |_) |  __/ |_| | (_| | (_) | (__| | (_| |
 |______|_| |_|   |_| \___|____/ \___|\__|_|\__,_|\___/ \___|_|\__,_|
"""


def create_console() -> Console:
    return Console(theme=hacker_theme)


def show_startup(console: Console, session_id: str) -> None:
    console.print(Text(ASCII_BANNER, style="ascii"))
    console.print(Panel("[primary]Welcome to Hacky CLI Bot! Type your commands below.[/primary]", style="panel.border"))
    console.print(f"[primary]Session[/primary]: {session_id}")
    console.print("[primary]Commands[/primary]: /reset, /exit")


def show_tool_step(console: Console, step: int, tool_name: str) -> None:
    console.print(f"[dim]step {step}: used {tool_name}[/dim]")


def show_tool_error(console: Console, message: str) -> None:
    console.print(Panel(f"[error]tool_error[/error] {message}", style="panel.border"))


def show_verify_error(console: Console, message: str) -> None:
    console.print(Panel(f"[error]verify_error[/error] {message}", style="panel.border"))


def show_result(console: Console, message: str) -> None:
    clipped = message if len(message) <= 3000 else message[:3000] + "...(truncated)"
    console.print(Panel(f"[primary]{clipped}[/primary]", style="panel.border"))


def show_info(console: Console, message: str) -> None:
    console.print(f"[dim]{message}[/dim]")


def show_goodbye(console: Console) -> None:
    console.print("Bye.")
