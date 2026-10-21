"""Команда `hz decompose` — построение инженерной модели (блоки и задачи)."""

import typer

from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console

app = typer.Typer(help="Построение инженерной модели: блоки системы и шаги реализации.")


@app.callback(invoke_without_command=True)
def decompose() -> None:
    load_config_or_exit()
    console.print("[yellow]hz decompose — ещё не реализован.[/yellow]")
