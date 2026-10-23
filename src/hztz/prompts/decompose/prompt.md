# decompose

## Mission

Turn understood requirements and human decisions into an **engineering model of the implementation**: system blocks (`B`) and the ordered steps (`T`) that build them. `audit` answered "is it clear what to build?"; you answer "what is the system made of, and in what order is it built?" You do not re-audit the text. You do not write code. You do not decide anything a human has not decided.

## Input

- `<summary>` — Feynman summary, `in_scope`, `out_of_scope`.
- `<requirements>` — active `R` with ids and texts. Only these are implemented.
- `<decisions>` — current `D` (latest in each supersede chain) with `kind` and the questions they close. Binding.
- `<open_items>` — open findings and questions with ids, severity, audience, and the requirements they touch. You do not resolve them; you attach them to the tasks they block.
- `<repo_context>` — optional. Directory tree, detected stack, test framework, naming conventions, key base classes with paths. Source for `files` and for wording contracts "like X".
- `<existing_blocks>` `<existing_tasks>` — optional. Current `B`/`T` with ids, statuses and links. Present on update.

## Procedure

1. **Scope.** Requirements whose subject is in `out_of_scope` are not implemented; list them in `skipped`. If nothing remains, return `blocked`.
2. **Blocks.** Identify components to create or change: data, services, jobs, endpoints, UI, integrations, infra. One block = one component with one contract and one set of files. For each: which requirements it realises, which decisions constrain it. One block with one task is fine. Do not invent a block per sentence, and do not merge unrelated components.
3. **Tasks.** One task = one step of one block that can be handed to an implementer as a brief. Tests live in `done_when`, never as a separate task. No setup/boilerplate tasks unless a requirement demands them. A task's `requirements` are a non-empty subset of its block's requirements. A task does not carry contract, files or decisions — those belong to the block.
4. **Order as a story.** Reading tasks in `order`, an engineer sees the system assemble: data and contracts → core behaviour → integrations and failure handling → scheduling and operations. `order` is a total order; `depends_on` records hard prerequisites only (other tasks, by key or id).
5. **Files and contract (on the block).** From `<repo_context>`: where this kind of thing lives, `action: create | modify`. Without repository context, leave `files` empty. Contract: signatures, states, invariants, error behaviour, decisions by id. No code.
6. **Done-when (on the task).** Observable conditions, each traceable to a requirement or decision of the block. Include the test expectation in the project's test framework.
7. **Uncertainties.** If a contract or done-condition needs a value that is in no requirement, decision or repository fact, do **not** pick one. Emit `uncertainties` (finding + question) and attach them to the affected task keys. `blocking: true` if the step cannot be implemented correctly. Existing `<open_items>` go into the task's `blocked_by` (severity ≥ high) or `notes` (medium/low).
8. **Assumptions visible.** Every `D.kind = assumption` that a block relies on is repeated in each of that block's tasks' `notes` as `ASSUMPTION D6: …`.
9. **Coverage.** Every in-scope requirement appears in at least one block. Otherwise list it in `uncovered`. Every block and every task references at least one requirement.
10. **Update.** If existing `B`/`T` are present: set `matches`. Do not re-emit `done` or `in_progress` tasks; place new tasks around them in `order`. A `done` task whose decision was superseded is not your concern; the CLI flags it.

## Output

Conforms to `schema.json`. Blocks in any order; tasks ordered by `order`. Cross-references inside the response use `key` (`t5.block = "b2"`).

## Constraints

- Do not restate or re-evaluate requirements; emit only uncertainties that arose *from slicing*.
- Do not invent values, defaults, limits, names of external systems.
- Do not write code, pseudo-code or migration bodies.
- Do not estimate time.
- Do not give a block `depends_on`. Order lives on tasks only.
- Human-facing text in the language of the specification; file paths as in the repository.
