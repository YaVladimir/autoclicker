#!/bin/zsh
set -e
cd "$(dirname "$0")"
export TK_SILENCE_DEPRECATION=1
export RUN_MACOS_UI_SMOKE=1
python3 -m unittest tests.test_macos_ui_smoke -v
echo
echo "Проверка нативного окна завершена."
read "?Нажмите Enter, чтобы закрыть это окно..."
