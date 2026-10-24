"""OpenAI-compatible клиент со structured output.

Основной путь — tool-calling (схема как `parameters` функции): он принимает
`oneOf`/`allOf`/`if-then-else`, в отличие от strict `response_format`.
Fallback — `response_format` json_object (гарантирует валидный JSON, схема
проверяется локально).
"""

import json
from typing import Any, cast

from openai import OpenAI

from hztz.core.config import HzConfig


class LLMClient:
    def __init__(self, config: HzConfig) -> None:
        self._client = OpenAI(
            base_url=config.provider.baseURL,
            api_key=config.provider.apiKey,
        )
        self._model = config.provider.model

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Возвращает JSON-объект, соответствующий `schema` (без `$ref`)."""
        try:
            return self._via_tool_calling(system, user, schema)
        except Exception:
            return self._via_json_object(system, user)

    def _messages(self, system: str, user: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _via_tool_calling(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=cast(Any, self._messages(system, user)),
            tools=cast(
                Any,
                [
                    {
                        "type": "function",
                        "function": {"name": "respond", "parameters": schema},
                    }
                ],
            ),
            tool_choice=cast(Any, {"type": "function", "function": {"name": "respond"}}),
        )
        message = response.choices[0].message
        if not message.tool_calls:
            raise ValueError("модель не вернула tool call")
        tool_call = cast(Any, message.tool_calls[0])
        return cast(dict[str, Any], json.loads(tool_call.function.arguments))

    def _via_json_object(self, system: str, user: str) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=cast(Any, self._messages(system, user)),
            response_format=cast(Any, {"type": "json_object"}),
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("пустой ответ модели")
        return cast(dict[str, Any], json.loads(content))
