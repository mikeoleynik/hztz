"""Каталог `.hz/chat/`: один JSON на сессию, имя файла совпадает с id."""

import secrets
from pathlib import Path

from hztz.core.store import _atomic_write
from hztz.models.session import ChatSession

TITLE_LIMIT = 80


def new_session_id() -> str:
    return "ses_" + secrets.token_urlsafe(16)


def fallback_title(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "сессия"
    return stripped.splitlines()[0][:TITLE_LIMIT]


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.dir = root / ".hz" / "chat"

    def path_for(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.json"

    def exists(self, session_id: str) -> bool:
        return self.path_for(session_id).is_file()

    def load(self, session_id: str) -> ChatSession | None:
        path = self.path_for(session_id)
        if not path.is_file():
            return None
        return ChatSession.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, session: ChatSession) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            self.path_for(session.id),
            session.model_dump_json(indent=2) + "\n",
        )
