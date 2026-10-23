import json

import pytest
from typer.testing import CliRunner

from hztz.cli.main import app

runner = CliRunner()


class FakeStageRunner:
    def __init__(self) -> None:
        pass

    def run(self, stage_prompt: str, schema_rel: str, blocks: list[str]) -> dict:
        if "extract.json" in schema_rel:
            return {
                "blocked": None,
                "requirements": [
                    {
                        "text": "Делать быстро",
                        "kind": "functional",
                        "section": "1",
                        "line_start": 1,
                        "line_end": 1,
                        "matches": None,
                    }
                ],
                "summary": {"feynman": "Делать быстро", "in_scope": [], "out_of_scope": []},
            }
        if "findings.json" in schema_rel:
            return {
                "blocked": None,
                "findings": [
                    {
                        "key": "f1",
                        "matches": None,
                        "kind": "ambiguous",
                        "missing": None,
                        "severity": "blocker",
                        "confidence": "high",
                        "title": "«быстро» без меры",
                        "detail": "нет численной меры",
                        "requirements": ["R1"],
                        "evidence": [{"line_start": 1, "line_end": 1, "quote": "Делать быстро"}],
                        "what_to_specify": "Указать меру «быстро»",
                    }
                ],
            }
        if "questions.json" in schema_rel:
            return {
                "blocked": None,
                "questions": [
                    {
                        "key": "q1",
                        "matches": None,
                        "text": "Что значит «быстро»?",
                        "why": "нет меры",
                        "audience": "technical",
                        "findings": ["A1"],
                        "options": [],
                    }
                ],
            }
        raise ValueError(schema_rel)


@pytest.fixture()
def fake_audit(monkeypatch, tmp_path):
    import hztz.cli.audit as audit_cli

    monkeypatch.setattr(audit_cli, "StageRunner", FakeStageRunner)
    monkeypatch.setattr(audit_cli, "load_config_or_exit", lambda: None)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "spec.md").write_text("Делать быстро и красиво.", encoding="utf-8")
    return tmp_path


def test_first_audit(fake_audit):
    result = runner.invoke(app, ["audit", "spec.md"])
    assert result.exit_code == 0, result.output

    state = json.loads((fake_audit / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in state["requirements"]] == ["R1"]
    assert [f["id"] for f in state["findings"]] == ["A1"]
    assert [q["id"] for q in state["questions"]] == ["O1"]
    assert (fake_audit / ".hz" / "audit.md").exists()
    assert list((fake_audit / ".hz" / "spec").glob("*.md"))


def test_answer_closes_question(fake_audit):
    runner.invoke(app, ["audit", "spec.md"])
    result = runner.invoke(app, ["audit", "O1", "--answer", "100ms"])
    assert result.exit_code == 0, result.output

    state = json.loads((fake_audit / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert [d["id"] for d in state["decisions"]] == ["D1"]
    assert state["questions"][0]["status"] == "answered"
    assert state["findings"][0]["status"] == "resolved"


def test_check_exits_3_when_blockers(fake_audit):
    runner.invoke(app, ["audit", "spec.md"])
    result = runner.invoke(app, ["audit", "--check"])
    assert result.exit_code == 3
