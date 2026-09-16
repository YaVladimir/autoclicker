@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m pip install -r requirements-windows.txt
    if errorlevel 1 goto :failed
    goto :done
)

where py.exe >nul 2>nul
if not errorlevel 1 (
    py.exe -3 -m pip install -r requirements-windows.txt
    if errorlevel 1 goto :failed
    goto :done
)

where python.exe >nul 2>nul
if not errorlevel 1 (
    python.exe -m pip install -r requirements-windows.txt
    if errorlevel 1 goto :failed
    goto :done
)

echo Python 3 ne naiden.
echo Ustanovite Python s https://www.python.org/downloads/ i zapustite etot fail snova.
:failed
    echo Ne udalos ustanovit komponenty prilozheniya.
    pause
    exit /b 1

:done
echo Gotovo. Teper mozhno zapustit run_autoclicker.bat.
pause
