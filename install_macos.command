#!/bin/zsh
set -e
cd "$(dirname "$0")"
python3 -m pip install --user -r requirements-macos.txt
echo
echo "Готово. Теперь откройте run_autoclicker_macos.command."
read "?Нажмите Enter, чтобы закрыть это окно..."
