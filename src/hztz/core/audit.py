"""Оркестрация `hz audit`: три стадии, построение state, мутации, сопоставление."""

from pathlib import Path
from typing import Any

from hztz.core.pipeline import StageRunner, block, raw_block
from hztz.core.store import StateStore, bump_counter
from hztz.models.state import (
    AStatus,
    Audience,
    Decision,
    DKind,
    Evidence,
    Finding,
    FindingOrigin,
    Location,
    Option,
    OStatus,
    Question,
    QuestionOrigin,
    Requirement,
    Resolution,
    RStatus,
    Scores,
    Spec,
    SpecVersion,
    State,
    Summary,
    now_utc,
)

# --- block serializers ------------------------------------------------------


def _req_block(r: Requirement) -> dict[str, Any]:
    return {
        "id": r.id,
        "text": r.text,
        "kind": r.kind.value,
        "section": r.section,
        "line_start": r.location.line_start,
        "line_end": r.location.line_end,
    }


def _finding_block(f: Finding) -> dict[str, Any]:
    return {
        "id": f.id,
        "kind": f.kind.value,
        "missing": f.missing.value if f.missing else None,
        "severity": f.severity.value,
        "confidence": f.confidence.value,
        "title": f.title,
        "detail": f.detail,
        "requirements": f.requirements,
        "evidence": [e.model_dump(mode="json") for e in f.evidence],
        "what_to_specify": f.what_to_specify,
    }


def _decision_block(d: Decision) -> dict[str, Any]:
    return {
        "id": d.id,
        "kind": d.kind.value,
        "text": d.text,
        "closes": d.closes,
        "option": d.option,
    }


def _existing_finding_block(f: Finding) -> dict[str, Any]:
    quote = next((e.quote for e in f.evidence if e.quote), None)
    return {
        "id": f.id,
        "kind": f.kind.value,
        "requirements": f.requirements,
        "title": f.title,
        "quote": quote,
        "status": f.status.value,
    }


def _existing_question_block(q: Question) -> dict[str, Any]:
    return {"id": q.id, "text": q.text, "findings": q.findings, "status": q.status.value}


# --- validation --------------------------------------------------------------


def _normalize(text: str) -> str:
    return " ".join(text.split())


def verify_quote(numbered: str, quote: str) -> bool:
    return _normalize(quote) in _normalize(numbered)


# --- анализ (первый запуск и повторный) --------------------------------------


def _build_requirements(
    state: State, resp: dict[str, Any], previous: list[Requirement]
) -> list[Requirement]:
    prev_by_id = {r.id: r for r in previous}
    previous_ids = set(prev_by_id)

    result: list[Requirement] = []
    matched_ids: set[str] = set()
    for item in resp["requirements"]:
        matches = item.get("matches")
        if matches and matches in prev_by_id:
            rid = matches
            matched_ids.add(rid)
            prev = prev_by_id[rid]
            result.append(
                prev.model_copy(
                    update={
                        "text": item["text"],
                        "section": item["section"],
                        "location": {
                            "line_start": item["line_start"],
                            "line_end": item["line_end"],
                        },
                        "kind": item["kind"],
                        "status": "active",
                    }
                )
            )
        else:
            rid = bump_counter(state, "R")
            result.append(
                Requirement(
                    id=rid,
                    text=item["text"],
                    section=item["section"],
                    location=Location(line_start=item["line_start"], line_end=item["line_end"]),
                    kind=item["kind"],
                    status=RStatus.active,
                )
            )

    for old_id in previous_ids - matched_ids:
        if old_id in prev_by_id:
            prev_by_id[old_id].status = RStatus.removed
            result.append(prev_by_id[old_id])

    return result


def _build_findings(
    state: State, resp: dict[str, Any], previous: list[Finding], numbered: str
) -> list[Finding]:
    prev_by_id = {f.id: f for f in previous}
    matched: set[str] = set()
    result: list[Finding] = []

    for item in resp["findings"]:
        matches = item.get("matches")
        if matches and matches in prev_by_id:
            f = prev_by_id[matches]
            matched.add(matches)
            result.append(
                f.model_copy(
                    update={
                        "kind": item["kind"],
                        "missing": item.get("missing"),
                        "severity": item["severity"],
                        "confidence": item["confidence"],
                        "title": item["title"],
                        "detail": item["detail"],
                        "what_to_specify": item["what_to_specify"],
                        "requirements": item["requirements"],
                        "evidence": [Evidence.model_validate(e) for e in item["evidence"]],
                    }
                )
            )
        else:
            aid = bump_counter(state, "A")
            result.append(
                Finding(
                    id=aid,
                    kind=item["kind"],
                    missing=item.get("missing"),
                    severity=item["severity"],
                    confidence=item["confidence"],
                    title=item["title"],
                    detail=item["detail"],
                    what_to_specify=item["what_to_specify"],
                    requirements=item["requirements"],
                    evidence=[Evidence.model_validate(e) for e in item["evidence"]],
                    origin=FindingOrigin(command="audit"),
                )
            )

    # находки, не совпавшие и исчезнувшие из нового текста
    for old in previous:
        if old.id in matched or old.status != "open":
            continue
        quotes = [e.quote for e in old.evidence if e.quote and e.line_start is not None]
        if quotes and not verify_quote(numbered, quotes[0]):
            old.status = AStatus.resolved
            old.resolution = Resolution(by="spec_changed", reason="spec_changed")
        result.append(old)

    return result


