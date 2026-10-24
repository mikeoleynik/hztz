"""Команда `hz next` — следующая задача, бриф и закрытие."""

import json
import sys
from pathlib import Path

import typer
from rich.console import Console

from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console
from hztz.core import next as next_core
from hztz.core.pipeline import StageRunner
from hztz.core.repo import detect_repo
from hztz.core.store import StateStore, hash_text
from hztz.models.state import LogEntry, State, Task, now_utc
from hztz.templates.render import render_decomposition_md

err_console = Console(stderr=True, highlight=False)


def next(  # noqa: A001
    target: str | None = typer.Argument(None, help="T# или B#."),
    list_mode: bool = typer.Option(False, "--list", help="Доска задач, без записи."),
    prompt: bool = typer.Option(False, "--prompt", help="Бриф; готовую todo берёт в работу."),
    done: bool = typer.Option(False, "--done", help="Закрыть in_progress или подтвердить ревизию."),
    json_mode: bool = typer.Option(False, "--json", help="Машинный вывод карточки и доски."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Пропустить подтверждения."),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Не писать пояснения в stderr."),
) -> None:
    """Что делать дальше: следующая задача и её контекст."""
    if prompt and done:
        _out("[red]Укажите либо --prompt, либо --done.[/red]")
        raise typer.Exit(code=1)
    if list_mode and (prompt or done or target):
        _out("[red]--list не сочетается с id и с --prompt/--done.[/red]")
        raise typer.Exit(code=1)

    store = StateStore(Path.cwd())
    state = store.load()
    if state is None:
        _explain("Нет состояния. Сначала `hz audit SPEC`.", prompt=prompt, quiet=quiet)
        raise typer.Exit(code=2)

    stale = _spec_stale(state)
    if stale and not yes:
        _explain(
            "ТЗ изменился с последнего audit. Сначала `hz audit SPEC`.",
            prompt=prompt,
            quiet=quiet,
        )
        raise typer.Exit(code=2)

    try:
        if list_mode:
            _show_list(store, state, json_mode, stale)
            return
        if done:
            _run_done(store, state, target, yes, stale)
            return
        if prompt:
            _run_prompt(store, state, target, stale=stale, quiet=quiet)
            return
        _run_show(store, state, target, json_mode, stale)
    except next_core.NextError as exc:
        _explain(str(exc), prompt=prompt, quiet=quiet)
        raise typer.Exit(code=exc.code) from exc


def _run_show(
    store: StateStore,
    state: State,
    target: str | None,
    json_mode: bool,
    stale: bool,
) -> None:
    task_id, block_id = _split_target(target)
    if task_id is not None:
        task = next_core.require_task(state, task_id)
        payload = next_core.QueueResult(code=0, task=task)
        text = next_core.format_card(state, task)
    else:
        payload = next_core.choose(state, block_id)
        text = (
            next_core.format_card(state, payload.task, payload.others)
            if payload.task is not None
            else next_core.format_stop(state, payload, block_id)
        )
    _persist(store, state, stale=stale, save=False)
    if json_mode:
        _out_plain(json.dumps(_payload(payload), ensure_ascii=False, indent=2))
    else:
        _out_plain(text)
    if payload.code:
        raise typer.Exit(code=payload.code)


