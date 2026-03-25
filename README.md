# PDF Combiner

A small desktop app for combining PDF files into one merged PDF in a custom order.

## Stack

- Python
- PySide6
- pypdfium2
- pikepdf

## Install

Create a virtual environment if you want one, then install:

```powershell
python -m pip install -r requirements.txt
```

## Run

On Windows, double-click `run_pdf_combiner.bat`, or run:

```powershell
& '.\run_pdf_combiner.bat'
```

## Build

To build a Windows executable with PyInstaller:

```powershell
& '.\build_windows.bat'
```

The packaged app is created in `dist\PDF Combiner\`.

## Project Notes

- Architecture and extension notes: `docs/ARCHITECTURE.md`
- Agent-oriented maintenance notes: `AGENTS.md`
