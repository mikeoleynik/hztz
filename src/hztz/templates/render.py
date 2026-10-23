"""Рендер audit.md из State."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from hztz.models.state import State

_SEVERITY_RANK = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
_SEVERITIES = ["blocker", "high", "medium", "low"]


def _finding_by_id(state: State) -> dict[str, Any]:
    return {f.id: f for f in state.findings}


def _question_severity(state: State, q: Any) -> str:
    by_id = _finding_by_id(state)
    ranks = [_SEVERITY_RANK[by_id[fid].severity.value] for fid in q.findings if fid in by_id]
    return _SEVERITIES[min(ranks)] if ranks else "low"


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
