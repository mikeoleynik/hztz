"""REPL `hz chat`: лента, инструменты файлов, слэши поверх ядра графа."""

import json
import shlex
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol, cast

import jsonschema

from hztz.core import audit as audit_core
from hztz.core import next as next_core
from hztz.core.files import FileDenied, apply_edit, read_project_file
from hztz.core.pipeline import compose_system, raw_block
from hztz.core.prompts import load_prompt
from hztz.core.schemas import dereference
from hztz.core.session import SessionStore, fallback_title, new_session_id
from hztz.core.store import StateStore
from hztz.models.session import (
    AssistantMessage,
    ChatSession,
    HzMessage,
    PatchPart,
    TextPart,
    ThinkingPart,
    UserMessage,
)
from hztz.models.state import DKind, LogEntry, State, now_utc
from hztz.templates.render import render_audit_md, render_decomposition_md

MAX_ROUNDS = 8
TITLE_SYSTEM = (
    "Назови разговор одной строкой не длиннее 80 символов, на языке сообщения. "
    "Только заголовок, без кавычек."
)
REPL_SUFFIX = """
## REPL

Reply in plain text. Do not emit the JSON schema.
`read_file` and `edit_file` are available.
A file edit does not record a decision and does not change task status.
The specification file and everything under `.hz/` are not writable.
Do not write into a file a concrete value that resolves an open question.
Offer the matching slash command instead.
""".strip()

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 file inside the project.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace old text with new text in a project file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
                "additionalProperties": False,
            },
        },
    },
]


class ChatLLM(Protocol):
    def stream_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[dict[str, str]]: ...

    def complete_text(self, system: str, user: str) -> str: ...

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]: ...


class ChatModelError(Exception):
    """Сбой модели. Уже записанные части сессии сохраняются."""


def compose_chat_system(persona: str, *, repl: bool) -> str:
    system = "\n\n".join(
        [
            compose_system("chat/prompt.md"),
            load_prompt(f"chat/personas/{persona}.md"),
        ]
    )
    if repl:
        return system + "\n\n" + REPL_SUFFIX
    return system


def drift_line(state: State, session: ChatSession) -> str | None:
    bits: list[str] = []
    if state.spec is not None and session.spec_hash and state.spec.hash != session.spec_hash:
        bits.append("снимок ТЗ изменился")
    own = f"chat:{session.id}"
    created: list[str] = []
    changed: list[str] = []
    for entry in state.log[session.log_cursor :]:
        if entry.via == own:
            continue
        created.extend(entry.created)
        for item in entry.changed:
            ident = str(item.get("id", ""))
            status = str(item.get("status", ""))
            changed.append(f"{ident} {status}".strip())
    if created:
        bits.append("созданы " + ", ".join(created))
    if changed:
        bits.append("изменено " + ", ".join(changed))
    if not bits:
        return None
    return "С прошлого раза: " + "; ".join(bits)


def render_transcript(session: ChatSession) -> str:
    chunks: list[str] = []
    for message in session.messages:
        if isinstance(message, UserMessage):
            chunks.append(f"> {message.text}")
        elif isinstance(message, HzMessage):
            chunks.append(message.text)
        else:
            for part in message.parts:
                if isinstance(part, ThinkingPart):
                    chunks.append("thinking\n" + part.text)
                elif isinstance(part, TextPart):
                    chunks.append(part.text)
                else:
                    chunks.append(_format_patch(part))
    return "\n".join(chunks)


def run_oneshot(
    client: ChatLLM, state: State, root: Path, persona: str, text: str
) -> dict[str, Any]:
    system = compose_chat_system(persona, repl=False)
    user = _user_blob(state, root, session=None, delta=None, message=text)
    schema = dereference("chat/schema.json")
    response = client.complete_json(system, user, schema)
    jsonschema.validate(instance=response, schema=schema)
    return response


