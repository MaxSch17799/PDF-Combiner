@echo off
setlocal

set "APP_DIR=%~dp0"
set "PYTHONPATH=%PYTHONPATH%"

if exist "%APP_DIR%.deps" (
    set "PYTHONPATH=%APP_DIR%.deps;%PYTHONPATH%"
)

if exist "%APP_DIR%.venv\Scripts\python.exe" (
    "%APP_DIR%.venv\Scripts\python.exe" "%APP_DIR%app.py"
    goto :end
)

if exist "%LocalAppData%\Python\bin\python.exe" (
    "%LocalAppData%\Python\bin\python.exe" "%APP_DIR%app.py"
    goto :end
)

if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" (
    "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" "%APP_DIR%app.py"
    goto :end
)

python "%APP_DIR%app.py"

:end
endlocal
