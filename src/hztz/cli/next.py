"""Команда `hz next` — что делать дальше."""

import typer

from hztz.cli.UI.console import console

app = typer.Typer(help="Что делать дальше: следующая задача и её контекст.")


@app.callback(invoke_without_command=True)
def next() -> None:
    console.print("[yellow]hz next — ещё не реализован.[/yellow]")
