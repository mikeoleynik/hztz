"""Корневая Typer-группа `hz`."""

import typer

from hztz.cli import audit, chat, decompose, init
from hztz.cli import next as next_cmd

app = typer.Typer(
    name="hz",
    help="хз в тз — превращает сырое ТЗ в декомпозированный список задач.",
    no_args_is_help=True,
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    session: str | None = typer.Option(None, "-s", "--session", help="Продолжить сессию чата."),
    persona: str | None = typer.Option(None, "--persona", help="Персона при продолжении сессии."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Не спрашивать подтверждение слэша."),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Не глушит баннер продолжения."),
    model: str | None = typer.Option(None, "--model", help="Модель на этот запуск."),
) -> None:
    if session is not None:
        chat.resume(session, persona=persona, yes=yes, quiet=quiet, model=model)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


app.command()(init.init)
app.command()(audit.audit)
app.command()(decompose.decompose)
app.command()(next_cmd.next)
app.command()(chat.chat)


def main() -> None:
    app()
