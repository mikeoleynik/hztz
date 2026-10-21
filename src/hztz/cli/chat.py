"""Команда `hz chat` — разговор по ТЗ и графу состояния."""

import typer

from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console

app = typer.Typer(help="Разговор по ТЗ и графу состояния (персоны, слэш-команды).")


@app.callback(invoke_without_command=True)
def chat() -> None:
    load_config_or_exit()
    console.print("[yellow]hz chat — ещё не реализован.[/yellow]")
