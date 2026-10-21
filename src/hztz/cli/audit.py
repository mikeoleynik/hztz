"""Команда `hz audit` — проверка ТЗ на неопределённости."""

import typer

from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console

app = typer.Typer(help="Проверка ТЗ на неопределённости и формирование вопросов.")


@app.callback(invoke_without_command=True)
def audit() -> None:
    load_config_or_exit()
    console.print("[yellow]hz audit — ещё не реализован.[/yellow]")
