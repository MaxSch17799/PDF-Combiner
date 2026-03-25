from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
from PySide6.QtCore import QObject, QRunnable, QThread, Signal
from PySide6.QtGui import QImage


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def format_bytes(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def render_first_page(path: str, target_width: int = 320) -> tuple[int, QImage]:
    document = None
    page = None
    bitmap = None

    try:
        document = pdfium.PdfDocument(path)
        page_count = len(document)
        if page_count <= 0:
            raise ValueError("This PDF does not contain any pages.")

        page = document[0]
        page_width, _page_height = page.get_size()
        scale = max((target_width * 2) / max(page_width, 1), 1.0)
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGBA")
        raw = image.tobytes("raw", "RGBA")
        qimage = QImage(raw, image.width, image.height, QImage.Format_RGBA8888).copy()
        return page_count, qimage
    finally:
        if bitmap is not None:
            try:
                bitmap.close()
            except Exception:
                pass
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        if document is not None:
            try:
                document.close()
            except Exception:
                pass


def merge_pdfs(
    file_paths: list[str],
    output_path: str,
    progress_callback: callable | None = None,
) -> None:
    if not file_paths:
        raise ValueError("Add at least one PDF before saving.")

    normalized_output = normalize_path(output_path)
    normalized_inputs = [normalize_path(path) for path in file_paths]
    if normalized_output in normalized_inputs:
        raise ValueError("Choose a new output file. The merged PDF cannot overwrite one of the source PDFs.")

    output_dir = Path(output_path).resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir=output_dir)
    temp_path = temp_handle.name
    temp_handle.close()

    combined = pikepdf.Pdf.new()
    total = len(file_paths)

    try:
        for index, file_path in enumerate(file_paths, start=1):
            if progress_callback is not None:
                progress_callback(index - 1, total, f"Reading {index} of {total}")

            with pikepdf.open(file_path) as source_pdf:
                combined.pages.extend(source_pdf.pages)

            if progress_callback is not None:
                progress_callback(index, total, f"Merging {index} of {total}")

        if progress_callback is not None:
            progress_callback(total, total, "Saving merged PDF")

        combined.save(temp_path)
        os.replace(temp_path, output_path)
    finally:
        try:
            combined.close()
        except Exception:
            pass

        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


class PreviewTaskSignals(QObject):
    loaded = Signal(str, int, object)
    failed = Signal(str, str)


class PreviewTask(QRunnable):
    def __init__(self, item_id: str, file_path: str, target_width: int) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.item_id = item_id
        self.file_path = file_path
        self.target_width = target_width
        self.signals = PreviewTaskSignals()

    def run(self) -> None:
        try:
            page_count, image = render_first_page(self.file_path, self.target_width)
        except Exception as exc:
            self.signals.failed.emit(self.item_id, str(exc))
            return

        self.signals.loaded.emit(self.item_id, page_count, image)


class MergeWorker(QThread):
    progress = Signal(int, int, str)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, file_paths: list[str], output_path: str) -> None:
        super().__init__()
        self.file_paths = file_paths
        self.output_path = output_path

    def run(self) -> None:
        try:
            merge_pdfs(self.file_paths, self.output_path, self.progress.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.succeeded.emit(self.output_path)
