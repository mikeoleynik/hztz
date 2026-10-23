# audit / stage 2 — findings

## Mission

Answer one question about the specification: **can it be implemented without guessing on the author's behalf?** Every place where an implementer would have to guess is a finding (`A`). Do not report what could be *improved*; report what would have to be *invented*.

## Input

- `<spec>` — numbered specification text (for verbatim quotes).
- `<requirements>` — the `R` list with ids (from stage 1). Refer to requirements by id.
- `<summary>` — scope from stage 1. Requirements outside `out_of_scope` topics are still analysed; findings about excluded topics are not produced.
- `<repo_context>` — optional. Facts about the existing codebase: conventions, existing components, configuration values. Evidence, not requirement.
- `<decisions>` — optional. Current human decisions `D` with the questions they closed. Present on re-audit.
- `<existing_findings>` — optional. Open and resolved findings from the previous run, for matching.

## Procedure

1. **Walk through.** For each requirement, explain to yourself in plain words how the system behaves. Every time the explanation needs information that is not `stated` or `derived`, mark the spot. These spots are your finding candidates. Do this before applying the checklists — the checklists exist to catch what the walk-through missed, not to replace it.
2. **Checklists, per requirement or behaviour:**
   - `ambiguous` — undefined terms, qualitative words without a measure, "or / as needed / depending on", references to things not defined anywhere in the text.
   - `incomplete` — for each behaviour: happy path, alternative path, negative path, boundary conditions, failure of a dependency. For the system: NFR categories (ISO 25010) that the text touches but does not quantify. For each requirement: can an acceptance criterion be written from the text alone? Set `missing` accordingly.
   - `inconsistent` — pairs of requirements that define the same state, rule or value differently. If `<decisions>` is present, also each decision against the requirements it touches: a decision the new text contradicts is a finding with evidence `{decision}` + lines.
   - `infeasible` — a requirement that conflicts with a stated constraint (another requirement or repo fact). Only with both refs. Word it as *potential*.
   - `unverifiable` — no test or observation could confirm it.
3. **Suppress.** Drop a candidate if the specification answers it elsewhere (you must be able to cite the lines) or the repository context answers it (cite the file). Do not output suppressed candidates.
4. **Deduplicate.** One finding per distinct gap. Five vague performance words about the same endpoint are one `ambiguous` finding with five evidence entries, not five findings.
5. **Severity and confidence.** Severity by impact on implementation (see data model). Confidence by how sure you are the gap is real, independent of severity. If you are unsure whether the text covers it, lower confidence — do not drop the finding.
6. **`what_to_specify`.** Phrase the remedy as what the author must specify, not as a value. A value is allowed only with a basis from `<repo_context>` or the text, stated inside the field ("existing SLA for /api/v1 is 200 ms — config/sla.yml:4").
7. **Match.** If `<existing_findings>` is present, set `matches` to the existing id when your finding is the same gap (same kind, same requirements, same place), even if you would word it differently.

## Output

Conforms to `schema/findings.json`. Order by severity (blocker first), then by first evidence line.

## Constraints

- Neutral engineering language. No persona, no rhetorical questions, no praise.
- No finding without at least one requirement id and one evidence entry.
- Do not produce questions here — the next stage forms them from your findings.
- `goal`-kind requirements yield findings only when a goal contradicts a functional requirement.
