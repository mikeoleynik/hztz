# Task {{task.id}} — {{task.title}}

<!-- Rendered by the CLI from the graph (T → B → R, D) + next/context output.
     This is NOT an hz system prompt; it is the brief handed to the implementer. -->

## Block {{block.id}} — {{block.title}}
{{block.purpose}}

## Goal
{{task.goal}}

## Requirements (verbatim from the specification)
{% for r in requirements %}
- **{{r.id}}** (§{{r.section}}): «{{r.text}}»
{% endfor %}

## Decisions (binding)
{% for d in decisions %}
- **{{d.id}}** ({% if d.kind == "assumption" %}ASSUMPTION — made by the developer, not the author; keep it visible in the PR{% else %}answer{% endif %}): {{d.text}}
{% endfor %}
{% if not decisions %}_none_{% endif %}

## Contract
{{block.contract}}

## Files
{% for f in block.files %}
- `{{f.path}}` — {{f.action}}
{% endfor %}
{% if not block.files %}_no repository context; choose paths per project conventions and list them in the PR_{% endif %}

{% if context %}
## Repository conventions
{% for c in context.conventions %}
- {{c.rule}} — `{{c.file}}`
{% endfor %}

Patterns to follow:
{% for e in context.example_files %}
- `{{e.path}}` — {{e.why}}
{% endfor %}

## Suggested approach
{% for step in context.approach %}
{{loop.index}}. {{step}}
{% endfor %}
{% endif %}

## Done when
{% for c in task.done_when %}
- [{% if loop.index0 in already_done_indexes %}x{% else %} {% endif %}] {{c}}
{% endfor %}

{% if task.notes or open_items or context.uncertainties %}
## Notes and open items
{% for n in task.notes %}
- {{n}}
{% endfor %}
{% for o in open_items %}
- open, non-blocking: **{{o.id}}** {{o.text}} — implement as the specification states; do not resolve it yourself
{% endfor %}
{% for u in context.uncertainties %}
- {% if u.blocking %}**UNRESOLVED**{% else %}unclear{% endif %}: {{u.text}}
{% endfor %}
{% endif %}

## Rules for the implementer
- Implement only this task. Do not start work that belongs to other tasks.
- Everything you need is in Requirements, Decisions and Contract. If it is not there and not visible in the cited files — **stop and report it as a question**. Do not pick a default.
- Keep ASSUMPTION items visible in the change description.
- When done, report which Done-when items are satisfied and how they were verified.

<!-- Back-channel: the developer records reported questions with
     hz audit --question "…" --for {{task.id}}
     and closes the task with hz next {{task.id}} --done -->
