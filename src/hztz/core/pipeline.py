"""Pipeline-инфраструктура: композиция system-промта, блоки, вызов стадии."""

import json
from typing import Any

import jsonschema

from hztz.core.config import require_config
from hztz.core.llm.client import LLMClient
from hztz.core.prompts import load_prompt
from hztz.core.schemas import dereference


class StageBlockedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def compose_system(stage_prompt: str) -> str:
    return "\n\n".join(
        [
            load_prompt("common/system.md"),
            load_prompt("common/model.md"),
            load_prompt(stage_prompt),
        ]
    )


def block(tag: str, content: Any) -> str:
    return f"<{tag}>\n{json.dumps(content, ensure_ascii=False, indent=2)}\n</{tag}>"


def raw_block(tag: str, content: str) -> str:
    return f"<{tag}>\n{content}\n</{tag}>"


class StageRunner:
    def __init__(self) -> None:
        self._client = LLMClient(require_config())

    def run(
        self,
        stage_prompt: str,
        schema_rel: str,
        user_blocks: list[str],
        *,
        allow_blocked: bool = False,
    ) -> dict[str, Any]:
        system = compose_system(stage_prompt)
        schema = dereference(schema_rel)
        user = "\n\n".join(b for b in user_blocks if b)
        response = self._client.complete_json(system, user, schema)
        jsonschema.validate(instance=response, schema=schema)
        if response.get("blocked") and not allow_blocked:
            raise StageBlockedError(str(response["blocked"]))
        return response