def run_repl(
    *,
    root: Path,
    state_store: StateStore,
    sessions: SessionStore,
    client: ChatLLM,
    persona: str,
    yes: bool,
    read: Callable[[], str | None],
    echo: Callable[[str], None],
    emit: Callable[[str, str], None],
    confirm: Callable[[str], bool],
    existing: ChatSession | None = None,
) -> tuple[int, ChatSession | None]:
    session = existing
    pending: str | None = None
    printed: str | None = None
    if session is not None:
        transcript = render_transcript(session)
        if transcript:
            echo(transcript)
    while True:
        state = state_store.load()
        if state is None:
            echo("Нет состояния. Сначала `hz audit SPEC`.")
            return 2, session
        if session is not None:
            drift = drift_line(state, session)
            if drift and drift != printed:
                echo(drift)
                pending = drift
                printed = drift
        line = read()
        if line is None:
            return 0, session
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "/exit":
            return 0, session
        if session is None:
            try:
                compose_chat_system(persona, repl=True)
            except OSError as exc:
                echo(f"неизвестная персона {persona}")
                raise ChatModelError(str(exc)) from exc
            session = ChatSession(
                id=new_session_id(),
                persona=persona,
                spec_hash=state.spec.hash if state.spec is not None else "",
                log_cursor=len(state.log),
            )
        if stripped.startswith("/"):
            output, stored = _slash(
                stripped,
                state=state,
                state_store=state_store,
                session=session,
                yes=yes,
                confirm=confirm,
            )
            if stored:
                session.messages.append(UserMessage(text=stripped))
                if output:
                    session.messages.append(HzMessage(text=output))
            if output:
                echo(output)
            if session.messages:
                _ensure_title(client, session)
                sessions.save(session)
            continue
        session.messages.append(UserMessage(text=stripped))
        _ensure_title(client, session)
        sessions.save(session)
        try:
            parts = _model_turn(
                client,
                root=root,
                state=state,
                session=session,
                delta=pending,
                emit=emit,
            )
        except ChatModelError:
            sessions.save(session)
            return 1, session
        if parts:
            session.messages.append(AssistantMessage(parts=parts))
        if pending is not None:
            pending = None
            printed = None
        session.log_cursor = len(state.log)
        if state.spec is not None:
            session.spec_hash = state.spec.hash
        sessions.save(session)


def _ensure_title(client: ChatLLM, session: ChatSession) -> None:
    if session.title or _user_count(session) != 1:
        return
    first = next(message.text for message in session.messages if isinstance(message, UserMessage))
    session.title = _title(client, first)


def _title(client: ChatLLM, text: str) -> str:
    try:
        raw = client.complete_text(TITLE_SYSTEM, text).strip()
        line = raw.splitlines()[0].strip() if raw else ""
        if not line:
            raise ValueError("пустой заголовок")
        return line[:80]
    except Exception:
        return fallback_title(text)


def _user_count(session: ChatSession) -> int:
    return sum(isinstance(message, UserMessage) for message in session.messages)


def _model_turn(
    client: ChatLLM,
    *,
    root: Path,
    state: State,
    session: ChatSession,
    delta: str | None,
    emit: Callable[[str, str], None],
) -> list[ThinkingPart | TextPart | PatchPart]:
    system = compose_chat_system(session.persona, repl=True)
    user = _user_blob(state, root, session, delta, _last_user_text(session))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    parts: list[ThinkingPart | TextPart | PatchPart] = []
    try:
        for _ in range(MAX_ROUNDS):
            thinking: list[str] = []
            text: list[str] = []
            calls: list[dict[str, str]] = []
            for event in client.stream_turn(messages, TOOLS):
                kind = event.get("type", "")
                if kind == "thinking":
                    chunk = event.get("text", "")
                    thinking.append(chunk)
                    emit("thinking", chunk)
                elif kind == "text":
                    chunk = event.get("text", "")
                    text.append(chunk)
                    emit("text", chunk)
                elif kind == "tool_call":
                    calls.append(event)
            if thinking:
                emit("break", "\n")
                parts.append(ThinkingPart(text="".join(thinking)))
            if text:
                emit("break", "\n")
                parts.append(TextPart(text="".join(text)))
            if not calls:
                return parts
            messages.append(_assistant_tools("".join(text), calls))
            for call in calls:
                result, patch = _dispatch(root, state, call)
                if patch is not None:
                    parts.append(patch)
                    emit("patch", _format_patch(patch) + "\n")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": result,
                    }
                )
    except ChatModelError:
        raise
    except Exception as exc:
        raise ChatModelError(str(exc)) from exc
    return parts


