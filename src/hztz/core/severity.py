"""Вычисляемая серьёзность вопросов. В state не хранится."""

from hztz.models.state import Question, State

_RANK = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
_LEVELS = ["blocker", "high", "medium", "low"]


def question_severity(state: State, question: Question) -> str:
    """`high` для вопроса человека; иначе max severity связанных находок."""
    if question.origin.command == "user":
        return "high"
    scores = [
        _RANK[finding.severity.value]
        for finding in state.findings
        if finding.id in question.findings
    ]
    return _LEVELS[min(scores)] if scores else "low"


def open_ref_severity(state: State, ref: str) -> str | None:
    """Серьёзность открытого `A`/`O`. Закрытые и чужие id дают None."""
    if ref.startswith("A"):
        finding = next((item for item in state.findings if item.id == ref), None)
        if finding is None or finding.status.value != "open":
            return None
        return finding.severity.value
    if ref.startswith("O"):
        question = next((item for item in state.questions if item.id == ref), None)
        if question is None or question.status.value != "open":
            return None
        return question_severity(state, question)
    return None


def blocks_task(severity: str | None) -> bool:
    return severity is not None and _RANK[severity] <= _RANK["high"]
