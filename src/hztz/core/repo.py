"""Сборка `<repo_context>`: детект стека, тест-фреймворка, усечённое дерево."""

from pathlib import Path
from typing import Any

_MANIFEST_STACK = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "package.json": "node",
    "Gemfile": "ruby",
    "go.mod": "go",
    "pom.xml": "java",
    "composer.json": "php",
    "Cargo.toml": "rust",
}

_IGNORED_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".hz",
}


def detect_repo(root: Path) -> bool:
    """Есть ли признаки проекта (`.git` или манифест пакета)."""
    if (root / ".git").exists():
        return True
    return any((root / m).exists() for m in _MANIFEST_STACK)


def detect_stack(root: Path) -> str:
    parts: list[str] = []
    for manifest, stack in _MANIFEST_STACK.items():
        if (root / manifest).exists():
            parts.append(stack)
    return ",".join(parts) if parts else "unknown"


def detect_test_framework(root: Path, stack: str) -> str:
    has_tests = (root / "tests").is_dir() or (root / "test").is_dir()
    if (root / "spec").is_dir():
        return "rspec"
    if has_tests and ("python" in stack or _mentions_pytest(root)):
        return "pytest"
    if (
        (root / "__tests__").is_dir()
        or _has_suffix(root, ".spec.ts")
        or _has_suffix(root, ".test.ts")
    ):
        return "jest"
    if _has_suffix(root, "_test.go"):
        return "go test"
    if has_tests and "node" in stack:
        return "jest"
    if _mentions_pytest(root):
        return "pytest"
    return "unknown"


def _mentions_pytest(root: Path) -> bool:
    for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt"):
        path = root / name
        if path.is_file() and "pytest" in path.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def _has_suffix(root: Path, suffix: str, max_depth: int = 4) -> bool:
    def walk(directory: Path, depth: int) -> bool:
        if depth > max_depth:
            return False
        try:
            entries = list(directory.iterdir())
        except OSError:
            return False
        for entry in entries:
            if entry.name in _IGNORED_DIRS:
                continue
            if entry.is_file() and entry.name.endswith(suffix):
                return True
            if entry.is_dir() and walk(entry, depth + 1):
                return True
        return False

    return walk(root, 0)


_TREE_CHAR_BUDGET = 8_000 * 4


def build_tree(root: Path, max_depth: int = 4, max_entries: int = 200) -> str:
    lines: list[str] = []

    def walk(directory: Path, prefix: str, depth: int) -> None:
        if depth > max_depth or len(lines) >= max_entries:
            return
        try:
            names = list(directory.iterdir())
        except OSError:
            return
        entries = sorted(
            (e for e in names if e.name not in _IGNORED_DIRS),
            key=lambda e: (e.is_file(), e.name),
        )
        for i, entry in enumerate(entries):
            if len(lines) >= max_entries:
                return
            is_last = i == len(entries) - 1
            suffix = "/" if entry.is_dir() else ""
            lines.append(prefix + ("└── " if is_last else "├── ") + entry.name + suffix)
            if entry.is_dir() and depth < max_depth:
                walk(entry, prefix + ("    " if is_last else "│   "), depth + 1)

    walk(root, "", 0)
    text = "\n".join(lines)
    if len(text) <= _TREE_CHAR_BUDGET:
        return text
    trimmed = text[:_TREE_CHAR_BUDGET].rsplit("\n", 1)[0]
    return trimmed + "\n…"


def build_repo_context(root: Path) -> dict[str, Any] | None:
    if not detect_repo(root):
        return None
    stack = detect_stack(root)
    return {
        "stack": stack,
        "test_framework": detect_test_framework(root, stack),
        "tree": build_tree(root),
    }