def _build_questions(
    state: State, resp: dict[str, Any], previous: list[Question]
) -> list[Question]:
    prev_by_id = {q.id: q for q in previous}
    matched: set[str] = set()
    result: list[Question] = []

    for item in resp["questions"]:
        matches = item.get("matches")
        if matches and matches in prev_by_id:
            q = prev_by_id[matches]
            matched.add(matches)
            result.append(
                q.model_copy(
                    update={
                        "text": item["text"],
                        "why": item["why"],
                        "findings": item["findings"],
                        "options": [Option.model_validate(o) for o in item["options"]],
                    }
                )
            )
        else:
            oid = bump_counter(state, "O")
            result.append(
                Question(
                    id=oid,
                    text=item["text"],
                    why=item["why"],
                    audience=item["audience"],
                    findings=item["findings"],
                    options=[Option.model_validate(o) for o in item["options"]],
                    origin=QuestionOrigin(command="audit"),
                )
            )

    for old in previous:
        if old.id not in matched and old.status == "open":
            result.append(old)

    return result


def analyze(
    spec_path: Path, store: StateStore, runner: StageRunner, existing: State | None
) -> State:
    """Полный анализ (три стадии) и построение state."""
    hash_value, numbered, snap_path = store.snapshot(spec_path)

    prev_reqs = existing.requirements if existing else []
    prev_findings = existing.findings if existing else []
    prev_questions = existing.questions if existing else []

    # Стадия 1: extract
    extract_blocks: list[str] = [raw_block("spec", numbered)]
    if prev_reqs:
        extract_blocks.append(block("previous_requirements", [_req_block(r) for r in prev_reqs]))
    extract_resp = runner.run("audit/extract.md", "audit/schema/extract.json", extract_blocks)

    if existing is None:
        state = State(spec=None, summary=Summary(feynman="", in_scope=[], out_of_scope=[]))
    else:
        state = existing

    state.requirements = _build_requirements(state, extract_resp, prev_reqs)
    summary = extract_resp["summary"]
    state.summary = Summary(
        feynman=summary["feynman"],
        in_scope=summary["in_scope"],
        out_of_scope=summary["out_of_scope"],
        scores=Scores(),
    )

    if state.spec is None:
        state.spec = Spec(path=str(spec_path), hash=hash_value, snapshot=str(snap_path))
    elif state.spec.hash != hash_value:
        state.spec.versions.append(
            SpecVersion(
                hash=state.spec.hash,
                path=state.spec.path,
                audited_at=now_utc(),
            )
        )
        state.spec.path = str(spec_path)
        state.spec.hash = hash_value
        state.spec.snapshot = str(snap_path)

    # Стадия 2: findings
    findings_blocks: list[str] = [
        raw_block("spec", numbered),
        block("requirements", [_req_block(r) for r in state.requirements]),
        block(
            "summary",
            {
                "feynman": state.summary.feynman,
                "in_scope": state.summary.in_scope,
                "out_of_scope": state.summary.out_of_scope,
            },
        ),
    ]
    if prev_findings:
        findings_blocks.append(
            block("existing_findings", [_existing_finding_block(f) for f in prev_findings])
        )
    if prev_decisions := (existing.decisions if existing else []):
        findings_blocks.append(block("decisions", [_decision_block(d) for d in prev_decisions]))
    findings_resp = runner.run("audit/findings.md", "audit/schema/findings.json", findings_blocks)
    state.findings = _build_findings(state, findings_resp, prev_findings, numbered)

    # Стадия 3: questions
    open_findings = [f for f in state.findings if f.status == "open"]
    questions_blocks: list[str] = [
        raw_block("spec", numbered),
        block("requirements", [_req_block(r) for r in state.requirements]),
        block("findings", [_finding_block(f) for f in open_findings]),
    ]
    if prev_questions:
        questions_blocks.append(
            block("existing_questions", [_existing_question_block(q) for q in prev_questions])
        )
    questions_resp = runner.run(
        "audit/questions.md", "audit/schema/questions.json", questions_blocks
    )
    state.questions = _build_questions(state, questions_resp, prev_questions)

    store.save(state)
    return state


# --- мутации -----------------------------------------------------------------


def answer_or_assume(
    state: State, question_id: str, text: str, kind: DKind, option: str | None = None
) -> State:
    question = next((q for q in state.questions if q.id == question_id), None)
    if question is None:
        raise ValueError(f"вопрос {question_id} не найден")

    did = bump_counter(state, "D")
    decision = Decision(id=did, kind=kind, text=text, closes=[question_id], option=option)
    state.decisions.append(decision)

    question.status = OStatus.answered if kind == DKind.answer else OStatus.assumed
    for f in state.findings:
        if f.id in question.findings and f.status == "open":
            f.status = AStatus.resolved
            f.resolution = Resolution(by=did)
    return state


def dismiss(state: State, obj_id: str, text: str | None = None) -> State:
    for f in state.findings:
        if f.id == obj_id:
            f.status = AStatus.dismissed
            return state
    for q in state.questions:
        if q.id == obj_id:
            q.status = OStatus.dismissed
            return state
    raise ValueError(f"объект {obj_id} не найден")


def add_question(state: State, text: str, task: str | None = None) -> State:
    target = None
    if task is not None:
        target = next((item for item in state.tasks if item.id == task), None)
        if target is None:
            raise ValueError(f"задача {task} не найдена")
    oid = bump_counter(state, "O")
    state.questions.append(
        Question(
            id=oid,
            text=text,
            why="",
            audience=Audience.technical,
            findings=[],
            origin=QuestionOrigin(command="user", task=task),
        )
    )
    if target is not None and oid not in target.blocked_by:
        target.blocked_by.append(oid)
    return state
