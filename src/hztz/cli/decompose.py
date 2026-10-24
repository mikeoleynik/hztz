"""Команда `hz decompose` — построение инженерной модели."""

import json
from pathlib import Path
from typing import Any

import typer

from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console
from hztz.core import decompose as decompose_core
from hztz.core.pipeline import StageBlockedError, StageRunner
from hztz.core.repo import build_repo_context, detect_repo
from hztz.core.store import StateStore, hash_text
from hztz.models.state import LogEntry, State, now_utc
from hztz.templates.render import build_decompose_view, render_decomposition_md


def decompose(
    repo: str | None = typer.Option(None, "--repo", help="Где лежит код (запоминается)."),
    reset: bool = typer.Option(False, "--reset", help="Снести B/T и пересобрать."),
    output: str = typer.Option(None, "-o", "--output", help="Куда писать decomposition.md."),
    json_mode: bool = typer.Option(False, "--json", help="Машинный вывод."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Пропустить подтверждения."),
) -> None:
    """Построение инженерной модели: блоки системы и шаги реализации."""
    store = StateStore(Path.cwd())
    state = store.load()
    if state is None:
        console.print("[red]Нет состояния. Сначала `hz audit SPEC`.[/red]")
        raise typer.Exit(code=2)

    if _spec_stale(state):
        if not yes:
            console.print("[red]ТЗ изменился с последнего audit. Сначала `hz audit SPEC`.[/red]")
            raise typer.Exit(code=2)
        state.log.append(
            LogEntry(
                at=now_utc(),
                cmd="decompose -y",
                via="cli",
                changed=[{"id": "spec", "status": "stale → bypass"}],
            )
        )

    if reset:
        if not yes and not typer.confirm("Снести блоки, задачи и вопросы decompose и пересобрать?"):
            raise typer.Exit(code=0)
        _reset(state)

    repo_path = _repo_path(state, repo)
    repo_context = build_repo_context(repo_path)
    before = _snapshot(state)
    updating = bool(before["tasks"] or before["blocks"])

    load_config_or_exit()
    runner = StageRunner()
    try:
        decompose_core.run_decompose(state, runner, repo_context)
    except decompose_core.DecomposeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except StageBlockedError as exc:
        console.print(f"[yellow]Декомпозиция остановлена:[/yellow] {exc.reason}")
        console.print("Нечего нарезать. Закройте скоуп и запустите снова.")
        raise typer.Exit(code=2) from exc

    _append_log(state, "decompose --reset" if reset else "decompose", before)
    store.save(state)
    _write_view(store, state, output)

    if json_mode:
        console.print(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return
    if updating:
        _print_delta(state, before)
    else:
        _print_summary(state, repo_context)


def _repo_path(state: State, repo: str | None) -> Path:
    if repo:
        state.repo = repo
        return Path(repo)
    if state.repo and state.repo != ".":
        return Path(state.repo)
    cwd = Path.cwd()
    if detect_repo(cwd):
        state.repo = "."
    return cwd


def _entity_ids(state: State) -> list[str]:
    return [
        *[block.id for block in state.blocks],
        *[task.id for task in state.tasks],
        *[finding.id for finding in state.findings],
        *[question.id for question in state.questions],
    ]


def _snapshot(state: State) -> dict[str, Any]:
    return {
        "blocks": {b.id: {"status": b.status.value} for b in state.blocks},
        "tasks": {
            t.id: {
                "status": t.status.value,
                "title": t.title,
                "needs_review": t.needs_review,
                "order": t.order,
            }
            for t in state.tasks
        },
        "ids": {entity_id: {} for entity_id in _entity_ids(state)},
    }


def _append_log(state: State, cmd: str, before: dict[str, Any]) -> None:
    known = set(before["ids"])
    created = [entity_id for entity_id in _entity_ids(state) if entity_id not in known]
    changed: list[dict[str, Any]] = []
    prev_tasks = before["tasks"]
    for task in state.tasks:
        prev = prev_tasks.get(task.id)
        if prev is None:
            continue
        if prev["status"] != task.status.value:
            changed.append({"id": task.id, "status": f"{prev['status']} → {task.status.value}"})
        elif task.needs_review and not prev["needs_review"]:
            changed.append({"id": task.id, "status": "needs_review"})
    state.log.append(LogEntry(at=now_utc(), cmd=cmd, via="cli", created=created, changed=changed))


def _print_delta(state: State, before: dict[str, Any]) -> None:
    prev = before["tasks"]
    current = {t.id: t for t in state.tasks}
    kept: list[str] = []
    updated: list[str] = []
    dropped: list[str] = []
    review: list[str] = []
    for tid, meta in prev.items():
        task = current.get(tid)
        if task is None:
            continue
        if task.status.value == "dropped" and meta["status"] != "dropped":
            dropped.append(tid)
        elif task.status.value in ("done", "in_progress"):
            kept.append(tid)
        elif meta["status"] == "todo" and task.status.value == "todo":
            updated.append(tid)
        if task.needs_review and not meta["needs_review"]:
            review.append(tid)
    new = [
        t.id
        for t in sorted(state.tasks, key=lambda item: item.order)
        if t.id not in prev and t.status.value != "dropped"
    ]
    prev_active = sum(1 for meta in prev.values() if meta["status"] != "dropped")
    now_active = sum(1 for task in state.tasks if task.status.value != "dropped")
    console.print(f"Tasks  {prev_active} → {now_active}")
    if kept:
        console.print("  kept     " + " ".join(kept))
    if updated:
        console.print("  updated  " + " ".join(updated))
    if dropped:
        console.print("  dropped  " + " ".join(dropped))
    if new:
        console.print("  new      " + " ".join(new))
    if review:
        console.print("  review   " + " ".join(review))
    console.print("Next: hz next")


def _spec_stale(state: State) -> bool:
    if state.spec is None:
        return False
    spec_file = Path(state.spec.path)
    if not spec_file.exists():
        return True
    return hash_text(spec_file.read_text(encoding="utf-8")) != state.spec.hash


def _reset(state: State) -> None:
    state.blocks = []
    state.tasks = []
    state.coverage.uncovered = []
    state.coverage.skipped = []
    state.findings = [f for f in state.findings if f.origin.command != "decompose"]
    state.questions = [q for q in state.questions if q.origin.command != "decompose"]


def _write_view(store: StateStore, state: State, output: str | None) -> None:
    md = render_decomposition_md(state)
    if output == "-":
        console.print(md)
    elif output:
        Path(output).write_text(md, encoding="utf-8")
    else:
        store.hz_dir.mkdir(parents=True, exist_ok=True)
        (store.hz_dir / "decomposition.md").write_text(md, encoding="utf-8")


def _print_summary(state: State, repo_context: dict[str, object] | None) -> None:
    view = build_decompose_view(state)
    active_blocks = sum(1 for b in state.blocks if b.status.value == "active")
    active_tasks = sum(1 for t in state.tasks if t.status.value != "dropped")
    stack = repo_context["stack"] if repo_context else "—"
    console.print(f"[bold]Repo[/bold] {state.repo} ({stack})")
    console.print(
        f"[bold]Blocks[/bold] {active_blocks} · [bold]Tasks[/bold] {active_tasks} · "
        f"blocked {len(view['blocked_tasks'])}"
    )
    console.print("Next: hz next")
