"""Чтение и правка файлов проекта из чата. Граф и ТЗ модель не перезаписывает."""

import difflib
from pathlib import Path

from hztz.models.state import State


class FileDenied(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _resolved(root: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _inside(root: Path, path: Path) -> bool:
    root_resolved = root.resolve()
    return path == root_resolved or root_resolved in path.parents


def _is_secret(path: Path) -> bool:
    name = path.name
    if name == ".env":
        return True
    return name.endswith(".env") and not name.endswith(".env.example")


def _under_hz(root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] == ".hz"


def spec_path(root: Path, state: State) -> Path | None:
    if state.spec is None:
        return None
    return _resolved(root, state.spec.path)


def check_read(root: Path, raw: str) -> Path:
    path = _resolved(root, raw)
    if not _inside(root, path):
        raise FileDenied("путь вне проекта")
    if _is_secret(path):
        raise FileDenied("секретный файл")
    return path


def check_write(root: Path, state: State, raw: str) -> Path:
    path = check_read(root, raw)
    if _under_hz(root, path):
        raise FileDenied("каталог .hz закрыт для записи")
    spec = spec_path(root, state)
    if spec is not None and path == spec:
        raise FileDenied("файл ТЗ закрыт для записи")
    return path


def read_project_file(root: Path, raw: str) -> str:
    path = check_read(root, raw)
    if not path.is_file():
        raise FileDenied("файл не найден")
    return path.read_text(encoding="utf-8")


def unified_diff(path: str, before: str, after: str) -> tuple[str, int, int]:
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return diff, added, removed


def apply_edit(root: Path, state: State, raw: str, old: str, new: str) -> tuple[str, int, int]:
    """Возвращает (hunk, added, removed). Отказ — FileDenied, файл не меняется."""
    path = check_write(root, state, raw)
    display = str(path.relative_to(root.resolve())) if _inside(root, path) else raw
    if path.is_file():
        before = path.read_text(encoding="utf-8")
        if old not in before:
            raise FileDenied("фрагмент для замены не найден")
        after = before.replace(old, new, 1)
    elif old == "":
        before = ""
        after = new
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        raise FileDenied("файл не найден")
    hunk, added, removed = unified_diff(display, before, after)
    if before == after:
        raise FileDenied("правка ничего не меняет")
    path.write_text(after, encoding="utf-8")
    return hunk, added, removed
