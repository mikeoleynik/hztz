"""Загрузка и dereference JSON-схем стадий.

Схемы в `src/hztz/prompts/` используют `$ref` на `common/schema.json#/$defs/…`.
Для отправки в LLM (tool-calling) и локальной валидации схему разворачиваем в
самодостаточную (без `$ref`).
"""

import json
import posixpath
from functools import cache
from importlib.resources import files
from typing import Any, cast


@cache
def _load_schema(rel: str) -> dict[str, Any]:
    raw = files("hztz.prompts").joinpath(*rel.split("/")).read_text("utf-8")
    return cast(dict[str, Any], json.loads(raw))


def load_schema(rel: str) -> dict[str, Any]:
    """Загружает схему как есть (с `$ref`)."""
    return _load_schema(rel)


def _split_ref(ref: str, current_file: str) -> tuple[str, str]:
    file_part, _, pointer = ref.partition("#")
    if file_part:
        target = posixpath.normpath(posixpath.join(posixpath.dirname(current_file), file_part))
    else:
        target = current_file
    return target, pointer


def _resolve_pointer(doc: Any, pointer: str) -> Any:
    if not pointer:
        return doc
    if pointer.startswith("/"):
        pointer = pointer[1:]
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/") if p != ""]
    for part in parts:
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


def _deref_node(node: Any, current_file: str, seen: frozenset[tuple[str, str]]) -> Any:
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            target_file, pointer = _split_ref(node["$ref"], current_file)
            key = (target_file, pointer)
            if key in seen:
                return node  # циклическая ссылка (в наших схемах не встречается)
            resolved = _resolve_pointer(_load_schema(target_file), pointer)
            return _deref_node(resolved, target_file, seen | {key})
        return {k: _deref_node(v, current_file, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [_deref_node(v, current_file, seen) for v in node]
    return node


def dereference(rel: str) -> dict[str, Any]:
    """Разворачивает `$ref`; возвращает самодостаточную схему."""
    schema = _load_schema(rel)
    return cast(dict[str, Any], _deref_node(schema, rel, frozenset()))
