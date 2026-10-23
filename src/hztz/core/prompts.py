"""Загрузка промтов из package data (src/hztz/prompts/)."""

from importlib.resources import files


def load_prompt(*parts: str) -> str:
    return files("hztz.prompts").joinpath(*parts).read_text(encoding="utf-8")
