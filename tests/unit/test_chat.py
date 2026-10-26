"""Сессия, границы файлов, дельта, промпт REPL."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hztz.core.chat import compose_chat_system, drift_line, run_repl
from hztz.core.files import FileDenied, apply_edit, check_write
from hztz.core.session import SessionStore, fallback_title
from hztz.core.store import StateStore
from hztz.models.session import (
    AssistantMessage,
    ChatSession,
    TextPart,
    ThinkingPart,
    UserMessage,
)
from hztz.models.state import (
    Audience,
    BKind,
    Block,
    Counters,
    LogEntry,
    Question,
    QuestionOrigin,
    Spec,
    State,
    Summary,
    Task,
    TStatus,
    now_utc,
)


class Scripted:
    def __init__(self, rounds: list[list[dict[str, str]]], title: str | None = "Заголовок") -> None:
        self.rounds = list(rounds)
        self.title = title
        self.seen: list[list[dict[str, Any]]] = []
        self.json_calls = 0

    def stream_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[dict[str, str]]:
        del tools
        self.seen.append(messages)
        events = self.rounds.pop(0) if self.rounds else [{"type": "text", "text": "ок"}]
        yield from events

    def complete_text(self, system: str, user: str) -> str:
        del system, user
        if self.title is None:
            raise RuntimeError("title failed")
        return self.title

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        del system, user, schema
        self.json_calls += 1
        return {}


def _project(tmp_path: Path) -> State:
    spec = tmp_path / "spec.md"
    spec.write_text("Ждать три секунды.\n", encoding="utf-8")
    store = StateStore(tmp_path)
    digest, _numbered, snap = store.snapshot(spec)
    state = State(
        spec=Spec(path="spec.md", hash=digest, snapshot=str(snap)),
        summary=Summary(feynman="Ждать."),
        counters=Counters(O=1, T=1, B=1),
        questions=[
            Question(
                id="O1",
                text="сколько ждать?",
                why="",
                audience=Audience.technical,
                findings=[],
                origin=QuestionOrigin(command="user"),
            )
        ],
        blocks=[
            Block(
                id="B1",
                kind=BKind.service,
                title="B1",
                purpose="p",
                requirements=["R1"],
                contract="c",
            )
        ],
        tasks=[
            Task(
                id="T1",
                block="B1",
                order=1,
                title="T1",
                goal="g",
                requirements=["R1"],
                done_when=["готово"],
            )
        ],
    )
    store.save(state)
    return state


def _run(
    tmp_path: Path,
    client: Scripted,
    lines: list[str],
    *,
    existing: ChatSession | None = None,
    persona: str = "columbo",
    yes: bool = False,
) -> tuple[list[str], ChatSession | None]:
    echoed: list[str] = []
    pending = list(lines)

    def read() -> str | None:
        if not pending:
            return None
        return pending.pop(0)

    code, session = run_repl(
        root=tmp_path,
        state_store=StateStore(tmp_path),
        sessions=SessionStore(tmp_path),
        client=client,
        persona=persona,
        yes=yes,
        read=read,
        echo=echoed.append,
        emit=lambda _kind, text: echoed.append(text),
        confirm=lambda _prompt: True,
        existing=existing,
    )
    assert code == 0
    return echoed, session


def test_fallback_title_truncates() -> None:
    assert fallback_title("а" * 90) == "а" * 80


def test_prompt_forbids_settling_open_question() -> None:
    system = compose_chat_system("columbo", repl=True)
    assert "resolves an open question" in system
    assert "slash command" in system


def test_session_roundtrip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = ChatSession(
        id="ses_abc",
        title="Выбор стека",
        persona="feynman",
        spec_hash="sha256:abcd",
        log_cursor=2,
        messages=[
            UserMessage(text="привет"),
            AssistantMessage(
                parts=[ThinkingPart(text="думаю"), TextPart(text="ответ")],
            ),
        ],
    )
    store.save(session)
    loaded = store.load("ses_abc")
    assert loaded is not None
    assert loaded.title == "Выбор стека"
    assert loaded.messages[1].parts[0].type == "thinking"  # type: ignore[union-attr]


def test_empty_lines_leave_no_file(tmp_path: Path) -> None:
    _project(tmp_path)
    _run(tmp_path, Scripted([]), [])
    assert list((tmp_path / ".hz" / "chat").glob("*.json")) == []


def test_title_fallback_when_model_fails(tmp_path: Path) -> None:
    _project(tmp_path)
    long = "б" * 90
    _echo, session = _run(
        tmp_path,
        Scripted([[{"type": "text", "text": "ок"}]], title=None),
        [long],
    )
    assert session is not None
    assert session.title == "б" * 80


def test_thinking_is_stored_and_not_replayed(tmp_path: Path) -> None:
    _project(tmp_path)
    client = Scripted(
        [
            [
                {"type": "thinking", "text": "SECRET-REASONING"},
                {"type": "text", "text": "ответ"},
            ],
            [{"type": "text", "text": "дальше"}],
        ]
    )
    _echo, session = _run(tmp_path, client, ["первый", "второй"])
    assert session is not None
    parts = session.messages[1].parts  # type: ignore[union-attr]
    assert any(part.type == "thinking" and "SECRET-REASONING" in part.text for part in parts)
    blob = str(client.seen[1][1]["content"])
    assert "SECRET-REASONING" not in blob
    assert "ответ" in blob
    assert client.json_calls == 0


def test_edit_shows_diff_and_leaves_task(tmp_path: Path) -> None:
    _project(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("old\n", encoding="utf-8")
    client = Scripted(
        [
            [
                {
                    "type": "tool_call",
                    "id": "c1",
                    "name": "edit_file",
                    "arguments": json.dumps({"path": "note.txt", "old": "old\n", "new": "new\n"}),
                    "text": "",
                }
            ],
            [{"type": "text", "text": "готово"}],
        ]
    )
    echoed, session = _run(tmp_path, client, ["правь"])
    assert note.read_text(encoding="utf-8") == "new\n"
    assert any("+1" in line or "+1 -1" in line or "note.txt" in line for line in echoed)
    assert session is not None
    patch = next(
        part
        for message in session.messages
        if isinstance(message, AssistantMessage)
        for part in message.parts
        if part.type == "patch"
    )
    assert patch.hunk  # type: ignore[union-attr]
    saved = StateStore(tmp_path).load()
    assert saved is not None
    assert saved.tasks[0].status == TStatus.todo


def test_rejected_edit_keeps_going(tmp_path: Path) -> None:
    _project(tmp_path)
    spec = (tmp_path / "spec.md").read_text(encoding="utf-8")
    client = Scripted(
        [
            [
                {
                    "type": "tool_call",
                    "id": "c1",
                    "name": "edit_file",
                    "arguments": json.dumps({"path": "spec.md", "old": "Ждать", "new": "Молчать"}),
                    "text": "",
                }
            ],
            [{"type": "text", "text": "не смог"}],
        ]
    )
    _echo, session = _run(tmp_path, client, ["правь тз"])
    assert (tmp_path / "spec.md").read_text(encoding="utf-8") == spec
    assert session is not None
    assert any(
        isinstance(message, AssistantMessage)
        and any(part.type == "text" and "не смог" in part.text for part in message.parts)
        for message in session.messages
    )


def test_write_boundaries(tmp_path: Path) -> None:
    state = _project(tmp_path)
    with pytest.raises(FileDenied):
        check_write(tmp_path, state, ".hz/state.json")
    with pytest.raises(FileDenied):
        check_write(tmp_path, state, "secret.env")
    with pytest.raises(FileDenied):
        check_write(tmp_path, state, "/etc/passwd")
    allowed = check_write(tmp_path, state, ".env.example")
    assert allowed.name == ".env.example"
    outside = tmp_path.parent / "outside.txt"
    with pytest.raises(FileDenied):
        apply_edit(tmp_path, state, str(outside), "", "x")
    assert not outside.exists()


def test_drift_skips_own_via(tmp_path: Path) -> None:
    state = _project(tmp_path)
    session = ChatSession(id="ses_me", persona="columbo", spec_hash=state.spec.hash, log_cursor=0)  # type: ignore[union-attr]
    state.log.append(
        LogEntry(
            at=now_utc(),
            cmd="audit O2 --answer",
            via="cli",
            created=["D4"],
            changed=[{"id": "O2", "status": "open → answered"}],
        )
    )
    state.log.append(
        LogEntry(
            at=now_utc(),
            cmd="audit O4 --assume",
            via="chat:ses_me",
            created=["D8"],
            changed=[{"id": "O4", "status": "open → assumed"}],
        )
    )
    line = drift_line(state, session)
    assert line is not None
    assert "O2" in line and "D4" in line
    assert "D8" not in line and "O4" not in line
