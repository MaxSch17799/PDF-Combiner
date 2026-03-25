# Architecture

## Overview

The app is a native desktop PDF combiner built with:

- `PySide6` for the window, widgets, drag/drop, dialogs, and settings
- `pypdfium2` for rendering first-page thumbnails
- `pikepdf` for merge/write operations

The codebase is intentionally small. Most behavior lives in one UI module and two support modules.

## File Layout

- `app.py`
  Loads optional vendored dependencies from `.deps` and starts the Qt app.
- `pdf_combiner/ui.py`
  Main window, card widgets, drag/drop reorder behavior, preview overlay, merge history popup, and merge workflow.
- `pdf_combiner/pdf_ops.py`
  Thumbnail rendering, byte formatting helpers, path normalization, preview worker, and merge worker.
- `pdf_combiner/theme.py`
  Theme definitions and the Qt stylesheet.

## Main Runtime Flow

1. `app.py` imports and runs `pdf_combiner.ui.run()`.
2. `MainWindow` restores settings, builds the header/list/drop area, and loads persisted merge history.
3. Adding files creates one `PdfEntry`, one `QListWidgetItem`, and one `PdfCardWidget` per PDF.
4. `PreviewTask` renders the first page in the global thread pool and reports back through Qt signals.
5. Reorder state is the order of items in `PdfListWidget`.
6. `Save As...` starts `MergeWorker`, which merges the current ordered file paths into a new output PDF.
7. Successful merges are recorded in `MergeHistoryOverlay` and persisted through `QSettings`.

## Important UI Components

### `PdfListWidget`

Custom `QListWidget` subclass responsible for:

- external file drop acceptance
- internal drag reorder behavior
- live placeholder movement during drag
- drag-edge autoscroll
- smooth wheel scrolling
- `Ctrl + mouse wheel` thumbnail resizing

The current implementation intentionally does not rely on Qt's default internal item move behavior for reorder UX. It uses a placeholder row and explicit item movement instead.

### `PdfCardWidget`

Represents one PDF in the merge list. Owns:

- first-page thumbnail
- order badge
- duplicate badge
- metadata labels
- up/down move buttons
- remove button
- right-click action to open the source PDF externally

### `DropArea`

Has two states:

- expanded empty-state layout
- compact "add more PDFs" layout after files exist

The compact bar uses a separate layout rather than shrinking the empty-state layout. This avoids clipped text.

### `MergeHistoryOverlay`

Popup dropdown anchored to the header history button. It:

- shows full details for each recent merge
- exposes `Open PDF` and `Open folder`
- supports `Clear history`
- closes when dismissed or when a history action is taken

## Persistence

`QSettings("maxsc", "pdf-combiner")` stores:

- `ui/geometry`
- `ui/theme_mode`
- `ui/thumbnail_width`
- `paths/last_import_dir`
- `paths/last_save_dir`
- `merge/history`

## Extension Points

If new features are added later, these are the cleanest hooks:

- welcome screen or multi-tool shell: wrap/replace `MainWindow` central layout while keeping the combiner tool as one screen/widget
- page ranges / per-file rotation: extend `PdfEntry` and merge preparation in `pdf_ops.py`
- more metadata in history: extend `MergeRecord`
- different card controls: extend `PdfCardWidget` and keep the list-order contract unchanged

## Invariants To Preserve

- Source PDFs are never modified or deleted.
- Merge order always matches the visible list order.
- Duplicate PDFs remain allowed.
- The app should remain usable without technical knowledge.
- The UI should stay lightweight and single-purpose.

