"""Команда `hz chat` — разговор по ТЗ и графу состояния."""

from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console


def chat() -> None:
    """Разговор по ТЗ и графу состояния (персоны, слэш-команды)."""
    load_config_or_exit()
    console.print("[yellow]hz chat — ещё не реализован.[/yellow]")
