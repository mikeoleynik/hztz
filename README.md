# hz — хз в тз

CLI, который превращает сырое ТЗ в декомпозированный список задач, не додумывая за автора.

## Установка

```bash
curl -LsSf https://raw.githubusercontent.com/your-org/hztz/main/install.sh | sh
```

Требуется Python 3.11+ (ставится через `uv` автоматически).

## Быстрый старт

```bash
hz init                 # настроить LLM-провайдера и персону
hz audit docs/spec.md   # проверить ТЗ на неопределённости
hz decompose            # построить блоки и задачи
hz next                 # что делать дальше
hz chat                 # разговор по ТЗ и графу состояния
```

## Команды

| Команда | Что делает |
|---------|-----------|
| `init` | Настройка LLM-провайдера (`~/.config/hz/config.json`): `--show`, `--path` |
| `audit` | Проверка ТЗ: требования, находки, вопросы |
| `decompose` | Инженерная модель: блоки и задачи |
| `next` | Следующая задача и её контекст |
| `chat` | Разговор по ТЗ и графу (персоны, слэш-команды) |

## Разработка

```bash
make setup   # uv sync
make test    # pytest
make lint    # ruff + mypy
make build   # uv build
```