def _last_user_text(session: ChatSession) -> str:
    for message in reversed(session.messages):
        if isinstance(message, UserMessage):
            return message.text
    return ""


def _user_blob(
    state: State,
    root: Path,
    session: ChatSession | None,
    delta: str | None,
    message: str,
) -> str:
    blocks = [
        raw_block("spec", _snapshot(root, state)),
        raw_block("state", _project(state)),
    ]
    if session is not None:
        history = _history(session)
        if history:
            blocks.append(raw_block("history", history))
        paths = _edited_paths(session)
        if paths:
            blocks.append(raw_block("edited_paths", "\n".join(paths)))
    if delta:
        blocks.append(raw_block("state_delta", delta))
    blocks.append(raw_block("message", message))
    return "\n\n".join(blocks)


def _history(session: ChatSession) -> str:
    messages = list(session.messages)
    if messages and isinstance(messages[-1], UserMessage):
        messages = messages[:-1]
    lines: list[str] = []
    for message in messages:
        if isinstance(message, UserMessage):
            lines.append("user: " + message.text)
        elif isinstance(message, HzMessage):
            lines.append("hz: " + message.text)
        else:
            texts = [part.text for part in message.parts if isinstance(part, TextPart)]
            if texts:
                lines.append("assistant: " + "\n".join(texts))
    return "\n".join(lines)


def _edited_paths(session: ChatSession) -> list[str]:
    paths: list[str] = []
    for message in session.messages:
        if not isinstance(message, AssistantMessage):
            continue
        for part in message.parts:
            if isinstance(part, PatchPart) and part.path not in paths:
                paths.append(part.path)
    return paths


def _snapshot(root: Path, state: State) -> str:
    if state.spec is None:
        return ""
    path = Path(state.spec.snapshot)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _project(state: State) -> str:
    lines: list[str] = []
    if state.summary is not None:
        lines.append("summary: " + state.summary.feynman)
    for req in state.requirements:
        lines.append(f"{req.id} [{req.status.value}] {req.text}")
    for finding in state.findings:
        lines.append(
            f"{finding.id} [{finding.status.value}] {finding.title} "
            f"requirements={','.join(finding.requirements)}"
        )
    for question in state.questions:
        lines.append(f"{question.id} [{question.status.value}] {question.text}")
    for decision in state.decisions:
        lines.append(
            f"{decision.id} [{decision.kind.value}] {decision.text} "
            f"closes={','.join(decision.closes)}"
        )
    for block in state.blocks:
        lines.append(f"{block.id} [{block.status.value}] {block.title}")
    for task in state.tasks:
        lines.append(f"{task.id} [{task.status.value}] {task.title} block={task.block}")
    return "\n".join(lines)


def _assistant_tools(text: str, calls: list[dict[str, str]]) -> dict[str, Any]:
    tool_calls: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        if not call.get("id"):
            call["id"] = f"call_{index}"
        tool_calls.append(
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call.get("name", ""),
                    "arguments": call.get("arguments", ""),
                },
            }
        )
    return {"role": "assistant", "content": text or None, "tool_calls": tool_calls}


