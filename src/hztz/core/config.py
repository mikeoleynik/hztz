"""Пользовательский LLM-конфиг: ~/.config/hz/config.json (права 600)."""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from hztz.core.exceptions import ConfigMissingError

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_PERSONA = "columbo"


class ProviderConfig(BaseModel):
    baseURL: str = DEFAULT_BASE_URL
    apiKey: str = ""
    model: str = DEFAULT_MODEL


class HzConfig(BaseModel):
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    persona: str = DEFAULT_PERSONA


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "hz" / "config.json"
    return Path.home() / ".config" / "hz" / "config.json"


def read_config() -> HzConfig | None:
    path = config_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return HzConfig.model_validate(data)


def write_config(config: HzConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.model_dump(), indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def require_config() -> HzConfig:
    config = read_config()
    if config is None:
        raise ConfigMissingError("LLM-конфиг не найден. Сначала запустите `hz init`.")
    return config


def mask_api_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return api_key[:4] + "…" + api_key[-4:]
