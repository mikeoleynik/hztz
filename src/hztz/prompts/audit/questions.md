# audit / stage 3 — questions

## Mission

Turn findings into the shortest list of questions (`O`) a human must answer before the system can be built without guessing. A finding is a fact for the tool; a question is a decision point for a person. Several findings may collapse into one question; a low-severity finding may need none.

## Input

- `<findings>` — open findings with ids and severity (new from stage 2 and still-open from earlier runs that have no open question).
- `<requirements>` — for context; refer by id.
- `<existing_questions>` — optional. Open questions from earlier runs, for matching and to avoid duplicates.
- `<repo_context>` — optional. Source of `basis` for options.
- `<spec>` — numbered text, for `basis.type = spec` quotes.

## Procedure

1. **Group by decision.** Findings that would be closed by the same single decision form one question. Findings about different decisions stay separate even if they sit in the same paragraph.
2. **Coverage rule.** Every `blocker` and `high` finding must be referenced by exactly one question. `medium` and `low` findings get a question only if a one-sentence human answer would close them; otherwise leave them without a question (the CLI will keep them visible as notes for implementers).
3. **Write the question** as a request for a decision, answerable in one sentence or by picking an option. Not "how do you see this?" but "when X happens, should the system do A or B?" State the object and the condition explicitly, using the specification's own terms.
4. **`why`.** One or two sentences: what the specification says, what it does not, and what depends on the answer (data model, API, state machine, UX). This is shown to the addressee so they understand the stakes.
5. **Audience.** `business` if the answer changes behaviour visible to users, money, legal or scope. `technical` if it concerns internal contour, libraries, retries, formats, deployment. When both, `business`.
6. **Options.** Add options only when they either logically exhaust the choice (yes/no; the two readings of an inconsistency, each citing its requirement) or have a `basis` (a repository fact, a spec quote, a stated convention). Each option states its `consequence`. A concrete value without basis is not an option. It is acceptable — and common — to have no options.
7. **Match.** If `<existing_questions>` contains a question about the same decision, set `matches` to it instead of creating a duplicate.

## Output

Conforms to `schema/questions.json`. Order: by the highest severity among referenced findings, then business before technical.

## Constraints

- Do not answer the questions. Do not mark any option as recommended.
- Do not ask what the specification or the repository already states (you would have found it in the previous stage).
- Do not ask two things in one question.
- Neutral wording; the addressee may be the customer.
