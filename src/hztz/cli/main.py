"""Корневая Typer-группа `hz`."""

import typer

from hztz.cli import audit, chat, decompose, init
from hztz.cli import next as next_cmd

app = typer.Typer(
    name="hz",
    help="хз в тз — превращает сырое ТЗ в декомпозированный список задач.",
    no_args_is_help=True,
)

app.command()(init.init)
app.command()(audit.audit)
app.command()(decompose.decompose)
app.command()(next_cmd.next)
app.command()(chat.chat)


def main() -> None:
    app()
