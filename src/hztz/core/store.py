"""State-файл: снапшот, нумерация, атомарная запись, lock, ID."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from hztz.models.state import State, now_utc

HZ_DIRNAME = ".hz"


def hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_hash(hash_value: str) -> str:
    return hash_value.split(":", 1)[1][:4]


def number_lines(text: str) -> str:
    lines = text.splitlines()
    width = max(3, len(str(len(lines))))
    return "\n".join(f"{i:>{width}}│ {line}" for i, line in enumerate(lines, 1)) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class StateStore:
    """Читает/пишет `.hz/state.json` и снимки ТЗ в рабочей директории."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.hz_dir = root / HZ_DIRNAME

    @property
    def state_path(self) -> Path:
        return self.hz_dir / "state.json"

    @property
    def snapshot_dir(self) -> Path:
        return self.hz_dir / "spec"

    def exists(self) -> bool:
        return self.state_path.exists()

    def load(self) -> State | None:
        if not self.state_path.exists():
            return None
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return State.model_validate(data)

    def save(self, state: State) -> None:
        self.hz_dir.mkdir(parents=True, exist_ok=True)
        state.updated_at = now_utc()
        _atomic_write(self.state_path, state.model_dump_json(indent=2) + "\n")

    def snapshot(self, spec_path: Path) -> tuple[str, str, Path]:
        """Снимок ТЗ с нумерацией. Возвращает (hash, numbered_text, snapshot_path)."""
        text = spec_path.read_text(encoding="utf-8")
        hash_value = hash_text(text)
        numbered = number_lines(text)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snap_path = self.snapshot_dir / f"{hash_value.split(':', 1)[1]}.md"
        snap_path.write_text(numbered, encoding="utf-8")
        return hash_value, numbered, snap_path


def next_id(prefix: str, counter: int) -> str:
    return f"{prefix}{counter}"


def bump_counter(state: State, prefix: str) -> str:
    """Инкрементирует счётчик и возвращает id вида `<prefix><n>`."""
    curr = getattr(state.counters, prefix, 0) + 1
    setattr(state.counters, prefix, curr)
    return next_id(prefix, curr)
