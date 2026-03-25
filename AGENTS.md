# Agent Notes

This repository contains a small desktop PDF combiner app built with Python and Qt.

Read this first when making changes:

- Core UI and workflow live in `pdf_combiner/ui.py`.
- PDF rendering and merge operations live in `pdf_combiner/pdf_ops.py`.
- Theme tokens and stylesheet rules live in `pdf_combiner/theme.py`.
- The app entrypoint is `app.py`.
- Maintainer-facing architecture notes are in `docs/ARCHITECTURE.md`.

Behavioral expectations:

- The app is a single-screen merge tool today. A future welcome screen is possible, but not implemented.
- Users add PDFs via file picker or drag-and-drop.
- Each PDF is represented by one card showing the first page thumbnail, filename, page count, and size.
- Reordering must support both drag-and-drop and explicit up/down buttons.
- Duplicate PDFs are allowed, but duplicate cards should be visibly marked.
- `Save As...` writes a new merged PDF and never modifies the source PDFs.
- Merge history is a popup dropdown anchored to the header button. It shows full details, can be cleared, and should dismiss when focus moves elsewhere.

Editing guidance:

- Preserve the current simple desktop-app feel. Avoid turning it into a browser-like or multi-pane admin UI.
- Keep drag/drop behavior coherent. `PdfListWidget` has custom internal reordering logic; external file drops and internal card moves are intentionally handled separately.
- If you touch preview loading, keep the `PreviewTask` lifetime management intact. The app stores live tasks in `MainWindow.preview_tasks` to avoid premature deletion while worker threads are still emitting signals.
- If you add new persisted preferences, keep them under `QSettings("maxsc", "pdf-combiner")`.

Run/build:

- Local run: `run_pdf_combiner.bat`
- Windows build: `build_windows.bat`

