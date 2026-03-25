@echo off
setlocal

set "APP_DIR=%~dp0"
set "PACKAGED_EXE=%APP_DIR%dist\PDF Combiner\PDF Combiner.exe"
set "SOURCE_LAUNCHER=%APP_DIR%run_pdf_combiner.bat"

if exist "%PACKAGED_EXE%" (
    start "" "%PACKAGED_EXE%"
    exit /b 0
)

if exist "%SOURCE_LAUNCHER%" (
    call "%SOURCE_LAUNCHER%"
    exit /b 0
)

echo Could not find the packaged app or source launcher.
echo Expected:
echo   %PACKAGED_EXE%
echo   %SOURCE_LAUNCHER%
pause
