"""Вход в `hz chat` и `hz -s`."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from typer.testing import CliRunner

from hztz.cli.main import app
from hztz.core.config import HzConfig, write_config
from hztz.core.session import SessionStore
from hztz.core.store import StateStore
from hztz.models.session import AssistantMessage, ChatSession, PatchPart, TextPart, UserMessage
from hztz.models.state import (
    Audience,
    BKind,
    Block,
    Counters,
    Question,
    QuestionOrigin,
    Spec,
    State,
    Summary,
    Task,
    TStatus,
)

runner = CliRunner()


class FakeClient:
    seen: list[list[dict[str, Any]]] = []

    def __init__(self, config: HzConfig) -> None:
        self.config = config

    def complete_text(self, system: str, user: str) -> str:
        del system, user
        return "Заголовок сессии"

    def stream_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[dict[str, str]]:
        del tools
        FakeClient.seen.append(messages)
        yield {"type": "thinking", "text": "думаю"}
        yield {"type": "text", "text": "понял"}

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        del system, user, schema
        return {
            "kind": "explanation",
            "reply": "T6 покрывает R1",
            "references": ["T6"],
            "proposals": [],
        }


@pytest.fixture()
def project(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    write_config(HzConfig())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("hztz.cli.chat.LLMClient", FakeClient)
    FakeClient.seen = []
    spec = tmp_path / "spec.md"
    spec.write_text("Ждать.\n", encoding="utf-8")
    store = StateStore(tmp_path)
    digest, _numbered, snap = store.snapshot(spec)
    store.save(
        State(
            spec=Spec(path="spec.md", hash=digest, snapshot=str(snap)),
            summary=Summary(feynman="Ждать."),
            counters=Counters(O=1, B=1, T=1),
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
                    status=TStatus.in_progress,
                )
            ],
        )
    )
    return tmp_path


def test_chat_without_state_exits_2(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["chat"])
    assert result.exit_code == 2
    assert not (tmp_path / ".hz" / "chat").exists()


def test_positional_id_is_rejected(project):
    result = runner.invoke(app, ["chat", "O4"])
    assert result.exit_code == 2
    assert list((project / ".hz" / "chat").glob("*.json")) == []


def test_unknown_session_exits_2(project):
    result = runner.invoke(app, ["-s", "ses_missing"])
    assert result.exit_code == 2
    assert not (project / ".hz" / "chat" / "ses_missing.json").exists()


def test_empty_exit_has_no_banner(project):
    result = runner.invoke(app, ["chat"], input="")
    assert result.exit_code == 0
    assert "Continue" not in result.output
    assert list((project / ".hz" / "chat").glob("*.json")) == []


def test_exit_banner_survives_quiet(project):
    result = runner.invoke(app, ["chat", "-q"], input="привет\n/exit\n")
    assert result.exit_code == 0, result.output
    assert "Session" in result.output
    assert "Continue  hz -s ses_" in result.output
    assert "Заголовок сессии" in result.output


def test_assume_confirms_and_logs_via(project):
    result = runner.invoke(app, ["chat", "-y"], input="/assume O1 три секунды\n/exit\n")
    assert result.exit_code == 0, result.output
    state = json.loads((project / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert state["questions"][0]["status"] == "assumed"
    assert state["log"][-1]["via"].startswith("chat:ses_")
    assert "hz audit O1 --assume" in result.output


def test_declined_assume_writes_nothing(project):
    result = runner.invoke(app, ["chat"], input="/assume O1 нет\nn\n/exit\n")
    assert result.exit_code == 0, result.output
    state = json.loads((project / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert state["decisions"] == []
    assert "не записано" in result.output


def test_prose_does_not_record_decision(project):
    result = runner.invoke(app, ["chat"], input="таймаут 3 секунды\n/exit\n")
    assert result.exit_code == 0, result.output
    state = json.loads((project / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert state["decisions"] == []
    assert "думаю" in result.output
    assert "понял" in result.output


def test_status_show_next_are_read_only(project):
    before = (project / ".hz" / "state.json").read_text(encoding="utf-8")
    result = runner.invoke(app, ["chat"], input="/status\n/show O1\n/next\n/exit\n")
    assert result.exit_code == 0, result.output
    assert "Открытых вопросов" in result.output
    assert "сколько ждать?" in result.output
    assert "T1" in result.output
    assert (project / ".hz" / "state.json").read_text(encoding="utf-8") == before


def test_persona_does_not_touch_graph(project):
    result = runner.invoke(app, ["chat"], input="/persona feynman\n/exit\n")
    assert result.exit_code == 0, result.output
    state = json.loads((project / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert state["decisions"] == []
    saved = next(iter((project / ".hz" / "chat").glob("*.json")))
    session = json.loads(saved.read_text(encoding="utf-8"))
    assert session["persona"] == "feynman"


def test_done_uses_core(project):
    result = runner.invoke(app, ["chat", "-y"], input="/done T1\n/exit\n")
    assert result.exit_code == 0, result.output
    state = json.loads((project / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert state["tasks"][0]["status"] == "done"
    assert state["log"][-1]["via"].startswith("chat:")


def test_resume_prints_transcript_and_keeps_persona(project):
    state = StateStore(project).load()
    assert state is not None and state.spec is not None
    SessionStore(project).save(
        ChatSession(
            id="ses_keep",
            title="Старый",
            persona="feynman",
            spec_hash=state.spec.hash,
            log_cursor=len(state.log),
            messages=[
                UserMessage(text="старый вопрос"),
                AssistantMessage(
                    parts=[
                        TextPart(text="старый ответ"),
                        PatchPart(path="note.txt", added=1, removed=0, hunk="ONLY-IN-HUNK"),
                    ]
                ),
            ],
        )
    )
    result = runner.invoke(app, ["-s", "ses_keep"], input="ещё\n/exit\n")
    assert result.exit_code == 0, result.output
    assert "старый ответ" in result.output
    assert "ONLY-IN-HUNK" in result.output
    assert "Continue  hz -s ses_keep" in result.output
    system = str(FakeClient.seen[0][0]["content"])
    assert "Check understanding" in system
    blob = str(FakeClient.seen[0][1]["content"])
    assert "ONLY-IN-HUNK" not in blob
    assert "note.txt" in blob


def test_resume_persona_override(project):
    state = StateStore(project).load()
    assert state is not None and state.spec is not None
    SessionStore(project).save(
        ChatSession(
            id="ses_over",
            title="Старый",
            persona="feynman",
            spec_hash=state.spec.hash,
            messages=[UserMessage(text="было")],
        )
    )
    result = runner.invoke(app, ["-s", "ses_over", "--persona", "columbo"], input="ещё\n/exit\n")
    assert result.exit_code == 0, result.output
    system = str(FakeClient.seen[0][0]["content"])
    assert "discover the gaps" in system


def test_oneshot_prints_reply_without_session(project):
    note = project / "note.txt"
    note.write_text("stay\n", encoding="utf-8")
    result = runner.invoke(app, ["chat", "-m", "какие требования покрывает T6?"])
    assert result.exit_code == 0, result.output
    assert "T6 покрывает R1" in result.output
    assert list((project / ".hz" / "chat").glob("*.json")) == []
    assert note.read_text(encoding="utf-8") == "stay\n"

    result = runner.invoke(app, ["chat", "-m", "что открыто?", "--json"])
    assert result.exit_code == 0, result.output
    assert '"kind"' in result.output
    assert '"reply"' in result.output
