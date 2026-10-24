"""Очередь, бриф и закрытие `hz next`."""

import json

import pytest
from typer.testing import CliRunner

from hztz.cli.main import app
from hztz.core.decompose import _flag_needs_review
from hztz.core.store import StateStore, hash_text
from hztz.models.state import (
    Audience,
    BKind,
    Block,
    BStatus,
    Decision,
    DKind,
    FileAction,
    FileRef,
    Question,
    QuestionOrigin,
    Spec,
    State,
    Task,
    TStatus,
)

runner = CliRunner()


def _block(bid: str = "B1", **kwargs: object) -> Block:
    data: dict[str, object] = {
        "id": bid,
        "kind": BKind.service,
        "title": bid,
        "purpose": "p",
        "requirements": ["R1"],
        "contract": "c",
    }
    data.update(kwargs)
    return Block(**data)  # type: ignore[arg-type]


def _task(tid: str, order: int = 1, **kwargs: object) -> Task:
    data: dict[str, object] = {
        "id": tid,
        "block": "B1",
        "order": order,
        "title": tid,
        "goal": f"goal {tid}",
        "requirements": ["R1"],
        "done_when": ["готово"],
    }
    data.update(kwargs)
    return Task(**data)  # type: ignore[arg-type]


def _question(oid: str, task: str) -> Question:
    return Question(
        id=oid,
        text="формат даты не задан",
        why="",
        audience=Audience.technical,
        findings=[],
        origin=QuestionOrigin(command="user", task=task),
    )


def _save(tmp_path, state: State) -> State:
    StateStore(tmp_path).save(state)
    return state


@pytest.fixture()
def project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_show_ready_todo_is_read_only(project):
    _save(project, State(blocks=[_block()], tasks=[_task("T5", order=2), _task("T1", order=1)]))
    result = runner.invoke(app, ["next"])
    assert result.exit_code == 0
    assert "T1" in result.stdout
    assert "goal T1" in result.stdout
    state = StateStore(project).load()
    assert state is not None
    assert state.tasks[1].status == TStatus.todo
    assert state.tasks[1].started_at is None


def test_prompt_takes_ready_todo_and_prints_only_the_brief(project):
    _save(project, State(blocks=[_block()], tasks=[_task("T5")]))
    result = runner.invoke(app, ["next", "--prompt"])
    assert result.exit_code == 0
    assert result.stdout.startswith("# Task T5")
    assert "Нет готовой" not in result.stdout
    state = StateStore(project).load()
    assert state is not None
    assert state.tasks[0].status == TStatus.in_progress
    assert state.tasks[0].started_at is not None
    assert (project / ".hz" / "decomposition.md").exists()


def test_second_worker_and_reprompt(project):
    _save(
        project,
        State(
            blocks=[_block()],
            tasks=[_task("T5", status=TStatus.in_progress), _task("T8", order=2)],
        ),
    )
    taken = runner.invoke(app, ["next", "T8", "--prompt"])
    assert taken.exit_code == 0
    state = StateStore(project).load()
    assert state is not None
    assert {task.id: task.status for task in state.tasks} == {
        "T5": TStatus.in_progress,
        "T8": TStatus.in_progress,
    }
    ambiguous = runner.invoke(app, ["next", "--prompt"])
    assert ambiguous.exit_code == 2
    assert ambiguous.stdout == ""
    assert "T5" in ambiguous.stderr and "T8" in ambiguous.stderr


def test_blocked_todo_is_not_taken(project):
    _save(
        project,
        State(
            blocks=[_block()],
            tasks=[_task("T7", blocked_by=["O4"])],
            questions=[_question("O4", "T7")],
        ),
    )
    result = runner.invoke(app, ["next", "T7", "--prompt"])
    assert result.exit_code == 0
    assert "# Task T7" in result.stdout
    state = StateStore(project).load()
    assert state is not None
    assert state.tasks[0].status == TStatus.todo


def test_greenfield_does_not_call_the_llm(project, monkeypatch):
    def boom() -> None:
        raise AssertionError("LLM")

    monkeypatch.setattr("hztz.cli.next.StageRunner", boom)
    _save(project, State(blocks=[_block()], tasks=[_task("T5")]))
    result = runner.invoke(app, ["next", "--prompt"])
    assert result.exit_code == 0
    assert "goal T5" in result.stdout


