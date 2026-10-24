"""Команда `hz init` — настройка LLM-провайдера и персоны."""

import typer

from hztz.cli.UI.console import console
from hztz.core.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PERSONA,
    HzConfig,
    ProviderConfig,
    config_path,
    mask_api_key,
    read_config,
    write_config,
)


def init(
    show: bool = typer.Option(False, "--show", help="Показать конфиг (apiKey маскируется)."),
    path: bool = typer.Option(False, "--path", help="Показать путь к файлу конфига."),
) -> None:
    """Интерактивно создать или отредактировать LLM-конфиг."""
    if path:
        console.print(str(config_path()))
        raise typer.Exit()

    if show:
        _print_config()
        raise typer.Exit()

    existing = read_config()
    if existing:
        console.print(f"Текущий файл: {config_path()}")
        console.print()

    config = _prompt_config(existing)
    write_config(config)
    console.print(f"[green]Конфиг сохранён:[/green] {config_path()}")
    console.print(
        "[yellow]apiKey хранится в открытом виде (права 600) — не коммить этот файл.[/yellow]"
    )


def _print_config() -> None:
    config = read_config()
    console.print(f"[bold]LLM-конфиг[/bold] · {config_path()}")
    if config is None:
        console.print("  (файл ещё не создан)")
        console.print("  Запустите `hz init`, чтобы настроить.")
        return
    console.print(f"  baseURL: {config.provider.baseURL}")
    console.print(f"  model:   {config.provider.model}")
    console.print(f"  apiKey:  {mask_api_key(config.provider.apiKey)}")
    console.print(f"  persona: {config.persona}")


def _prompt_config(current: HzConfig | None) -> HzConfig:
    base_url = typer.prompt(
        "baseURL",
        default=current.provider.baseURL if current else DEFAULT_BASE_URL,
    )

    if current and current.provider.apiKey:
        api_key = typer.prompt(
            "apiKey (Enter — оставить текущий)",
            default="",
            hide_input=True,
            show_default=False,
        )
        api_key = api_key.strip() or current.provider.apiKey
    else:
        api_key = typer.prompt("apiKey", default="", hide_input=True, show_default=False)

    model = typer.prompt(
        "model",
        default=current.provider.model if current else DEFAULT_MODEL,
    )
    persona = typer.prompt(
        "persona",
        default=current.persona if current else DEFAULT_PERSONA,
    )

    return HzConfig(
        provider=ProviderConfig(
            baseURL=base_url.rstrip("/"),
            apiKey=api_key,
            model=model,
        ),
        persona=persona,
    )
