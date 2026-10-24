"""Рендер audit.md из State."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from hztz.core.severity import open_ref_severity, question_severity
from hztz.models.state import State

_SEVERITY_RANK = {"blocker": 0, "high": 1, "medium": 2, "low": 3}


def _finding_by_id(state: State) -> dict[str, Any]:
    return {f.id: f for f in state.findings}


def _question_severity(state: State, q: Any) -> str:
    return question_severity(state, q)


def _finding_questions(state: State) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for q in state.questions:
        for fid in q.findings:
            result.setdefault(fid, []).append(q.id)
    return result


def build_view(state: State) -> dict[str, Any]:
    open_qs: list[dict[str, Any]] = [
        {
            "id": q.id,
            "text": q.text,
            "why": q.why,
            "audience": q.audience.value,
            "severity": _question_severity(state, q),
            "options": [o.model_dump(mode="json") for o in q.options],
            "findings": q.findings,
        }
        for q in state.questions
        if q.status.value == "open"
    ]
    open_qs.sort(key=lambda q: (q["audience"] != "business", _SEVERITY_RANK[q["severity"]]))

    fq = _finding_questions(state)
    return {
        "open_questions": open_qs,
        "decisions": [d.model_dump(mode="json") for d in state.decisions],
        "findings": [
            {
                **f.model_dump(mode="json"),
                "questions": fq.get(f.id, []),
                "evidence": [e.model_dump(mode="json") for e in f.evidence],
            }
            for f in state.findings
        ],
        "requirements": [r.model_dump(mode="json") for r in state.requirements],
    }


def render_audit_md(state: State) -> str:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template("audit.md.j2")
    return template.render(state=state, view=build_view(state))


_SEV_RANK = {"blocker": 0, "high": 1, "medium": 2, "low": 3}


def _decompose_item_severity(state: State, ref: str) -> str | None:
    return open_ref_severity(state, ref)


def _decompose_task_blocked(state: State, t: Any) -> bool:
    return any(
        (sev := _decompose_item_severity(state, ref)) is not None and _SEV_RANK[sev] <= 1
        for ref in t.blocked_by
    )


def _mermaid_label(text: str) -> str:
    return text.replace('"', "'")


def _build_mermaid(state: State) -> str:
    active = {t.id: t for t in state.tasks if t.status.value != "dropped"}
    by_block: dict[str, list[Any]] = {}
    for task in active.values():
        by_block.setdefault(task.block, []).append(task)
    active_block_ids = {b.id for b in state.blocks if b.status.value == "active"}
    lines = ["```mermaid", "graph LR"]
    for owner in state.blocks:
        if owner.status.value != "active":
            continue
        lines.append(f'  subgraph {owner.id}["{_mermaid_label(owner.title)}"]')
        for task in sorted(by_block.get(owner.id, []), key=lambda item: item.order):
            lines.append(f'    {task.id}["{_mermaid_label(task.title)}"]')
        lines.append("  end")
    for task in active.values():
        if task.block not in active_block_ids:
            lines.append(f'  {task.id}["{_mermaid_label(task.title)}"]')
    for task in active.values():
        for dep in task.depends_on:
            if dep in active:
                lines.append(f"  {dep} --> {task.id}")
    lines.append("```")
    return "\n".join(lines)


def _blocked_because(state: State, task: Any) -> str:
    parts: list[str] = []
    for ref in task.blocked_by:
        severity = _decompose_item_severity(state, ref)
        if severity is None or _SEV_RANK[severity] > 1:
            continue
        if ref.startswith("O"):
            question = next((item for item in state.questions if item.id == ref), None)
            if question is None:
                continue
            parts.append(f"{ref} [{severity}, {question.audience.value}] «{question.text}»")
        else:
            finding = next((item for item in state.findings if item.id == ref), None)
            if finding is None:
                continue
            parts.append(f"{ref} [{severity}] «{finding.title}»")
    return ", ".join(parts)


def build_decompose_view(state: State) -> dict[str, Any]:
    tasks_by_block: dict[str, list[Any]] = {}
    for t in state.tasks:
        tasks_by_block.setdefault(t.block, []).append(t)
    for lst in tasks_by_block.values():
        lst.sort(key=lambda t: t.order)

    blocks = [b.model_dump(mode="json") for b in state.blocks if b.status.value == "active"]
    for b in blocks:
        b["tasks"] = [
            {
                **t.model_dump(mode="json"),
                "blocked": _decompose_task_blocked(state, t),
            }
            for t in tasks_by_block.get(b["id"], [])
            if t.status.value != "dropped"
        ]

    blocked = [
        {"id": t.id, "because": _blocked_because(state, t)}
        for t in state.tasks
        if t.status.value == "todo" and _decompose_task_blocked(state, t)
    ]

    coverage: dict[str, Any] = {}
    for r in state.requirements:
        blk = next((b.id for b in state.blocks if r.id in b.requirements), None)
        tsk = [t.id for t in state.tasks if r.id in t.requirements]
        coverage[r.id] = {"block": blk, "tasks": tsk}

    return {
        "blocks": blocks,
        "blocked_tasks": blocked,
        "coverage": coverage,
        "uncovered": state.coverage.uncovered,
        "skipped": state.coverage.skipped,
        "assumptions": [
            d for d in state.decisions if d.kind.value == "assumption" and d.superseded_by is None
        ],
    }


def render_decomposition_md(state: State) -> str:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template("decomposition.md.j2")
    return template.render(
        state=state, view=build_decompose_view(state), mermaid=_build_mermaid(state)
    )