def _show_list(store: StateStore, state: State, json_mode: bool, stale: bool) -> None:
    _persist(store, state, stale=stale, save=False)
    if json_mode:
        rows = [
            {
                "id": task.id,
                "block": task.block,
                "status": task.status.value,
                "order": task.order,
                "needs_review": task.needs_review,
            }
            for task in state.tasks
        ]
        _out_plain(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    _out_plain(next_core.format_list(state))


def _run_prompt(
    store: StateStore,
    state: State,
    target: str | None,
    *,
    stale: bool,
    quiet: bool,
) -> None:
    task_id, block_id = _split_target(target)
    if task_id is not None:
        task = next_core.require_task(state, task_id)
    else:
        picked = next_core.choose(state, block_id, prompt=True)
        if picked.task is None:
            _explain(next_core.format_stop(state, picked, block_id), prompt=True, quiet=quiet)
            raise typer.Exit(code=picked.code)
        task = picked.task

    changed = next_core.take(state, task)
    context = _maybe_context(state, task)
    brief = next_core.render_brief(state, task, context)
    if changed:
        _log(
            state,
            f"next {task.id} --prompt",
            [{"id": task.id, "status": "todo → in_progress"}],
        )
    _persist(store, state, stale=stale, save=changed)
    if changed:
        _write_view(store, state)
    sys.stdout.write(brief if brief.endswith("\n") else brief + "\n")


def _run_done(
    store: StateStore,
    state: State,
    target: str | None,
    yes: bool,
    stale: bool,
) -> None:
    task_id, block_id = _split_target(target)
    if block_id is not None:
        raise next_core.NextError(1, "Для --done укажите задачу T#, не блок.")
    task = (
        next_core.require_task(state, task_id)
        if task_id is not None
        else next_core.sole_in_progress(state)
    )
    next_core.ensure_closable(task)
    before = task.status.value
    if task.status.value == "done" and task.needs_review:
        replaced = " ".join(next_core.superseded_decision_ids(state, task))
        _out_plain(f"Подтвердить ревизию {task.id}: {replaced}")
    checklist = "\n".join(f"  [ ] {item}" for item in task.done_when) or "  (пусто)"
    if not yes and not typer.confirm(f"Закрыть {task.id}?\n{checklist}", default=False):
        raise typer.Exit(code=2)
    next_core.finish(state, task)
    _log(
        state,
        f"next {task.id} --done",
        [{"id": task.id, "status": f"{before} → {task.status.value}"}],
    )
    _persist(store, state, stale=stale, save=True)
    _write_view(store, state)
    _out_plain(f"{task.id} {task.status.value}")


def _maybe_context(state: State, task: Task) -> dict[str, object] | None:
    root = Path(state.repo or ".")
    if not root.is_absolute():
        root = Path.cwd() / root
    if not detect_repo(root):
        return None
    load_config_or_exit()
    return next_core.load_repo_context(state, task, StageRunner())


def _split_target(target: str | None) -> tuple[str | None, str | None]:
    if target is None:
        return None, None
    if len(target) < 2 or not target[1:].isdigit():
        raise next_core.NextError(1, f"Неизвестный id {target}")
    if target[0] == "T":
        return target, None
    if target[0] == "B":
        return None, target
    raise next_core.NextError(1, f"Неизвестный id {target}")


def _spec_stale(state: State) -> bool:
    if state.spec is None:
        return False
    spec_file = Path(state.spec.path)
    if not spec_file.is_absolute():
        spec_file = Path.cwd() / spec_file
    if not spec_file.exists():
        return True
    return hash_text(spec_file.read_text(encoding="utf-8")) != state.spec.hash


def _persist(store: StateStore, state: State, *, stale: bool, save: bool) -> None:
    if stale:
        state.log.append(
            LogEntry(
                at=now_utc(),
                cmd="next -y",
                via="cli",
                changed=[{"id": "spec", "status": "stale → bypass"}],
            )
        )
    if stale or save:
        store.save(state)


def _log(state: State, cmd: str, changed: list[dict[str, str]]) -> None:
    state.log.append(LogEntry(at=now_utc(), cmd=cmd, via="cli", changed=changed))


def _write_view(store: StateStore, state: State) -> None:
    store.hz_dir.mkdir(parents=True, exist_ok=True)
    (store.hz_dir / "decomposition.md").write_text(render_decomposition_md(state), encoding="utf-8")


def _payload(result: next_core.QueueResult) -> dict[str, object]:
    task = result.task
    return {
        "code": result.code,
        "task": None if task is None else task.model_dump(mode="json"),
        "others": [item.id for item in result.others],
        "blocked": [{"id": item.id, "because": label} for item, label in result.blocked],
        "waiting": [{"id": item.id, "because": label} for item, label in result.waiting],
    }


def _explain(message: str, *, prompt: bool, quiet: bool) -> None:
    if prompt:
        if not quiet:
            err_console.print(message, markup=False)
        return
    _out_plain(message)


def _out(message: str) -> None:
    console.print(message)


def _out_plain(message: str) -> None:
    console.print(message, markup=False, highlight=False)
