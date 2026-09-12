@echo off
setlocal
cd /d "%~dp0"

where pyw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pyw.exe -3 "%~dp0autoclicker.py"
    exit /b 0
)

where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%~dp0autoclicker.py"
    exit /b 0
)

for %%V in (314 313 312 311 310) do (
    if exist "%LocalAppData%\Programs\Python\Python%%V\pythonw.exe" (
        start "" "%LocalAppData%\Programs\Python\Python%%V\pythonw.exe" "%~dp0autoclicker.py"
        exit /b 0
    )
)

echo Python 3 ne naiden.
echo Ustanovite Python s https://www.python.org/downloads/ i zapustite etot fail snova.
pause
