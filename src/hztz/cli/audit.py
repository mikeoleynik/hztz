"""Команда `hz audit`."""

import json
from pathlib import Path

import typer
from rich.table import Table

from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console
from hztz.core import audit as audit_core
from hztz.core.pipeline import StageRunner
from hztz.core.store import StateStore, short_hash
from hztz.models.state import DKind, Question, State
from hztz.templates.render import build_view, render_audit_md


def audit(
    target: str = typer.Argument(None, help="path к ТЗ или ID объекта (O#/A#)"),
    answer: str = typer.Option(None, "--answer", help="Записать ответ аналитика на вопрос."),
    assume: str = typer.Option(None, "--assume", help="Закрыть вопрос собственным допущением."),
    dismiss: bool = typer.Option(False, "--dismiss", help="Отклонить находку/вопрос."),
    question: str = typer.Option(None, "--question", help="Добавить вопрос вручную."),
    for_task: str = typer.Option(None, "--for", help="Задача, к которой относится вопрос."),
    resolve_: bool = typer.Option(False, "--resolve", help="Пройти открытые вопросы интерактивно."),
    check: bool = typer.Option(False, "--check", help="exit 3 при открытых blocker-вопросах."),
    reset: bool = typer.Option(False, "--reset", help="Снести состояние."),
    output: str = typer.Option(None, "-o", "--output", help="Куда писать audit.md ('-' = stdout)."),
    json_mode: bool = typer.Option(False, "--json", help="Машинный вывод."),
) -> None:
    """Анализ ТЗ: требования, находки, вопросы."""
    store = StateStore(Path.cwd())

    if reset:
        _reset(store)
        return

    if question:
        _add_question(store, question, for_task)
        return

    if resolve_:
        _resolve(store)
        return

    if target and (answer or assume or dismiss):
        _mutate(store, target, answer, assume, dismiss)
        return

    if check:
        _check(store)

    if target and not _is_id(target):
        _analyze(store, Path(target), output)
        return

    if target and _is_id(target):
        console.print(f"[yellow]Для {target} укажите --answer/--assume/--dismiss.[/yellow]")
        raise typer.Exit(code=1)

    if check:
        return

    _status(store, json_mode)

def _is_id(s: str) -> bool:
    return len(s) >= 2 and s[0] in "RAOD" and s[1:].isdigit()

def _analyze(store: StateStore, spec_path: Path, output: str | None) -> None:
    load_config_or_exit()
    runner = StageRunner()
    existing = store.load()
    state = audit_core.analyze(spec_path, store, runner, existing)
    _write_view(store, state, output)
    _print_summary(state)

def _write_view(store: StateStore, state: State, output: str | None) -> None:
    md = render_audit_md(state)
    if output == "-":
        console.print(md)
    elif output:
        Path(output).write_text(md, encoding="utf-8")
    else:
        store.hz_dir.mkdir(parents=True, exist_ok=True)
        (store.hz_dir / "audit.md").write_text(md, encoding="utf-8")

def _print_summary(state: State) -> None:
    spec = state.spec
    if spec is None:
        return
    console.print(
        f"[bold]Spec[/bold] {spec.path} ({short_hash(spec.hash)}…)  "
        f"[bold]R[/bold] {len(state.requirements)} · "
        f"[bold]A[/bold] {len(state.findings)} · "
        f"[bold]O[/bold] {len(state.questions)}"
    )
    open_q = [q for q in state.questions if q.status.value == "open"]
    blockers = sum(1 for q in open_q if _q_severity(state, q) == "blocker")
    console.print(f"Открытых вопросов: {len(open_q)} (blocker {blockers})")

def _q_severity(state: State, q: Question) -> str:
    ranks = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
    s = [ranks[f.severity.value] for f in state.findings if f.id in q.findings]
    return ["blocker", "high", "medium", "low"][min(s)] if s else "low"

def _mutate(
    store: StateStore, obj_id: str, answer: str | None, assume: str | None, dismiss: bool
) -> None:
    state = store.load()
    if state is None:
        console.print("[red]Нет состояния. Сначала `hz audit SPEC`.[/red]")
        raise typer.Exit(code=2)
    if answer:
        audit_core.answer_or_assume(state, obj_id, answer, DKind.answer)
    elif assume:
        audit_core.answer_or_assume(state, obj_id, assume, DKind.assumption)
    elif dismiss:
        audit_core.dismiss(state, obj_id)
    store.save(state)
    _write_view(store, state, None)
    console.print(f"[green]{obj_id} обновлён.[/green]")

def _add_question(store: StateStore, text: str, for_task: str | None) -> None:
    state = store.load()
    if state is None:
        console.print("[red]Нет состояния. Сначала `hz audit SPEC`.[/red]")
        raise typer.Exit(code=2)
    audit_core.add_question(state, text, for_task)
    store.save(state)
    _write_view(store, state, None)
    console.print("[green]Вопрос добавлен.[/green]")

def _resolve(store: StateStore) -> None:
    state = store.load()
    if state is None:
        console.print("[red]Нет состояния.[/red]")
        raise typer.Exit(code=2)
    open_qs = [q for q in state.questions if q.status.value == "open"]
    for q in open_qs:
        prompt_text = f"{q.id} — {q.text}\n[a]nswer / as[s]ume / [d]ismiss / s[k]ip"
        text = typer.prompt(prompt_text, default="k")
        text = text.strip().lower()
        if text.startswith("a"):
            val = typer.prompt("Ответ")
            audit_core.answer_or_assume(state, q.id, val, DKind.answer)
        elif text.startswith("s"):
            val = typer.prompt("Допущение")
            audit_core.answer_or_assume(state, q.id, val, DKind.assumption)
        elif text.startswith("d"):
            audit_core.dismiss(state, q.id)
        else:
            continue
    store.save(state)
    _write_view(store, state, None)

def _check(store: StateStore) -> None:
    state = store.load()
    if state is None:
        raise typer.Exit(code=2)
    blockers = [
        q
        for q in state.questions
        if q.status.value == "open" and _q_severity(state, q) == "blocker"
    ]
    if blockers:
        console.print(f"[red]Открытых blocker-вопросов: {len(blockers)}[/red]")
        raise typer.Exit(code=3)

def _status(store: StateStore, json_mode: bool) -> None:
    state = store.load()
    if state is None:
        console.print("[yellow]Состояния нет. Запустите `hz audit SPEC`.[/yellow]")
        raise typer.Exit(code=2)
    if json_mode:
        console.print(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return
    view = build_view(state)
    table = Table(title="Открытые вопросы")
    table.add_column("ID")
    table.add_column("Severity")
    table.add_column("Audience")
    table.add_column("Вопрос")
    for q in view["open_questions"]:
        table.add_row(q["id"], q["severity"], q["audience"], q["text"])
    console.print(table)
    console.print("Next: hz audit --resolve")

def _reset(store: StateStore) -> None:
    if store.state_path.exists():
        store.state_path.unlink()
    for f in ("audit.md",):
        p = store.hz_dir / f
        if p.exists():
            p.unlink()
    console.print("[green]Состояние сброшено.[/green]")
