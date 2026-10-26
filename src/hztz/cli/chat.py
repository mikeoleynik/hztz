"""Команда `hz chat` и продолжение `hz -s`."""

import json
import sys
from collections.abc import Callable
from pathlib import Path

import typer
from prompt_toolkit import PromptSession
from rich.text import Text

from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console
from hztz.core.chat import ChatModelError, run_oneshot, run_repl
from hztz.core.config import HzConfig
from hztz.core.llm.client import LLMClient
from hztz.core.session import SessionStore
from hztz.core.store import StateStore
from hztz.models.session import ChatSession


def chat(
    message: str | None = typer.Option(None, "-m", help="Одно сообщение без сессии и без правок."),
    persona: str | None = typer.Option(None, "--persona", help="Персона новой сессии."),
    json_mode: bool = typer.Option(False, "--json", help="Для -m: весь объект ответа."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Не спрашивать подтверждение слэша."),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Не глушит баннер продолжения."),
    model: str | None = typer.Option(None, "--model", help="Модель на этот запуск."),
) -> None:
    """Разговор по ТЗ и графу. Файлы проекта можно править, граф — только слэшем."""
    _ = quiet
    root = Path.cwd()
    state_store = StateStore(root)
    if not state_store.exists():
        console.print("[red]Нет состояния. Сначала `hz audit SPEC`.[/red]")
        raise typer.Exit(code=2)
    config = _config(model)
    chosen = persona or config.persona
    if message is not None:
        _oneshot(state_store, root, config, chosen, message, json_mode)
        return
    code, session = _loop(
        root=root,
        state_store=state_store,
        config=config,
        persona=chosen,
        yes=yes,
        existing=None,
    )
    _finish(code, session)


def resume(
    session_id: str,
    *,
    persona: str | None = None,
    yes: bool = False,
    quiet: bool = False,
    model: str | None = None,
) -> None:
    _ = quiet
    root = Path.cwd()
    sessions = SessionStore(root)
    existing = sessions.load(session_id)
    if existing is None:
        console.print(f"[red]Нет сессии {session_id}.[/red]")
        raise typer.Exit(code=2)
    state_store = StateStore(root)
    if not state_store.exists():
        console.print("[red]Нет состояния. Сначала `hz audit SPEC`.[/red]")
        raise typer.Exit(code=2)
    config = _config(model)
    if persona:
        existing.persona = persona
        sessions.save(existing)
    code, session = _loop(
        root=root,
        state_store=state_store,
        config=config,
        persona=existing.persona,
        yes=yes,
        existing=existing,
    )
    _finish(code, session)


def _config(model: str | None) -> HzConfig:
    config = load_config_or_exit()
    if model is None:
        return config
    provider = config.provider.model_copy(update={"model": model})
    return config.model_copy(update={"provider": provider})


def _oneshot(
    state_store: StateStore,
    root: Path,
    config: HzConfig,
    persona: str,
    message: str,
    json_mode: bool,
) -> None:
    state = state_store.load()
    if state is None:
        raise typer.Exit(code=2)
    try:
        payload = run_oneshot(LLMClient(config), state, root, persona, message)
    except (ChatModelError, OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if json_mode:
        console.print(json.dumps(payload, ensure_ascii=False))
    else:
        reply = payload.get("reply")
        console.print(reply if isinstance(reply, str) else "")


def _loop(
    *,
    root: Path,
    state_store: StateStore,
    config: HzConfig,
    persona: str,
    yes: bool,
    existing: ChatSession | None,
) -> tuple[int, ChatSession | None]:
    reader = _reader()
    try:
        return run_repl(
            root=root,
            state_store=state_store,
            sessions=SessionStore(root),
            client=LLMClient(config),
            persona=persona,
            yes=yes,
            read=reader,
            echo=_echo,
            emit=_emit,
            confirm=_confirm,
            existing=existing,
        )
    except ChatModelError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1, existing


def _finish(code: int, session: ChatSession | None) -> None:
    if session is not None and session.messages:
        console.print(f"  Session   {session.title}")
        console.print(f"  Continue  hz -s {session.id}")
    if code:
        raise typer.Exit(code=code)


def _reader() -> Callable[[], str | None]:
    if not sys.stdin.isatty():
        def read_plain() -> str | None:
            try:
                return input("> ")
            except EOFError:
                return None

        return read_plain
    prompt: PromptSession[str] = PromptSession()

    def read_tty() -> str | None:
        try:
            return str(prompt.prompt("> "))
        except (EOFError, KeyboardInterrupt):
            return None

    return read_tty


def _echo(text: str) -> None:
    console.print(text, markup=False)


def _emit(kind: str, text: str) -> None:
    if kind == "thinking":
        console.print(Text(text), style="dim", end="")
    elif kind == "text":
        console.print(text, end="", markup=False)
    elif kind == "break":
        console.print()
    else:
        console.print(text, markup=False)


def _confirm(prompt: str) -> bool:
    return typer.confirm(prompt, default=False)
