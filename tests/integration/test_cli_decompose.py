import copy
import json

import pytest
from typer.testing import CliRunner

from hztz.cli.main import app
from hztz.core.store import hash_text

runner = CliRunner()

DECOMPOSE_RESP = {
    "blocked": None,
    "blocks": [
        {
            "key": "b1",
            "matches": None,
            "kind": "service",
            "title": "Operator",
            "purpose": "p",
            "requirements": ["R1"],
            "decisions": [],
            "contract": "c",
            "files": [],
        }
    ],
    "tasks": [
        {
            "key": "t1",
            "matches": None,
            "block": "b1",
            "order": 1,
            "title": "DTO",
            "goal": "g",
            "requirements": ["R1"],
            "depends_on": [],
            "blocked_by": [],
            "done_when": ["d"],
            "notes": [],
        },
        {
            "key": "t2",
            "matches": None,
            "block": "b1",
            "order": 2,
            "title": "Client",
            "goal": "g",
            "requirements": ["R1"],
            "depends_on": ["t1"],
            "blocked_by": [],
            "done_when": ["d"],
            "notes": [],
        },
    ],
    "uncertainties": [
        {
            "finding": {
                "key": "f1",
                "matches": None,
                "kind": "incomplete",
                "missing": "behavior",
                "severity": "high",
                "confidence": "high",
                "title": "таймаут",
                "detail": "d",
                "requirements": ["R1"],
                "evidence": [],
                "what_to_specify": "w",
            },
            "question": {
                "key": "q1",
                "matches": None,
                "text": "что при таймауте?",
                "why": "w",
                "audience": "technical",
                "findings": ["f1"],
                "options": [],
            },
            "affects": ["t2"],
            "blocking": True,
        }
    ],
    "uncovered": [],
    "skipped": [],
}


class FakeStageRunner:
    payload = DECOMPOSE_RESP
    last_blocks: list[str] | None = None

    def __init__(self) -> None:
        pass

    def run(self, stage_prompt: str, schema_rel: str, blocks: list[str]) -> dict:
        assert "decompose" in schema_rel
        FakeStageRunner.last_blocks = blocks
        return copy.deepcopy(FakeStageRunner.payload)


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    import hztz.cli.decompose as decompose_cli

    FakeStageRunner.payload = DECOMPOSE_RESP
    FakeStageRunner.last_blocks = None
    monkeypatch.setattr(decompose_cli, "StageRunner", FakeStageRunner)
    monkeypatch.setattr(decompose_cli, "load_config_or_exit", lambda: None)
    monkeypatch.chdir(tmp_path)

    spec_content = "Делать быстро."
    (tmp_path / "spec.md").write_text(spec_content, encoding="utf-8")

    from hztz.core.store import StateStore
    from hztz.models.state import (
        Location,
        Requirement,
        RKind,
        Spec,
        State,
        Summary,
    )

    store = StateStore(tmp_path)
    h = hash_text(spec_content)
    state = State(
        spec=Spec(path="spec.md", hash=h, snapshot=f".hz/spec/{h.split(':')[1]}.md"),
        summary=Summary(feynman="Делать", in_scope=[], out_of_scope=[]),
    )
    state.counters.R = 1
    state.requirements = [
        Requirement(
            id="R1",
            text="Делать быстро",
            section="1",
            location=Location(line_start=1, line_end=1),
            kind=RKind.functional,
        )
    ]
    store.save(state)
    return tmp_path


def test_primary_decomposition(seeded):
    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 0, result.output

    state = json.loads((seeded / ".hz" / "state.json").read_text(encoding="utf-8"))
    assert [b["id"] for b in state["blocks"]] == ["B1"]
    assert [t["id"] for t in state["tasks"]] == ["T1", "T2"]

    t2 = next(t for t in state["tasks"] if t["id"] == "T2")
    assert t2["depends_on"] == ["T1"]
    assert t2["blocked_by"] == ["O1"]

    assert [f["id"] for f in state["findings"]] == ["A1"]
    assert state["findings"][0]["origin"]["command"] == "decompose"
    assert [q["id"] for q in state["questions"]] == ["O1"]
    assert state["questions"][0]["findings"] == ["A1"]
    assert state["findings"][0]["origin"]["block"] == "B1"

    md = (seeded / ".hz" / "decomposition.md").read_text(encoding="utf-8")
    assert "```mermaid" in md
    assert "subgraph B1" in md
    assert "O1" in md


