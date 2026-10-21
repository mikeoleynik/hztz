"""Кастомные ошибки hz."""


class HzError(Exception):
    """Базовая ошибка инструмента."""


class ConfigMissingError(HzError):
    """LLM-конфиг отсутствует, а команда требует его."""
