#!/bin/sh
set -e

echo "🚀 Установка hz (хз в тз)..."

if ! command -v uv >/dev/null 2>&1; then
    echo "📦 Установка uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "⚡️ Установка hztz CLI..."
# TODO: заменить на реальный источник (PyPI или git-репозиторий).
uv tool install hztz --from git+https://github.com/your-org/hztz.git --force

echo "✅ Успешно установлено! Запустите 'hz --help' для проверки."
