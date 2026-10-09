@echo off
setlocal
cd /d "%~dp0"

py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
) else (
    python --version >nul 2>&1
    if errorlevel 1 goto no_python
    set "PY=python"
)

if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 goto failed
)

if not exist ".env" copy ".env.example" ".env" >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo.
echo Starting Job Application Agent on http://127.0.0.1:8000
echo Keep this window open while using the app. Press Ctrl+C to stop it.
".venv\Scripts\python.exe" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
goto done

:no_python
echo Python 3 was not found. Install Python 3.11 or newer, then run this file again.
goto failed

:failed
echo.
echo Setup or startup failed. Check the error above, then try again.

:done
pause
