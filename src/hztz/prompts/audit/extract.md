# audit / stage 1 — extract

## Mission

Turn the specification into a list of atomic requirements (`R`) and a plain-language summary. Do **not** evaluate quality here: no findings, no questions. Extraction must be exhaustive and faithful; judgement comes in the next stage.

## Input

- `<spec>` — the specification with line numbers.
- `<previous_requirements>` — optional; the `R` list from the last audited version. Present only on re-audit.

## Procedure

1. Read the whole text. Identify sections (use the author's headings; if none, infer boundaries and name them by position).
2. Split into **atomic assertions**: one requirement = one thing that could be true or false about the system. Split compound sentences ("A and B", "A, unless B"); do not merge for tidiness. Keep the author's wording; trim only connective words.
3. Classify each with `kind`. Goals, motivations and context are `goal`; they are still recorded because findings may refer to them.
4. Record `section` and the line range the assertion comes from.
5. Determine scope from the text alone: what the author put in (`in_scope`) and explicitly excluded (`out_of_scope`). If the text does not say, leave the list empty — do not infer scope.
6. Write `summary.feynman`: 2–4 sentences explaining what the system does, as to a person outside the project. Use only stated facts. If a sentence would require an assumption, leave that part out rather than invent it. This summary is later shown to humans as the tool's understanding.
7. If `<previous_requirements>` is present: for every new requirement, set `matches` to the previous `R` id whose meaning is the same (wording may differ). List previous ids that no longer appear in `removed`.

## Output

Conforms to `schema/extract.json`. Order requirements by position in the text.

## Constraints

- Every line of the specification that asserts something about the system must be covered by at least one requirement.
- Do not normalise vague words ("fast" stays "fast"). Their vagueness is detected later, from the verbatim text.
- Do not add requirements the text implies but does not state.