def _dispatch(
    root: Path,
    state: State,
    call: dict[str, str],
) -> tuple[str, PatchPart | None]:
    try:
        args = cast("dict[str, Any]", json.loads(call.get("arguments") or "{}"))
    except json.JSONDecodeError:
        return "ошибка: аргументы не JSON", None
    name = call.get("name", "")
    if name == "read_file":
        try:
            return read_project_file(root, str(args.get("path", ""))), None
        except (FileDenied, OSError, UnicodeError) as exc:
            return f"ошибка: {exc}", None
    if name == "edit_file":
        path = str(args.get("path", ""))
        old = str(args.get("old", ""))
        new = str(args.get("new", ""))
        try:
            hunk, added, removed = apply_edit(root, state, path, old, new)
        except (FileDenied, OSError, UnicodeError) as exc:
            return f"ошибка: {exc}", None
        return "записано", PatchPart(path=path, added=added, removed=removed, hunk=hunk)
    return f"ошибка: неизвестный инструмент {name}", None


def _format_patch(part: PatchPart) -> str:
    return f"{part.path}  +{part.added} -{part.removed}\n{part.hunk}"


def _slash(
    line: str,
    *,
    state: State,
    state_store: StateStore,
    session: ChatSession,
    yes: bool,
    confirm: Callable[[str], bool],
) -> tuple[str, bool]:
    try:
        parts = shlex.split(line)
    except ValueError as exc:
        return f"не разобрал команду: {exc}", False
    name = parts[0][1:]
    args = parts[1:]
    if name == "persona":
        if not args:
            return "укажите персону", False
        try:
            load_prompt(f"chat/personas/{args[0]}.md")
        except OSError:
            return f"неизвестная персона {args[0]}", False
        session.persona = args[0]
        return f"персона {args[0]}", True
    if name == "status":
        return _status_text(state), False
    if name == "show":
        if not args:
            return "укажите id", False
        return _show(state, args[0]), False
    if name == "next":
        return _next_text(state), False
    if name in {"answer", "assume", "dismiss", "question", "done"}:
        return _mutate(
            name,
            args,
            state=state,
            state_store=state_store,
            session=session,
            yes=yes,
            confirm=confirm,
        )
    return f"неизвестная команда /{name}", False


def _status_text(state: State) -> str:
    open_q = [item for item in state.questions if item.status.value == "open"]
    return f"Открытых вопросов: {len(open_q)}\n{next_core.format_list(state)}"


def _next_text(state: State) -> str:
    result = next_core.choose(state)
    if result.task is None:
        return next_core.format_stop(state, result)
    return next_core.format_card(state, result.task, result.others)


def _show(state: State, ident: str) -> str:
    for req in state.requirements:
        if req.id == ident:
            return f"{req.id} [{req.status.value}] {req.text}"
    for finding in state.findings:
        if finding.id == ident:
            return f"{finding.id} [{finding.status.value}] {finding.title}\n{finding.detail}"
    for question in state.questions:
        if question.id == ident:
            return f"{question.id} [{question.status.value}] {question.text}"
    for decision in state.decisions:
        if decision.id == ident:
            return f"{decision.id} [{decision.kind.value}] {decision.text}"
    for block in state.blocks:
        if block.id == ident:
            return f"{block.id} [{block.status.value}] {block.title}\n{block.purpose}"
    for task in state.tasks:
        if task.id == ident:
            return next_core.format_card(state, task)
    return f"нет объекта {ident}"


def _mutate(
    name: str,
    args: list[str],
    *,
    state: State,
    state_store: StateStore,
    session: ChatSession,
    yes: bool,
    confirm: Callable[[str], bool],
) -> tuple[str, bool]:
    try:
        command, apply, view = _plan(name, args, state)
    except (ValueError, next_core.NextError) as exc:
        return str(exc), False
    echo_line = f"≡ {command}"
    if not yes and not confirm(echo_line):
        return echo_line + "\nне записано", True
    try:
        result = apply()
    except (ValueError, next_core.NextError) as exc:
        return str(exc), False
    text, created, changed = result
    state.log.append(
        LogEntry(
            at=now_utc(),
            cmd=command,
            via=f"chat:{session.id}",
            created=created,
            changed=changed,
        )
    )
    state_store.save(state)
    _write_view(state_store, state, view)
    return echo_line + "\n" + text, True


