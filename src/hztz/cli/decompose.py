"""Команда `hz decompose` — построение инженерной модели (блоки и задачи)."""


from hztz.cli.options import load_config_or_exit
from hztz.cli.UI.console import console


def decompose() -> None:
    """Построение инженерной модели: блоки системы и шаги реализации."""
    load_config_or_exit()
    console.print("[yellow]hz decompose — ещё не реализован.[/yellow]")
