"""Общие CLI-хелперы."""

import typer

from hztz.cli.UI.console import console
from hztz.core.config import HzConfig, require_config
from hztz.core.exceptions import ConfigMissingError


def load_config_or_exit() -> HzConfig:
    """Загружает конфиг; при отсутствии — exit 2 с подсказкой `hz init`."""
    try:
        return require_config()
    except ConfigMissingError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=2) from None
