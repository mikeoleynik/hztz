"""Очередь `hz next`: выбор задачи, бриф, закрытие. Markdown не читается."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from hztz.core.pipeline import StageRunner, block
from hztz.core.repo import build_tree
from hztz.core.severity import blocks_task, open_ref_severity
from hztz.models.state import Block, State, Task, TStatus, now_utc

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts" / "next"
_FILE_CHARS = 4_000
_MAX_CANDIDATES = 4


class NextError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class QueueResult:
    code: int
    task: Task | None = None
    others: list[Task] = field(default_factory=list)
    blocked: list[tuple[Task, str]] = field(default_factory=list)
    waiting: list[tuple[Task, str]] = field(default_factory=list)


def live_tasks(state: State, block_id: str | None = None) -> list[Task]:
    tasks = [task for task in state.tasks if task.status != TStatus.dropped]
    if block_id is not None:
        tasks = [task for task in tasks if task.block == block_id]
    return tasks


def _task_map(state: State) -> dict[str, Task]:
    return {task.id: task for task in state.tasks}


def _block(state: State, task: Task) -> Block | None:
    return next((item for item in state.blocks if item.id == task.block), None)


def dependency_waiting(state: State, task: Task) -> list[str]:
    known = _task_map(state)
    return [
        dep
        for dep in task.depends_on
        if known.get(dep) is None or known[dep].status != TStatus.done
    ]


def is_ready(state: State, task: Task) -> bool:
    if task.status != TStatus.todo:
        return False
    if any(blocks_task(open_ref_severity(state, ref)) for ref in task.blocked_by):
        return False
    return not dependency_waiting(state, task)


def _ref_label(state: State, ref: str) -> str:
    severity = open_ref_severity(state, ref) or "?"
    if ref.startswith("O"):
        question = next((item for item in state.questions if item.id == ref), None)
        if question is None:
            return ref
        return f"{ref} [{severity}, {question.audience.value}] «{question.text}»"
    finding = next((item for item in state.findings if item.id == ref), None)
    if finding is None:
        return ref
    return f"{ref} [{severity}] «{finding.title}»"


def blocking_labels(state: State, task: Task) -> list[str]:
    return [
        _ref_label(state, ref)
        for ref in task.blocked_by
        if blocks_task(open_ref_severity(state, ref))
    ]


def open_nonblocking(state: State, task: Task) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for ref in task.blocked_by:
        severity = open_ref_severity(state, ref)
        if severity is None or blocks_task(severity):
            continue
        text = ref
        if ref.startswith("O"):
            question = next((item for item in state.questions if item.id == ref), None)
            text = question.text if question else ref
        elif ref.startswith("A"):
            finding = next((item for item in state.findings if item.id == ref), None)
            text = finding.title if finding else ref
        items.append({"id": ref, "text": text, "severity": severity})
    return items


def superseded_decision_ids(state: State, task: Task) -> list[str]:
    owner = _block(state, task)
    if owner is None:
        return []
    return [
        decision.id
        for decision in state.decisions
        if decision.id in owner.decisions and decision.superseded_by is not None
    ]


def choose(state: State, block_id: str | None = None, *, prompt: bool = False) -> QueueResult:
    if block_id is not None and block_id not in {item.id for item in state.blocks}:
        raise NextError(1, f"блок {block_id} не найден")
    if not state.blocks and not state.tasks:
        raise NextError(2, "Нет задач. Сначала `hz decompose`.")

    live = live_tasks(state, block_id)
    in_progress = sorted(
        (task for task in live if task.status == TStatus.in_progress),
        key=lambda task: task.order,
    )
    if len(in_progress) > 1 and prompt:
        names = " ".join(task.id for task in in_progress)
        raise NextError(2, f"Несколько задач в работе: {names}. Укажите id.")
    if in_progress:
        return QueueResult(code=0, task=in_progress[0], others=in_progress[1:])

    ready = sorted((task for task in live if is_ready(state, task)), key=lambda task: task.order)
    if ready:
        return QueueResult(code=0, task=ready[0])

    todos = [task for task in live if task.status == TStatus.todo]
    if todos:
        blocked = [(task, "; ".join(blocking_labels(state, task))) for task in todos]
        blocked = [(task, label) for task, label in blocked if label]
        waiting = [
            (task, " ".join(dependency_waiting(state, task)))
            for task in todos
            if dependency_waiting(state, task)
        ]
        return QueueResult(code=4, blocked=blocked, waiting=waiting)
    if any(task.status == TStatus.done for task in live):
        return QueueResult(code=5)
    raise NextError(2, "Нет задач. Сначала `hz decompose`.")


def require_task(state: State, task_id: str) -> Task:
    task = next((item for item in state.tasks if item.id == task_id), None)
    if task is None:
        raise NextError(1, f"задача {task_id} не найдена")
    if task.status == TStatus.dropped:
        raise NextError(2, f"{task_id} снята")
    return task


def sole_in_progress(state: State) -> Task:
    found = [task for task in state.tasks if task.status == TStatus.in_progress]
    if len(found) != 1:
        hint = "Укажите id." if found else "Нет задачи в работе. Сначала `hz next --prompt`."
        raise NextError(2, hint)
    return found[0]


def take(state: State, task: Task) -> bool:
    """Готовую `todo` переводит в `in_progress`. Остальные статусы не трогает."""
    if not is_ready(state, task):
        return False
    task.status = TStatus.in_progress
    task.started_at = now_utc()
    return True


def ensure_closable(task: Task) -> None:
    if task.status == TStatus.in_progress:
        return
    if task.status == TStatus.done and task.needs_review:
        return
    if task.status == TStatus.todo:
        raise NextError(2, f"{task.id} ещё todo. Сначала `hz next --prompt`.")
    raise NextError(2, f"{task.id} уже done")


def finish(state: State, task: Task) -> None:
    ensure_closable(task)
    if task.status == TStatus.in_progress:
        task.status = TStatus.done
        task.done_at = now_utc()
        task.needs_review = False
        return
    extra = superseded_decision_ids(state, task)
    task.acked_decisions = list(dict.fromkeys([*task.acked_decisions, *extra]))
    task.needs_review = False


def position_label(state: State, task: Task) -> str:
    visible = sorted(
        (item for item in state.tasks if item.status != TStatus.dropped),
        key=lambda item: item.order,
    )
    index = next((n for n, item in enumerate(visible, start=1) if item.id == task.id), 0)
    return f"{index}/{len(visible)}"


def format_stop(state: State, result: QueueResult, block_id: str | None = None) -> str:
    if result.code == 5:
        done = sum(1 for task in live_tasks(state, block_id) if task.status == TStatus.done)
        return f"Всё сделано ({done}/{done})."
    lines = ["Нет готовой задачи."]
    if result.blocked:
        lines.append("Заблокированы вопросом")
        for task, label in result.blocked:
            lines.append(f"  {task.id} ← {label}")
        hints = []
        for task, _label in result.blocked:
            for ref in task.blocked_by:
                if blocks_task(open_ref_severity(state, ref)) and ref not in hints:
                    hints.append(ref)
        for ref in hints:
            lines.append(f'  hz audit {ref} --answer "…"')
    if result.waiting:
        lines.append("Ждут другую задачу")
        for task, deps in result.waiting:
            lines.append(f"  {task.id} ← {deps}")
    return "\n".join(lines)


def format_card(state: State, task: Task, others: list[Task] | None = None) -> str:
    owner = _block(state, task)
    lines = [
        f"{task.id}  {task.title}  {task.status.value} · {position_label(state, task)}",
    ]
    if owner is not None:
        lines.append(f"  {owner.id} {owner.title}")
    if others:
        lines.append("  также в работе: " + " ".join(item.id for item in others))
    lines.append(f"Цель      {task.goal}")
    if task.requirements:
        lines.append("Требования  " + " ".join(task.requirements))
    if owner is not None and owner.decisions:
        lines.append("Решения   " + " ".join(owner.decisions))
    if owner is not None:
        lines.append(f"Контракт  {owner.contract}")
        if owner.files:
            lines.append("Файлы     " + " · ".join(item.path for item in owner.files))
    if task.done_when:
        lines.append("Done when")
        lines.extend(f"  [ ] {item}" for item in task.done_when)
    if task.notes:
        lines.append("Заметки   " + " · ".join(task.notes))
    opened = open_nonblocking(state, task)
    if opened:
        opened_text = " · ".join(
            f"{item['id']} {item['severity']} {item['text']}" for item in opened
        )
        lines.append(f"Открыто   {opened_text}")
    blockers = blocking_labels(state, task)
    if blockers:
        lines.append("Блокер    " + " · ".join(blockers))
    if task.needs_review:
        replaced = superseded_decision_ids(state, task)
        lines.append("Ревизия   " + (" ".join(replaced) or "решение блока заменено"))
        lines.append(f"  hz next {task.id} --done")
    elif task.status == TStatus.in_progress:
        replaced = superseded_decision_ids(state, task)
        if replaced:
            lines.append("Решение блока уже заменено: " + " ".join(replaced))
    return "\n".join(lines)


def format_list(state: State) -> str:
    lines: list[str] = []
    active = [item for item in state.blocks if item.status.value == "active"]
    dropped_blocks = [item for item in state.blocks if item.status.value == "dropped"]
    for owner in active:
        tasks = sorted(
            (
                task
                for task in state.tasks
                if task.block == owner.id and task.status != TStatus.dropped
            ),
            key=lambda task: task.order,
        )
        lines.append(f"{owner.id}  {owner.title}  {_block_progress(tasks)}")
        lines.extend(_task_line(state, task) for task in tasks)
    if dropped_blocks:
        lines.append("Снятые блоки")
        for owner in dropped_blocks:
            orphans = [
                task
                for task in state.tasks
                if task.block == owner.id and task.status == TStatus.done
            ]
            if not orphans:
                continue
            lines.append(f"{owner.id}  {owner.title}")
            lines.extend(_task_line(state, task) for task in orphans)
    return "\n".join(lines) if lines else "Задач нет."


def _block_progress(tasks: list[Task]) -> str:
    if not tasks:
        return "пусто"
    if all(task.status == TStatus.done for task in tasks):
        return "done"
    if any(task.status == TStatus.in_progress for task in tasks):
        return "in progress"
    return "todo"


def _task_line(state: State, task: Task) -> str:
    mark = {"todo": " ", "in_progress": "→", "done": "✓", "dropped": "·"}[task.status.value]
    extra = ""
    if task.needs_review:
        extra = "  ⚠ needs review"
    elif blocking_labels(state, task):
        extra = "  ⛔ " + blocking_labels(state, task)[0]
    return f"  {mark} {task.id}  {task.title}{extra}"


def render_brief(state: State, task: Task, context: dict[str, Any] | None = None) -> str:
    owner = _block(state, task)
    if owner is None:
        raise NextError(2, f"у {task.id} нет блока {task.block}")
    requirements = [
        {"id": req.id, "section": req.section, "text": req.text}
        for req in state.requirements
        if req.id in task.requirements
    ]
    decisions = [
        {"id": decision.id, "kind": decision.kind.value, "text": decision.text}
        for decision in state.decisions
        if decision.id in owner.decisions and decision.superseded_by is None
    ]
    indexes = []
    if context is not None:
        indexes = [item["done_when_index"] for item in context.get("already_done") or []]
    env = Environment(
        loader=FileSystemLoader(_PROMPT_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    text = env.get_template("handoff.md").render(
        task=task,
        block=owner,
        requirements=requirements,
        decisions=decisions,
        open_items=open_nonblocking(state, task),
        context=context,
        already_done_indexes=indexes,
    )
    blockers = blocking_labels(state, task)
    if blockers:
        text += "\n## Blocked\n" + "\n".join(f"- {line}" for line in blockers) + "\n"
    return text


def load_repo_context(state: State, task: Task, runner: StageRunner) -> dict[str, Any] | None:
    root = Path(state.repo or ".")
    if not root.is_absolute():
        root = Path.cwd() / root
    owner = _block(state, task)
    if owner is None:
        return None
    response = runner.run(
        "next/context.md",
        "next/schema.json",
        _context_blocks(state, task, owner, root),
        allow_blocked=True,
    )
    uncertainties = list(response.get("uncertainties") or [])
    blocked = response.get("blocked")
    if blocked:
        uncertainties.append({"text": str(blocked.get("reason", blocked)), "blocking": True})
    return {
        "conventions": response.get("conventions") or [],
        "example_files": response.get("example_files") or [],
        "approach": response.get("approach") or [],
        "already_done": response.get("already_done") or [],
        "uncertainties": uncertainties,
    }


def _context_blocks(state: State, task: Task, owner: Block, root: Path) -> list[str]:
    requirements = [
        {"id": req.id, "text": req.text, "section": req.section}
        for req in state.requirements
        if req.id in task.requirements
    ]
    decisions = [
        {"id": decision.id, "kind": decision.kind.value, "text": decision.text}
        for decision in state.decisions
        if decision.id in owner.decisions and decision.superseded_by is None
    ]
    task_files = []
    for ref in owner.files:
        if ref.action.value != "modify":
            continue
        body = _read_text(root / ref.path)
        if body:
            task_files.append({"path": ref.path, "content": body})
    return [
        block(
            "task",
            {
                "id": task.id,
                "title": task.title,
                "goal": task.goal,
                "done_when": task.done_when,
                "notes": task.notes,
                "requirements": task.requirements,
                "depends_on": task.depends_on,
            },
        ),
        block(
            "block",
            {
                "id": owner.id,
                "title": owner.title,
                "purpose": owner.purpose,
                "contract": owner.contract,
                "files": [item.model_dump(mode="json") for item in owner.files],
                "decisions": owner.decisions,
            },
        ),
        block("requirements", requirements),
        block("decisions", decisions),
        block("repo_tree", build_tree(root)),
        block("task_files", task_files),
        block("candidates", _candidates(root, owner)),
    ]


def _candidates(root: Path, owner: Block) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen = {ref.path for ref in owner.files}
    for ref in owner.files:
        directory = (root / ref.path).parent
        if not directory.is_dir():
            continue
        suffix = Path(ref.path).suffix
        for entry in sorted(directory.iterdir()):
            if len(found) >= _MAX_CANDIDATES:
                return found
            if not entry.is_file() or entry.suffix != suffix:
                continue
            rel = str(entry.relative_to(root))
            if rel in seen:
                continue
            body = _read_text(entry)
            if not body:
                continue
            seen.add(rel)
            found.append({"path": rel, "content": body})
    return found


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:_FILE_CHARS]
    except OSError:
        return ""
