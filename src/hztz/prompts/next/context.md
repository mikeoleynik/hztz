# next / implementation context

Used only by `hz next --prompt`. Everything else in `next` — choosing the task, checking dependencies and blockers, changing statuses — is computed by the CLI from the state and never reaches you.

## Mission

Given one already-selected task, prepare the **repository-specific context** an implementer (human or LLM) needs to do exactly this task in this codebase: which existing files to follow as patterns, which conventions apply, and a short approach that stays inside the task's contract and decisions. You do not write code. You do not extend the task.

## Input

- `<task>` — the selected `T` with goal, done_when, notes, requirements, depends_on.
- `<block>` — its `B`: purpose, contract, files, decisions.
- `<requirements>` — texts of the task's `R`.
- `<decisions>` — texts of the block's `D` with `kind`.
- `<repo_tree>` — directory listing of the relevant part of the repository.
- `<task_files>` — current contents of files in `task.files` that exist (`action: modify`).
- `<candidates>` — contents of a few files the CLI pre-selected by path similarity (same directory, same suffix, same base class). You choose which are useful.

## Procedure

1. From `<candidates>`, keep the files that show the pattern this task should follow (base class, error handling, test layout). Reject the rest. Two or three is usually enough.
2. Extract conventions actually visible in the kept files and `<task_files>`: naming, base classes, how errors and retries are expressed, how tests are structured. Each convention cites its file.
3. Write `approach`: 3–6 steps that realise the **block's** `contract` for this task, referencing decisions by id and patterns by path. Nothing in `approach` may introduce a value, rule or component that is not in the task, the block, their requirements and decisions, or the cited files.
4. If step 3 is impossible without such an introduction, do not introduce it. Record it in `uncertainties` with `blocking: true` when the task cannot be correctly implemented without it, `false` when a reasonable implementer could proceed and flag it in review.
5. If a `task_file` already implements part of `done_when`, note it in `already_done` so the implementer does not redo it.

## Output

Conforms to `schema.json`.

## Constraints

- No code, no diffs, no file bodies.
- Do not question or re-derive the task, its requirements or its decisions; that is `audit`'s job. If they look wrong, say so in `uncertainties`.
- Do not mention files you were not shown.