def test_context_blocked_stays_in_the_brief(project, monkeypatch):
    class Runner:
        def __init__(self) -> None:
            self.allow_blocked = None

        def run(self, prompt: str, schema: str, blocks: list[str], allow_blocked: bool = False):
            self.allow_blocked = allow_blocked
            assert "app/pay.py" in "\n".join(blocks)
            return {
                "blocked": {"reason": "нет образца", "refs": []},
                "example_files": [],
                "conventions": [],
                "approach": ["сделать контракт"],
                "already_done": [],
                "uncertainties": [{"text": "таймаут", "blocking": False}],
            }

    monkeypatch.setattr("hztz.cli.next.detect_repo", lambda root: True)
    monkeypatch.setattr("hztz.cli.next.load_config_or_exit", lambda: None)
    monkeypatch.setattr("hztz.cli.next.StageRunner", Runner)
    _save(
        project,
        State(
            blocks=[_block(files=[FileRef(path="app/pay.py", action=FileAction.modify)])],
            tasks=[_task("T5")],
        ),
    )
    result = runner.invoke(app, ["next", "--prompt"])
    assert result.exit_code == 0
    assert "UNRESOLVED" in result.stdout
    assert "нет образца" in result.stdout
    state = StateStore(project).load()
    assert state is not None
    assert state.questions == []
    assert state.findings == []


def test_exit_4_splits_blockers_and_waiting(project):
    _save(
        project,
        State(
            blocks=[_block()],
            tasks=[
                _task("T7", blocked_by=["O4"]),
                _task("T8", order=2, depends_on=["T7"]),
            ],
            questions=[_question("O4", "T7")],
        ),
    )
    human = runner.invoke(app, ["next"])
    assert human.exit_code == 4
    assert "Заблокированы вопросом" in human.stdout
    assert "Ждут другую задачу" in human.stdout
    assert "O4" in human.stdout
    assert "hz audit O4" in human.stdout
    assert "hz audit T8" not in human.stdout
    prompted = runner.invoke(app, ["next", "--prompt", "-q"])
    assert prompted.exit_code == 4
    assert prompted.stdout == ""
    assert prompted.stderr == ""


def test_exit_5_when_everything_is_done(project):
    _save(project, State(blocks=[_block()], tasks=[_task("T1", status=TStatus.done)]))
    human = runner.invoke(app, ["next"])
    assert human.exit_code == 5
    assert "Всё сделано" in human.stdout
    prompted = runner.invoke(app, ["next", "--prompt"])
    assert prompted.exit_code == 5
    assert prompted.stdout == ""
    assert "Всё сделано" in prompted.stderr


def test_missing_decomposition_exits_2(project):
    _save(project, State())
    result = runner.invoke(app, ["next"])
    assert result.exit_code == 2
    assert "hz decompose" in result.stdout


def test_block_scope_and_held_task(project):
    _save(
        project,
        State(
            blocks=[_block("B1"), _block("B2")],
            tasks=[
                _task("T1", block="B1", status=TStatus.in_progress, blocked_by=["O1"]),
                _task("T2", block="B2", order=2),
            ],
            questions=[_question("O1", "T1")],
        ),
    )
    current = runner.invoke(app, ["next"])
    assert current.exit_code == 0
    assert "T1" in current.stdout
    assert "O1" in current.stdout
    scoped = runner.invoke(app, ["next", "B2"])
    assert scoped.exit_code == 0
    assert "T2" in scoped.stdout


def test_done_transitions(project):
    _save(
        project,
        State(blocks=[_block()], tasks=[_task("T5", status=TStatus.in_progress)]),
    )
    closed = runner.invoke(app, ["next", "--done", "-y"])
    assert closed.exit_code == 0
    state = StateStore(project).load()
    assert state is not None
    assert state.tasks[0].status == TStatus.done
    assert state.tasks[0].done_at is not None
    view = (project / ".hz" / "decomposition.md").read_text(encoding="utf-8")
    assert "[done]" in view

    _save(project, State(blocks=[_block()], tasks=[_task("T5")]))
    rejected = runner.invoke(app, ["next", "T5", "--done", "-y"])
    assert rejected.exit_code == 2
    state = StateStore(project).load()
    assert state is not None
    assert state.tasks[0].status == TStatus.todo


def test_done_confirmation_refusal_does_not_write(project):
    _save(
        project,
        State(blocks=[_block()], tasks=[_task("T5", status=TStatus.in_progress)]),
    )
    result = runner.invoke(app, ["next", "--done"], input="n\n")
    assert result.exit_code == 2
    state = StateStore(project).load()
    assert state is not None
    assert state.tasks[0].status == TStatus.in_progress


