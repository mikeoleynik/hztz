"""Оркестрация `hz decompose`: один вызов LLM → key→id → uncertainties → покрытие."""

import re
from difflib import SequenceMatcher
from typing import Any

from hztz.core.pipeline import StageRunner, block
from hztz.core.store import bump_counter
from hztz.models.state import (
    Block,
    BStatus,
    Decision,
    Evidence,
    FileRef,
    Finding,
    FindingOrigin,
    Option,
    Question,
    QuestionOrigin,
    Requirement,
    State,
    Task,
    TStatus,
)

_ID_RE = re.compile(r"^[RAODBT][0-9]+$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TITLE_SIMILARITY = 0.85


class DecomposeError(Exception):
    pass


# --- сериализаторы блоков ---------------------------------------------------


def _req_block(r: Requirement) -> dict[str, Any]:
    return {
        "id": r.id,
        "text": r.text,
        "kind": r.kind.value,
        "section": r.section,
        "line_start": r.location.line_start,
        "line_end": r.location.line_end,
    }


def _decision_block(d: Decision) -> dict[str, Any]:
    return {
        "id": d.id,
        "kind": d.kind.value,
        "text": d.text,
        "closes": d.closes,
        "option": d.option,
    }


def question_severity(state: State, findings: list[str]) -> str:
    """`O.severity = max(A.severity)` по связанным находкам."""
    ranks = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
    fmap = {f.id: f for f in state.findings}
    scores = [ranks[fmap[fid].severity.value] for fid in findings if fid in fmap]
    return ["blocker", "high", "medium", "low"][min(scores)] if scores else "low"


def _question_requirements(state: State, q: Question) -> list[str]:
    fmap = {f.id: f for f in state.findings}
    reqs: list[str] = []
    for fid in q.findings:
        if fid in fmap:
            reqs.extend(fmap[fid].requirements)
    return list(dict.fromkeys(reqs))


def _open_items(state: State) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for f in state.findings:
        if f.status.value == "open":
            items.append(
                {
                    "id": f.id,
                    "type": "A",
                    "severity": f.severity.value,
                    "requirements": f.requirements,
                    "text": f.title,
                }
            )
    for q in state.questions:
        if q.status.value == "open":
            items.append(
                {
                    "id": q.id,
                    "type": "O",
                    "severity": question_severity(state, q.findings),
                    "audience": q.audience.value,
                    "requirements": _question_requirements(state, q),
                    "text": q.text,
                }
            )
    return items


def _existing_block_block(b: Block) -> dict[str, Any]:
    return {
        "id": b.id,
        "kind": b.kind.value,
        "title": b.title,
        "requirements": b.requirements,
        "decisions": b.decisions,
    }


def _existing_task_block(t: Task) -> dict[str, Any]:
    return {
        "id": t.id,
        "status": t.status.value,
        "title": t.title,
        "block": t.block,
        "requirements": t.requirements,
        "order": t.order,
    }


# --- резолв ссылок -----------------------------------------------------------


def _resolve(ref: str, key_map: dict[str, str], existing: set[str]) -> str:
    if _ID_RE.match(ref):
        if ref not in existing:
            raise DecomposeError(f"ссылка на несуществующий id: {ref}")
        return ref
    if _KEY_RE.match(ref):
        if ref not in key_map:
            raise DecomposeError(f"ключ без объекта: {ref}")
        return key_map[ref]
    raise DecomposeError(f"ссылка не ключ и не id: {ref}")


def _resolve_many(refs: list[str], key_map: dict[str, str], existing: set[str]) -> list[str]:
    return [_resolve(r, key_map, existing) for r in refs]


def _norm_title(title: str) -> str:
    folded = title.casefold()
    cleaned = re.sub(r"[^\w\s]", " ", folded, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _titles_similar(left: str, right: str) -> bool:
    a, b = _norm_title(left), _norm_title(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= _TITLE_SIMILARITY


def _block_key(kind: str, requirements: list[str]) -> tuple[str, tuple[str, ...]]:
    return (kind, tuple(sorted(requirements)))


def _take_match(match_id: str, used: set[str], label: str) -> str:
    if match_id in used:
        raise DecomposeError(f"{label} {match_id} указан дважды")
    used.add(match_id)
    return match_id


def _assign_block_ids(
    state: State, raw_blocks: list[dict[str, Any]], old_blocks: dict[str, Block]
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for raw in raw_blocks:
        key = str(raw["key"])
        if key in mapping:
            raise DecomposeError(f"повтор ключа блока: {key}")
        matches = raw.get("matches")
        if matches:
            if not re.fullmatch(r"B[0-9]+", str(matches)):
                raise DecomposeError(f"matches блока не id: {matches}")
            if matches not in old_blocks:
                raise DecomposeError(f"matches на несуществующий блок: {matches}")
            mapping[key] = _take_match(str(matches), used, "блок")
            continue
        key_sig = _block_key(str(raw["kind"]), list(raw["requirements"]))
        candidates = [
            old
            for old in old_blocks.values()
            if old.id not in used
            and old.status == BStatus.active
            and _block_key(old.kind.value, old.requirements) == key_sig
        ]
        if len(candidates) == 1:
            mapping[key] = _take_match(candidates[0].id, used, "блок")
        else:
            mapping[key] = bump_counter(state, "B")
    return mapping


def _assign_uncertainty_ids(
    state: State, raw: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, str]]:
    finding_ids: dict[str, str] = {}
    question_ids: dict[str, str] = {}
    for item in raw:
        fkey = str(item["finding"]["key"])
        qkey = str(item["question"]["key"])
        if fkey in finding_ids:
            raise DecomposeError(f"повтор ключа находки: {fkey}")
        if qkey in question_ids:
            raise DecomposeError(f"повтор ключа вопроса: {qkey}")
        finding_ids[fkey] = bump_counter(state, "A")
        question_ids[qkey] = bump_counter(state, "O")
    return finding_ids, question_ids


def _assign_task_ids(
    state: State,
    raw_tasks: list[dict[str, Any]],
    old_tasks: dict[str, Task],
    block_ids: dict[str, str],
    old_block_ids: set[str],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for raw in raw_tasks:
        key = str(raw["key"])
        if key in mapping:
            raise DecomposeError(f"повтор ключа задачи: {key}")
        block_id = _resolve(str(raw["block"]), block_ids, old_block_ids)
        matches = raw.get("matches")
        if matches:
            if not re.fullmatch(r"T[0-9]+", str(matches)):
                raise DecomposeError(f"matches задачи не id: {matches}")
            old = old_tasks.get(str(matches))
            if old is None:
                raise DecomposeError(f"matches на несуществующую задачу: {matches}")
            if old.status in (TStatus.done, TStatus.in_progress):
                raise DecomposeError(f"matches на задачу {matches} со статусом {old.status.value}")
            mapping[key] = _take_match(str(matches), used, "задача")
            continue
        candidates = [
            old
            for old in old_tasks.values()
            if old.id not in used
            and old.status == TStatus.todo
            and old.block == block_id
            and _titles_similar(old.title, str(raw["title"]))
        ]
        if len(candidates) == 1:
            mapping[key] = _take_match(candidates[0].id, used, "задача")
        else:
            mapping[key] = bump_counter(state, "T")
    return mapping


# --- оркестрация --------------------------------------------------------------


def run_decompose(state: State, runner: StageRunner, repo_context: dict[str, Any] | None) -> State:
    old_blocks = {b.id: b for b in state.blocks}
    old_tasks = {t.id: t for t in state.tasks}
    old_finding_ids = {f.id for f in state.findings}
    old_question_ids = {q.id for q in state.questions}

    blocks_in: list[str] = [
        block(
            "summary",
            {
                "feynman": state.summary.feynman if state.summary else "",
                "in_scope": state.summary.in_scope if state.summary else [],
                "out_of_scope": state.summary.out_of_scope if state.summary else [],
            },
        ),
        block("requirements", [_req_block(r) for r in state.requirements]),
        block(
            "decisions",
            [_decision_block(d) for d in state.decisions if d.superseded_by is None],
        ),
        block("open_items", _open_items(state)),
    ]
    if repo_context:
        blocks_in.append(block("repo_context", repo_context))
    if old_blocks:
        blocks_in.append(block("existing_blocks", [_existing_block_block(b) for b in state.blocks]))
    if old_tasks:
        blocks_in.append(block("existing_tasks", [_existing_task_block(t) for t in state.tasks]))

    resp = runner.run("decompose/prompt.md", "decompose/schema.json", blocks_in)
    raw_blocks = list(resp["blocks"])
    raw_tasks = list(resp["tasks"])
    raw_uncertainties = list(resp["uncertainties"])

    block_key_to_id = _assign_block_ids(state, raw_blocks, old_blocks)
    finding_key_to_id, question_key_to_id = _assign_uncertainty_ids(state, raw_uncertainties)
    task_key_to_id = _assign_task_ids(state, raw_tasks, old_tasks, block_key_to_id, set(old_blocks))

    old_block_ids = set(old_blocks)
    old_task_ids = set(old_tasks)
    aq_keys = {**question_key_to_id, **finding_key_to_id}
    old_aq_ids = old_finding_ids | old_question_ids

    new_blocks: list[Block] = []
    for raw in raw_blocks:
        new_blocks.append(
            Block(
                id=block_key_to_id[raw["key"]],
                kind=raw["kind"],
                title=raw["title"],
                purpose=raw["purpose"],
                requirements=list(raw["requirements"]),
                decisions=list(raw["decisions"]),
                contract=raw["contract"],
                files=[FileRef.model_validate(f) for f in raw["files"]],
            )
        )

    new_tasks: list[Task] = []
    for raw in raw_tasks:
        new_tasks.append(
            Task(
                id=task_key_to_id[raw["key"]],
                block=_resolve(str(raw["block"]), block_key_to_id, old_block_ids),
                order=int(raw["order"]),
                title=raw["title"],
                goal=raw["goal"],
                requirements=list(raw["requirements"]),
                depends_on=_resolve_many(list(raw["depends_on"]), task_key_to_id, old_task_ids),
                blocked_by=_resolve_many(list(raw["blocked_by"]), aq_keys, old_aq_ids),
                done_when=list(raw["done_when"]),
                notes=list(raw["notes"]),
            )
        )

    _apply_uncertainties(
        state,
        raw_uncertainties,
        finding_key_to_id,
        question_key_to_id,
        task_key_to_id,
        old_task_ids,
        old_finding_ids,
        new_tasks,
    )
    final_blocks, final_tasks = _merge(state, new_blocks, new_tasks, old_blocks, old_tasks)
    uncovered, skipped = _coverage(state, final_blocks, resp)
    state.blocks = final_blocks
    state.tasks = final_tasks
    state.coverage.uncovered = uncovered
    state.coverage.skipped = skipped
    _validate_graph(state)
    _flag_needs_review(state)
    return state


def _apply_uncertainties(
    state: State,
    raw: list[dict[str, Any]],
    finding_ids: dict[str, str],
    question_ids: dict[str, str],
    task_ids: dict[str, str],
    old_task_ids: set[str],
    old_finding_ids: set[str],
    new_tasks: list[Task],
) -> None:
    for item in raw:
        fid = finding_ids[item["finding"]["key"]]
        qid = question_ids[item["question"]["key"]]
        finding = item["finding"]
        question = item["question"]
        affects = _resolve_many(list(item["affects"]), task_ids, old_task_ids)
        first = _find_task(new_tasks, state, affects[0]) if affects else None
        origin_block = first.block if first is not None else None

        state.findings.append(
            Finding(
                id=fid,
                kind=finding["kind"],
                missing=finding.get("missing"),
                severity=finding["severity"],
                confidence=finding["confidence"],
                title=finding["title"],
                detail=finding["detail"],
                what_to_specify=finding["what_to_specify"],
                requirements=list(finding["requirements"]),
                evidence=[Evidence.model_validate(e) for e in finding["evidence"]],
                origin=FindingOrigin(command="decompose", block=origin_block),
            )
        )
        linked = _resolve_many(list(question["findings"]), finding_ids, old_finding_ids)
        state.questions.append(
            Question(
                id=qid,
                text=question["text"],
                why=question["why"],
                audience=question["audience"],
                findings=linked,
                options=[Option.model_validate(o) for o in question["options"]],
                origin=QuestionOrigin(command="decompose", task=affects[0] if affects else None),
            )
        )

        for task_id in affects:
            target = _find_task(new_tasks, state, task_id)
            if target is None:
                continue
            if item["blocking"]:
                if qid not in target.blocked_by:
                    target.blocked_by.append(qid)
            else:
                note = f"открыто {qid} ({finding['severity']})"
                if note not in target.notes:
                    target.notes.append(note)


def _merge(
    state: State,
    new_blocks: list[Block],
    new_tasks: list[Task],
    old_blocks: dict[str, Block],
    old_tasks: dict[str, Task],
) -> tuple[list[Block], list[Task]]:
    matched_blocks = {b.id for b in new_blocks if b.id in old_blocks}
    matched_tasks = {t.id for t in new_tasks if t.id in old_tasks}

    for previous_block in state.blocks:
        if previous_block.status == BStatus.active and previous_block.id not in matched_blocks:
            previous_block.status = BStatus.dropped
    for previous_task in state.tasks:
        if previous_task.status == TStatus.todo and previous_task.id not in matched_tasks:
            previous_task.status = TStatus.dropped

    new_block_ids = {b.id for b in new_blocks}
    dropped_blocks = [
        b for b in state.blocks if b.status == BStatus.dropped and b.id not in new_block_ids
    ]
    final_blocks = new_blocks + dropped_blocks

    new_task_ids = {t.id for t in new_tasks}
    kept = [
        t
        for t in state.tasks
        if t.status in (TStatus.done, TStatus.in_progress) and t.id not in new_task_ids
    ]
    kept.sort(key=lambda t: t.order)
    fresh = sorted(new_tasks, key=lambda t: t.order)
    dropped_tasks = [
        t for t in state.tasks if t.status == TStatus.dropped and t.id not in new_task_ids
    ]
    final_tasks = kept + fresh + dropped_tasks
    for index, task in enumerate(final_tasks, start=1):
        task.order = index
    return final_blocks, final_tasks


def _coverage(
    state: State, blocks: list[Block], resp: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    covered: set[str] = set()
    for owner in blocks:
        if owner.status == BStatus.active:
            covered.update(owner.requirements)
    skipped_raw = resp.get("skipped") or []
    uncovered_raw = resp.get("uncovered") or []
    skipped = [dict(entry) for entry in skipped_raw]
    skipped_ids = {str(entry["requirement"]) for entry in skipped if "requirement" in entry}
    uncovered_llm = {
        str(entry["requirement"]): dict(entry) for entry in uncovered_raw if "requirement" in entry
    }
    uncovered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for req in state.requirements:
        if req.status.value != "active" or req.id in covered or req.id in skipped_ids:
            continue
        seen.add(req.id)
        uncovered.append(
            uncovered_llm.get(
                req.id,
                {"requirement": req.id, "reason": "no_behaviour", "detail": "нет блока"},
            )
        )
    for req_id, entry in uncovered_llm.items():
        if req_id not in seen and req_id not in covered and req_id not in skipped_ids:
            uncovered.append(entry)
    return uncovered, skipped


def _find_task(new_tasks: list[Task], state: State, tid: str) -> Task | None:
    for task in new_tasks:
        if task.id == tid:
            return task
    for task in state.tasks:
        if task.id == tid:
            return task
    return None


def _validate_graph(state: State) -> None:
    blocks = {b.id: b for b in state.blocks}
    tasks = {t.id: t for t in state.tasks}
    if len(blocks) != len(state.blocks) or len(tasks) != len(state.tasks):
        raise DecomposeError("повторяющийся id")
    finding_ids = {f.id for f in state.findings}
    question_ids = {q.id for q in state.questions}
    active = [t for t in state.tasks if t.status != TStatus.dropped]

    for task in active:
        owner = blocks.get(task.block)
        if owner is None:
            raise DecomposeError(f"{task.id}: блок {task.block} не существует")
        if task.status == TStatus.todo and owner.status != BStatus.active:
            raise DecomposeError(f"{task.id}: блок {task.block} не active")
        if not task.requirements:
            raise DecomposeError(f"{task.id}: пустой requirements")
        if not set(task.requirements) <= set(owner.requirements):
            raise DecomposeError(f"{task.id}: requirements не подмножество {owner.id}")
        for dep in task.depends_on:
            other = tasks.get(dep)
            if other is None:
                raise DecomposeError(f"{task.id}: depends_on {dep} не существует")
            if other.status == TStatus.dropped:
                raise DecomposeError(f"{task.id}: depends_on указывает на dropped {dep}")
        for ref in task.blocked_by:
            if not re.fullmatch(r"[AO][0-9]+", ref):
                raise DecomposeError(f"{task.id}: blocked_by {ref} не A/O")
            pool = finding_ids if ref.startswith("A") else question_ids
            if ref not in pool:
                raise DecomposeError(f"{task.id}: blocked_by {ref} не существует")

    _assert_dag(active)


def _assert_dag(tasks: list[Task]) -> None:
    ids = {t.id for t in tasks}
    graph = {t.id: [dep for dep in t.depends_on if dep in ids] for t in tasks}
    color = dict.fromkeys(ids, 0)

    def visit(node: str) -> None:
        color[node] = 1
        for nxt in graph[node]:
            if color[nxt] == 1:
                raise DecomposeError(f"цикл depends_on: {node} → {nxt}")
            if color[nxt] == 0:
                visit(nxt)
        color[node] = 2

    for node in ids:
        if color[node] == 0:
            visit(node)


def _flag_needs_review(state: State) -> None:
    superseded = {d.id for d in state.decisions if d.superseded_by is not None}
    block_by_id = {b.id: b for b in state.blocks}
    for task in state.tasks:
        if task.status != TStatus.done:
            continue
        owner = block_by_id.get(task.block)
        if owner and any(did in superseded for did in owner.decisions):
            task.needs_review = True