def _plan(
    name: str,
    args: list[str],
    state: State,
) -> tuple[str, Callable[[], tuple[str, list[str], list[dict[str, Any]]]], str]:
    if name in {"answer", "assume"}:
        if len(args) < 2:
            raise ValueError(f"/{name} ID TEXT")
        ident, text = args[0], " ".join(args[1:])
        kind = DKind.answer if name == "answer" else DKind.assumption
        flag = "--answer" if name == "answer" else "--assume"
        command = f'hz audit {ident} {flag} "{text}"'

        def apply_decision() -> tuple[str, list[str], list[dict[str, Any]]]:
            before = _status_of(state, ident)
            audit_core.answer_or_assume(state, ident, text, kind)
            decision = state.decisions[-1]
            label = "answer" if kind == DKind.answer else "assumption"
            return (
                f"{decision.id} {label} · {ident} → {decision.kind.value}",
                [decision.id],
                [{"id": ident, "status": f"{before} → {_status_of(state, ident)}"}],
            )

        return command, apply_decision, "audit"
    if name == "dismiss":
        if not args:
            raise ValueError("/dismiss ID")
        ident = args[0]
        note = " ".join(args[1:]) or None
        quoted = f' "{note}"' if note else ""
        command = f"hz audit {ident} --dismiss{quoted}"

        def apply_dismiss() -> tuple[str, list[str], list[dict[str, Any]]]:
            before = _status_of(state, ident)
            audit_core.dismiss(state, ident, note)
            return (
                f"{ident} → {_status_of(state, ident)}",
                [],
                [{"id": ident, "status": f"{before} → {_status_of(state, ident)}"}],
            )

        return command, apply_dismiss, "audit"
    if name == "question":
        body, task_id = _split_for(args)
        if not body:
            raise ValueError("/question TEXT")
        flag = f" --for {task_id}" if task_id else ""
        command = f'hz audit --question "{body}"{flag}'

        def apply_question() -> tuple[str, list[str], list[dict[str, Any]]]:
            audit_core.add_question(state, body, task_id)
            created_id = state.questions[-1].id
            changed: list[dict[str, Any]] = []
            if task_id:
                changed.append({"id": task_id, "status": "blocked_by + " + created_id})
            return (f"{created_id} question", [created_id], changed)

        return command, apply_question, "audit"
    if not args:
        task = next_core.sole_in_progress(state)
    else:
        task = next_core.require_task(state, args[0])
    next_core.ensure_closable(task)
    command = f"hz next {task.id} --done"

    def apply_done() -> tuple[str, list[str], list[dict[str, Any]]]:
        before = task.status.value
        next_core.finish(state, task)
        return (
            f"{task.id} {task.status.value}",
            [],
            [{"id": task.id, "status": f"{before} → {task.status.value}"}],
        )

    return command, apply_done, "decomposition"


def _split_for(args: list[str]) -> tuple[str, str | None]:
    if "--for" not in args:
        return " ".join(args), None
    index = args.index("--for")
    task = args[index + 1] if index + 1 < len(args) else None
    text = " ".join(args[:index] + args[index + 2 :])
    return text, task


def _status_of(state: State, ident: str) -> str:
    for question in state.questions:
        if question.id == ident:
            return question.status.value
    for finding in state.findings:
        if finding.id == ident:
            return finding.status.value
    return ""


def _write_view(store: StateStore, state: State, view: str) -> None:
    if state.spec is None or state.summary is None:
        return
    store.hz_dir.mkdir(parents=True, exist_ok=True)
    if view == "audit":
        (store.hz_dir / "audit.md").write_text(render_audit_md(state), encoding="utf-8")
    else:
        (store.hz_dir / "decomposition.md").write_text(
            render_decomposition_md(state),
            encoding="utf-8",
        )