def test_review_ack_needs_an_explicit_id(project):
    decision = Decision(
        id="D1",
        kind=DKind.answer,
        text="старое",
        closes=[],
        superseded_by="D2",
    )
    _save(
        project,
        State(
            blocks=[_block(decisions=["D1"])],
            decisions=[decision],
            tasks=[
                _task("T2", status=TStatus.done, needs_review=True),
                _task("T5", order=2, status=TStatus.in_progress),
            ],
        ),
    )
    auto = runner.invoke(app, ["next", "--done", "-y"])
    assert auto.exit_code == 0
    state = StateStore(project).load()
    assert state is not None
    by_id = {task.id: task for task in state.tasks}
    assert by_id["T5"].status == TStatus.done
    assert by_id["T2"].needs_review is True

    acked = runner.invoke(app, ["next", "T2", "--done", "-y"])
    assert acked.exit_code == 0
    state = StateStore(project).load()
    assert state is not None
    reviewed = next(task for task in state.tasks if task.id == "T2")
    assert reviewed.needs_review is False
    assert "D1" in reviewed.acked_decisions


def test_list_shows_dropped_orphans(project):
    _save(
        project,
        State(
            blocks=[
                _block("B1", status=BStatus.dropped),
                _block("B2"),
            ],
            tasks=[
                _task("T1", block="B1", status=TStatus.done, needs_review=True),
                _task("T2", block="B2", order=2),
            ],
        ),
    )
    result = runner.invoke(app, ["next", "--list"])
    assert result.exit_code == 0
    assert "Снятые блоки" in result.stdout
    assert "T1" in result.stdout
    assert "needs review" in result.stdout


def test_stale_spec_needs_yes(project):
    spec = project / "spec.md"
    spec.write_text("новое", encoding="utf-8")
    _save(
        project,
        State(
            spec=Spec(path="spec.md", hash=hash_text("старое"), snapshot="snap"),
            blocks=[_block()],
            tasks=[_task("T1")],
        ),
    )
    blocked = runner.invoke(app, ["next"])
    assert blocked.exit_code == 2
    allowed = runner.invoke(app, ["next", "-y"])
    assert allowed.exit_code == 0
    state = StateStore(project).load()
    assert state is not None
    assert any(entry.cmd == "next -y" for entry in state.log)


def test_question_for_task_blocks_it(project):
    text = "спека"
    (project / "spec.md").write_text(text, encoding="utf-8")
    _save(
        project,
        State(
            spec=Spec(path="spec.md", hash=hash_text(text), snapshot="snap"),
            blocks=[_block()],
            tasks=[_task("T5")],
        ),
    )
    missing = runner.invoke(app, ["audit", "--question", "когда?", "--for", "T9"])
    assert missing.exit_code == 1
    added = runner.invoke(app, ["audit", "--question", "когда?", "--for", "T5"])
    assert added.exit_code == 0
    state = StateStore(project).load()
    assert state is not None
    assert state.questions[0].origin.command == "user"
    assert state.questions[0].origin.task == "T5"
    assert state.tasks[0].blocked_by == [state.questions[0].id]
    queued = runner.invoke(app, ["next"])
    assert queued.exit_code == 4


def test_done_without_review_is_rejected(project):
    _save(project, State(blocks=[_block()], tasks=[_task("T1", status=TStatus.done)]))
    result = runner.invoke(app, ["next", "T1", "--done", "-y"])
    assert result.exit_code == 2
    raw = json.loads((project / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert raw["tasks"][0]["status"] == "done"
    assert raw["log"] == []


def test_needs_review_respects_acked_decisions():
    decision = Decision(id="D1", kind=DKind.answer, text="старое", closes=[], superseded_by="D2")
    state = State(
        blocks=[_block(decisions=["D1"])],
        decisions=[decision],
        tasks=[
            _task("T1", status=TStatus.done, acked_decisions=["D1"], needs_review=True),
            _task("T2", order=2, status=TStatus.done),
            _task("T3", order=3, status=TStatus.in_progress),
        ],
    )
    _flag_needs_review(state)
    by_id = {task.id: task for task in state.tasks}
    assert by_id["T1"].needs_review is False
    assert by_id["T2"].needs_review is True
    assert by_id["T3"].needs_review is False
