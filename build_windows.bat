@echo off
setlocal

set "APP_DIR=%~dp0"
set "PYTHONPATH=%PYTHONPATH%"

if exist "%APP_DIR%.deps" (
    set "PYTHONPATH=%APP_DIR%.deps;%PYTHONPATH%"
)

set "PYTHON_EXE="

if exist "%APP_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%APP_DIR%.venv\Scripts\python.exe"
    goto build
)

if exist "%LocalAppData%\Python\bin\python.exe" (
    set "PYTHON_EXE=%LocalAppData%\Python\bin\python.exe"
    goto build
)

if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" (
    set "PYTHON_EXE=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
    goto build
)

set "PYTHON_EXE=python"

:build
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean --windowed --name "PDF Combiner" "%APP_DIR%app.py"
endlocal
