"""Pydantic-модели состояния `hz` — source of truth (.hz/state.json).

Схема описана в `_private/cli/state.md`. Хранятся только факты; вычисляемое
(`O.severity`, `O.decision`, `A.questions`) считается на чтении, не хранится.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def now_utc() -> datetime:
    return datetime.now(UTC)


class HZModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True)


# --- enums ---------------------------------------------------------------


class RKind(StrEnum):
    functional = "functional"
    nfr = "nfr"
    constraint = "constraint"
    data = "data"
    interface = "interface"
    goal = "goal"


class RStatus(StrEnum):
    active = "active"
    removed = "removed"


class AKind(StrEnum):
    ambiguous = "ambiguous"
    incomplete = "incomplete"
    inconsistent = "inconsistent"
    infeasible = "infeasible"
    unverifiable = "unverifiable"


class Missing(StrEnum):
    requirement = "requirement"
    behavior = "behavior"
    error_handling = "error_handling"
    edge_case = "edge_case"
    nfr = "nfr"
    acceptance_criteria = "acceptance_criteria"
    constraint = "constraint"
    definition = "definition"


class Severity(StrEnum):
    blocker = "blocker"
    high = "high"
    medium = "medium"
    low = "low"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class AStatus(StrEnum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


class Audience(StrEnum):
    business = "business"
    technical = "technical"


class BasisType(StrEnum):
    spec = "spec"
    repo = "repo"
    convention = "convention"


class OStatus(StrEnum):
    open = "open"
    answered = "answered"
    assumed = "assumed"
    dismissed = "dismissed"


class DKind(StrEnum):
    answer = "answer"
    assumption = "assumption"


# --- requirement ----------------------------------------------------------


class Location(HZModel):
    line_start: int
    line_end: int


class Requirement(HZModel):
    id: str
    text: str
    section: str
    location: Location
    kind: RKind
    status: RStatus = RStatus.active


# --- finding --------------------------------------------------------------


class Evidence(HZModel):
    # oneOf-варианты (валидация варианта — на границе LLM, по JSON Schema)
    line_start: int | None = None
    line_end: int | None = None
    quote: str | None = None
    decision: str | None = None
    file: str | None = None


class Resolution(HZModel):
    by: str
    reason: str | None = None  # для spec_changed


class FindingOrigin(HZModel):
    command: str
    version: str | None = None
    block: str | None = None


class Finding(HZModel):
    id: str
    kind: AKind
    missing: Missing | None = None
    severity: Severity
    confidence: Confidence
    title: str
    detail: str
    what_to_specify: str
    requirements: list[str]
    evidence: list[Evidence]
    status: AStatus = AStatus.open
    resolution: Resolution | None = None
    origin: FindingOrigin
    created_at: datetime = Field(default_factory=now_utc)


# --- question -------------------------------------------------------------


class Basis(HZModel):
    type: BasisType
    ref: str
    quote: str | None = None


class Option(HZModel):
    label: str
    text: str
    consequence: str
    basis: Basis | None = None


class QuestionOrigin(HZModel):
    command: str
    task: str | None = None


class Question(HZModel):
    id: str
    text: str
    why: str
    audience: Audience
    findings: list[str]
    options: list[Option] = Field(default_factory=list)
    status: OStatus = OStatus.open
    origin: QuestionOrigin
    created_at: datetime = Field(default_factory=now_utc)


# --- decision --------------------------------------------------------------


class Decision(HZModel):
    id: str
    kind: DKind
    text: str
    closes: list[str]
    option: str | None = None
    by: str | None = None
    at: datetime = Field(default_factory=now_utc)
    supersedes: str | None = None
    superseded_by: str | None = None


# --- top-level state -------------------------------------------------------


class SpecVersion(HZModel):
    hash: str
    path: str
    audited_at: datetime


class Spec(HZModel):
    path: str
    hash: str
    snapshot: str
    versions: list[SpecVersion] = Field(default_factory=list)


class Scores(HZModel):
    clarity: float = 0.0
    completeness: float = 0.0
    consistency: float = 0.0
    testability: float = 0.0


class Summary(HZModel):
    feynman: str
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    scores: Scores = Field(default_factory=Scores)


class Counters(HZModel):
    R: int = 0
    A: int = 0
    O: int = 0  # noqa: E741
    D: int = 0
    B: int = 0
    T: int = 0


class LogEntry(HZModel):
    at: datetime
    cmd: str
    via: str = "cli"
    created: list[str] = Field(default_factory=list)
    changed: list[dict[str, Any]] = Field(default_factory=list)


class Coverage(HZModel):
    uncovered: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class State(HZModel):
    version: int = 1
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    spec: Spec | None = None
    repo: str = "."
    summary: Summary | None = None
    counters: Counters = Field(default_factory=Counters)
    requirements: list[Requirement] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    log: list[LogEntry] = Field(default_factory=list)
