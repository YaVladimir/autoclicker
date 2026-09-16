@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    .venv\Scripts\python.exe -c "import tkinter, customtkinter, PIL" >nul 2>nul
    if errorlevel 1 goto :dependencies
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0autoclicker.py"
    exit /b 0
)

where pyw.exe >nul 2>nul
if %errorlevel%==0 (
    py.exe -3 -c "import tkinter, customtkinter, PIL" >nul 2>nul
    if errorlevel 1 goto :dependencies
    start "" pyw.exe -3 "%~dp0autoclicker.py"
    exit /b 0
)

where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    python.exe -c "import tkinter, customtkinter, PIL" >nul 2>nul
    if errorlevel 1 goto :dependencies
    start "" pythonw.exe "%~dp0autoclicker.py"
    exit /b 0
)

for %%V in (314 313 312 311 310) do (
    if exist "%LocalAppData%\Programs\Python\Python%%V\pythonw.exe" (
        "%LocalAppData%\Programs\Python\Python%%V\python.exe" -c "import tkinter, customtkinter, PIL" >nul 2>nul
        if errorlevel 1 goto :dependencies
        start "" "%LocalAppData%\Programs\Python\Python%%V\pythonw.exe" "%~dp0autoclicker.py"
        exit /b 0
    )
)

echo Python 3 ne naiden.
echo Ustanovite Python s https://www.python.org/downloads/ i zapustite etot fail snova.
pause
exit /b 1

:dependencies
echo Snachala zapustite install_windows.bat dlya ustanovki komponentov interfeisa.
pause
exit /b 1
