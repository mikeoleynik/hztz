"""Корневая Typer-группа `hz`."""

import typer

from hztz.cli import audit, chat, decompose, init
from hztz.cli import next as next_cmd

app = typer.Typer(
    name="hz",
    help="хз в тз — превращает сырое ТЗ в декомпозированный список задач.",
    no_args_is_help=True,
)

app.add_typer(init.app, name="init")
app.add_typer(audit.app, name="audit")
app.add_typer(decompose.app, name="decompose")
app.add_typer(next_cmd.app, name="next")
app.add_typer(chat.app, name="chat")


def main() -> None:
    app()
