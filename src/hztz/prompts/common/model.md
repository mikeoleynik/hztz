# hz — data model (shared by all stages)

The project state is a JSON document owned by the CLI. You read parts of it and return new or updated objects; the CLI validates, assigns ids, and persists. **You are never the source of truth.**

## Entities

```text
R → A → O → D → B → T → T
```

| Prefix | Entity | Created by stage | What it is |
| --- | --- | --- | --- |
| `R` | Requirement | audit/extract | One atomic assertion from the specification, in the author's words, with section and line range |
| `A` | Finding | audit/findings, decompose | A fact: this requirement cannot be implemented without guessing. Always with evidence |
| `O` | Question | audit/questions, decompose, user | What a human must decide. Refers to ≥1 finding. Has an addressee and optional grounded options |
| `D` | Decision | **human only** (CLI `--answer`, `--assume`) | Immutable answer or assumption that closes questions |
| `B` | Block | decompose | A component of the system: purpose, requirements, decisions, contract, files. No progress status of its own |
| `T` | Task | decompose | One step of implementing a block: goal, requirement slice, depends_on, blocked_by, done-when, status |

## Ids and keys

- Existing objects are referenced by their real id (`R12`, `A3`, `O2`, `D4`, `B2`, `T5`). Never invent ids in these formats.
- New objects you create get a local `key` (`"f1"`, `"q2"`, `"b2"`, `"t3"`) used only for cross-references inside your response. The CLI replaces keys with real ids.
- When updating, `matches` names the existing object your new object is the same as. `null` means new.

## Enums

**`R.kind`** — `functional | nfr | constraint | data | interface | goal`

**`A.kind`** — the ISO/IEC/IEEE 29148 characteristic that is violated:

| kind | Use when | Common vocabulary it covers |
| --- | --- | --- |
| `ambiguous` | Text admits more than one reading; a term is undefined; "fast", "as needed", "or" | ambiguity, undefined term, hidden assumption in wording |
| `incomplete` | Something needed to implement is not there; refine with `missing` | missing requirement, undefined behavior, missing edge case, missing error handling, missing acceptance criteria, missing NFR, missing constraint |
| `inconsistent` | Two places (R↔R, or R↔D) define the same thing differently | contradiction, inconsistency |
| `infeasible` | A requirement conflicts with a stated constraint; always *potential* | infeasibility |
| `unverifiable` | No test or check could confirm it | untestable, no acceptance criterion possible |

**`A.missing`** (only with `incomplete`) — `requirement | behavior | error_handling | edge_case | nfr | acceptance_criteria | constraint | definition`

**`A.severity`** — impact on implementation, not importance of topic:

| severity | Meaning |
| --- | --- |
| `blocker` | The requirement cannot be implemented correctly without a decision |
| `high` | Work can start, but the decision may force substantial rework |
| `medium` | Does not affect the happy path; affects part of the behaviour |
| `low` | Clarification with no architectural or main-flow impact; may be assumed |

**`A.confidence`** — `high | medium | low` — how sure you are the finding is real. Independent of severity.

**`O.audience`** — `business` (behaviour, money, users, legal → analyst/customer) · `technical` (contour, libraries, retries, internal formats → developer may close by assumption)

**`basis.type`** — `spec | repo | convention`

**`D.kind`** — `answer` (a human answered) · `assumption` (developer decided without the author; carried into tasks as `ASSUMPTION`)

**`B.kind`** — `data | service | job | api | ui | integration | infra`

**`T.status`** — `todo | in_progress | done | dropped`. "Blocked" is computed by the CLI from `blocked_by`, never a status you set. A task belongs to exactly one block.

**NFR categories** (for `missing: nfr`, in `detail`) — ISO 25010: `performance, reliability, availability, security, maintainability, usability, compatibility, portability, observability, compliance`.

## Evidence

```json
{ "line_start": 142, "line_end": 151, "quote": "verbatim text from the specification" }
{ "decision": "D3" }
{ "file": "app/jobs/job_base.rb", "line_start": 12, "line_end": 14, "quote": "retry: 3" }
```

Line numbers refer to the numbered specification text in your input. Quotes are verbatim, trimmed, not paraphrased.

## Output envelope

Every stage response has:

```json
{ "blocked": null, ...payload }
{ "blocked": { "reason": "…", "refs": ["O3"] } }
```

`blocked` non-null means the stage could not run; payload fields may be omitted. A task that cannot be implemented is *not* a blocked stage — it is a task with `blocked_by`.