def test_update_keeps_done(seeded):
    runner.invoke(app, ["decompose"])

    # mark T1 done via direct state edit
    spath = seeded / ".hz" / "state.json"
    state = json.loads(spath.read_text(encoding="utf-8"))
    for t in state["tasks"]:
        if t["id"] == "T1":
            t["status"] = "done"
    spath.write_text(json.dumps(state), encoding="utf-8")

    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 0, result.output

    state = json.loads(spath.read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in state["tasks"]}
    assert by_id["T1"]["status"] == "done"
    assert by_id["T2"]["status"] == "todo"
    assert by_id["T2"]["title"] == "Client"
    assert [b["id"] for b in state["blocks"] if b["status"] == "active"] == ["B1"]
    assert "kept" in result.output
    assert "updated" in result.output


def _load(path):
    return json.loads((path / ".hz" / "state.json").read_text(encoding="utf-8"))


def test_unresolvable_key_does_not_save(seeded):
    bad = copy.deepcopy(DECOMPOSE_RESP)
    bad["tasks"][1]["depends_on"] = ["missing"]
    FakeStageRunner.payload = bad

    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 1, result.output
    assert _load(seeded)["blocks"] == []


def test_cycle_exits_1(seeded):
    bad = copy.deepcopy(DECOMPOSE_RESP)
    bad["tasks"][0]["depends_on"] = ["t2"]
    FakeStageRunner.payload = bad

    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 1, result.output
    assert _load(seeded)["tasks"] == []


def test_requirements_subset(seeded):
    bad = copy.deepcopy(DECOMPOSE_RESP)
    bad["tasks"][0]["requirements"] = ["R9"]
    FakeStageRunner.payload = bad

    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 1, result.output
    assert _load(seeded)["blocks"] == []


def test_matches_on_done_exits_1(seeded):
    runner.invoke(app, ["decompose"])
    spath = seeded / ".hz" / "state.json"
    state = json.loads(spath.read_text(encoding="utf-8"))
    for task in state["tasks"]:
        if task["id"] == "T1":
            task["status"] = "done"
    spath.write_text(json.dumps(state), encoding="utf-8")

    bad = copy.deepcopy(DECOMPOSE_RESP)
    bad["tasks"][0]["matches"] = "T1"
    FakeStageRunner.payload = bad

    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 1, result.output
    again = json.loads(spath.read_text(encoding="utf-8"))
    assert [t["id"] for t in again["tasks"]] == ["T1", "T2"]
    assert next(t for t in again["tasks"] if t["id"] == "T1")["status"] == "done"


def test_nonblocking_goes_to_notes(seeded):
    payload = copy.deepcopy(DECOMPOSE_RESP)
    payload["uncertainties"][0]["blocking"] = False
    FakeStageRunner.payload = payload

    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 0, result.output
    t2 = next(t for t in _load(seeded)["tasks"] if t["id"] == "T2")
    assert t2["blocked_by"] == []
    assert any("O1" in note for note in t2["notes"])


def test_repo_flag_and_stack(seeded):
    (seeded / "package.json").write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["decompose", "--repo", "."])
    assert result.exit_code == 0, result.output
    assert _load(seeded)["repo"] == "."
    assert FakeStageRunner.last_blocks is not None
    assert any("node" in block for block in FakeStageRunner.last_blocks)


def test_greenfield_omits_repo_context(seeded):
    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 0, result.output
    assert FakeStageRunner.last_blocks is not None
    assert all("<repo_context>" not in block for block in FakeStageRunner.last_blocks)


def test_stale_spec_exits_2(seeded):
    (seeded / "spec.md").write_text("Другой текст.", encoding="utf-8")
    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 2, result.output
    assert _load(seeded)["blocks"] == []


def test_missing_state_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 2, result.output


def test_needs_review_on_superseded_decision(seeded):
    from hztz.core.store import StateStore
    from hztz.models.state import Decision, DKind

    runner.invoke(app, ["decompose"])
    store = StateStore(seeded)
    state = store.load()
    assert state is not None
    state.decisions = [
        Decision(id="D1", kind=DKind.answer, text="было", closes=["O1"], superseded_by="D2"),
        Decision(id="D2", kind=DKind.answer, text="стало", closes=["O1"], supersedes="D1"),
    ]
    state.blocks[0].decisions = ["D1"]
    for task in state.tasks:
        if task.id == "T1":
            task.status = "done"
    store.save(state)

    payload = copy.deepcopy(DECOMPOSE_RESP)
    payload["blocks"][0]["decisions"] = ["D1"]
    payload["blocks"][0]["matches"] = "B1"
    payload["tasks"][1]["matches"] = "T2"
    FakeStageRunner.payload = payload

    result = runner.invoke(app, ["decompose"])
    assert result.exit_code == 0, result.output
    again = _load(seeded)
    done = next(t for t in again["tasks"] if t["id"] == "T1")
    assert done["status"] == "done"
    assert done["needs_review"] is True
    assert "review" in result.output
