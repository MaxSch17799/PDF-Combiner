from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QDateTime,
    QPoint,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QDrag, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedLayout,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .pdf_ops import MergeWorker, PreviewTask, format_bytes, normalize_path
from .theme import build_palette, build_stylesheet, theme_spec


def desktop_path() -> str:
    return str(Path.home() / "Desktop")


def extract_pdf_paths_from_mime_data(mime_data) -> list[str]:  # noqa: ANN001
    if not mime_data.hasUrls():
        return []
    return [
        url.toLocalFile()
        for url in mime_data.urls()
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() == ".pdf"
    ]


@dataclass
class PdfEntry:
    item_id: str
    file_path: str
    file_name: str
    file_size_bytes: int
    page_count: int | None = None
    preview_image: QImage | None = None
    is_duplicate: bool = False
    is_loading: bool = True
    error_message: str | None = None


@dataclass
class MergeRecord:
    output_path: str
    created_at_iso: str
    file_size_bytes: int

    @property
    def file_name(self) -> str:
        return Path(self.output_path).name

    @property
    def folder_path(self) -> str:
        return str(Path(self.output_path).resolve().parent)

    @property
    def created_label(self) -> str:
        timestamp = QDateTime.fromString(self.created_at_iso, Qt.ISODate)
        if not timestamp.isValid():
            return self.created_at_iso
        return timestamp.toString("yyyy-MM-dd HH:mm:ss")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "output_path": self.output_path,
            "created_at_iso": self.created_at_iso,
            "file_size_bytes": self.file_size_bytes,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "MergeRecord":
        return cls(
            output_path=str(payload["output_path"]),
            created_at_iso=str(payload["created_at_iso"]),
            file_size_bytes=int(payload["file_size_bytes"]),
        )


class PreviewHoverLabel(QLabel):
    hover_started = Signal()
    hover_ended = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self.hover_started.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self.hover_ended.emit()
        super().leaveEvent(event)


class PdfListWidget(QListWidget):
    order_changed = Signal()
    thumbnail_zoom_requested = Signal(int)
    files_dropped = Signal(list)
    file_drag_active_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setSpacing(14)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setDragDropMode(QListWidget.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setAutoScroll(True)
        self.setAutoScrollMargin(72)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setIconSize(QSize(1, 1))
        self.setMouseTracking(True)
        self.viewport().setAcceptDrops(True)
        self.verticalScrollBar().setSingleStep(16)

        self._dragging_internal = False
        self._drag_hover_pos: QPoint | None = None
        self._autoscroll_speed = 0
        self._dragged_item: QListWidgetItem | None = None
        self._dragged_widget: QWidget | None = None
        self._drag_placeholder: QWidget | None = None
        self._drag_original_row: int | None = None
        self._internal_drop_committed = False

        self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_animation.setDuration(140)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)

        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.setInterval(16)
        self._autoscroll_timer.timeout.connect(self._perform_autoscroll)

    def startDrag(self, supported_actions) -> None:  # noqa: ANN001
        item = self.currentItem()
        if item is None:
            return

        widget = self.itemWidget(item)
        if widget is None:
            return

        mime_data = self.model().mimeData(self.selectedIndexes())
        if mime_data is None:
            return

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        pixmap = self._create_drag_pixmap(widget)
        drag.setPixmap(pixmap)
        local_pos = widget.mapFromGlobal(QCursor.pos())
        drag.setHotSpot(local_pos + QPoint(16, 16))

        self._dragging_internal = True
        self._internal_drop_committed = False
        self._dragged_item = item
        self._dragged_widget = widget
        self._drag_original_row = self.row(item)
        self._drag_placeholder = self._create_drag_placeholder(widget)

        self.removeItemWidget(item)
        self.setItemWidget(item, self._drag_placeholder)
        item.setSizeHint(self._drag_placeholder.sizeHint())
        widget.hide()

        drag.exec(Qt.MoveAction)

        if not self._internal_drop_committed and self._dragged_item is not None and self._drag_original_row is not None:
            self._move_item_with_widget(self.row(self._dragged_item), self._drag_original_row, self._drag_placeholder)

        if self._dragged_item is not None and self._dragged_widget is not None:
            self.removeItemWidget(self._dragged_item)
            self.setItemWidget(self._dragged_item, self._dragged_widget)
            self._dragged_item.setSizeHint(self._dragged_widget.sizeHint())
            self._dragged_widget.show()
            self.setCurrentItem(self._dragged_item)

        drop_committed = self._internal_drop_committed
        self._reset_drag_state()
        if not drop_committed:
            self.order_changed.emit()

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if extract_pdf_paths_from_mime_data(event.mimeData()):
            self.file_drag_active_changed.emit(True)
            event.acceptProposedAction()
            return

        self._dragging_internal = event.source() is self
        if self._dragging_internal:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if extract_pdf_paths_from_mime_data(event.mimeData()):
            self.file_drag_active_changed.emit(True)
            event.acceptProposedAction()
            return

        self._dragging_internal = event.source() is self
        if self._dragging_internal:
            pos = self._event_pos(event)
            self._drag_hover_pos = pos
            self._update_autoscroll(pos)
            self._reorder_dragged_item(pos)
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: ANN001
        self.file_drag_active_changed.emit(False)
        self._stop_autoscroll_feedback()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001
        paths = extract_pdf_paths_from_mime_data(event.mimeData())
        if paths:
            self.file_drag_active_changed.emit(False)
            self._reset_drag_state()
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return

        if self._dragging_internal:
            self._internal_drop_committed = True
            event.acceptProposedAction()
            self._stop_autoscroll_feedback()
            self.order_changed.emit()
            return

        super().dropEvent(event)
        self._reset_drag_state()
        self.order_changed.emit()

    def wheelEvent(self, event) -> None:  # noqa: ANN001
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.thumbnail_zoom_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return

        scroll_bar = self.verticalScrollBar()
        pixel_delta = event.pixelDelta().y()
        angle_delta = event.angleDelta().y()

        if pixel_delta:
            change = -pixel_delta
        elif angle_delta:
            steps = angle_delta / 120
            change = int(-steps * scroll_bar.singleStep() * 4)
        else:
            super().wheelEvent(event)
            return

        target_value = max(scroll_bar.minimum(), min(scroll_bar.maximum(), scroll_bar.value() + change))
        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(scroll_bar.value())
        self._scroll_animation.setEndValue(target_value)
        self._scroll_animation.start()
        event.accept()

    def _event_pos(self, event) -> QPoint:  # noqa: ANN001
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _stop_autoscroll_feedback(self) -> None:
        self._dragging_internal = False
        self._drag_hover_pos = None
        self._autoscroll_speed = 0
        self._autoscroll_timer.stop()

    def _reset_drag_state(self) -> None:
        self._stop_autoscroll_feedback()
        self._dragged_item = None
        self._dragged_widget = None
        self._drag_placeholder = None
        self._drag_original_row = None
        self._internal_drop_committed = False

    def _update_autoscroll(self, pos: QPoint) -> None:
        margin = 72
        viewport_height = self.viewport().height()

        if pos.y() < margin:
            distance = margin - pos.y()
            self._autoscroll_speed = -max(6, min(28, distance // 2))
        elif pos.y() > viewport_height - margin:
            distance = pos.y() - (viewport_height - margin)
            self._autoscroll_speed = max(6, min(28, distance // 2))
        else:
            self._autoscroll_speed = 0

        if self._autoscroll_speed:
            if not self._autoscroll_timer.isActive():
                self._autoscroll_timer.start()
        else:
            self._autoscroll_timer.stop()

    def _perform_autoscroll(self) -> None:
        if not self._dragging_internal:
            self._autoscroll_timer.stop()
            return

        scroll_bar = self.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.value() + self._autoscroll_speed)
        cursor_pos = self.viewport().mapFromGlobal(QCursor.pos())
        self._drag_hover_pos = cursor_pos
        self._reorder_dragged_item(cursor_pos)

    def _create_drag_placeholder(self, source_widget: QWidget) -> QWidget:
        placeholder = QFrame()
        placeholder.setObjectName("DragPlaceholder")
        placeholder.setFixedHeight(source_widget.height())
        placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return placeholder

    def _create_drag_pixmap(self, source_widget: QWidget) -> QPixmap:
        base = source_widget.grab()
        padding = 16
        shadow_offset = 8
        drag_pixmap = QPixmap(base.width() + (padding * 2), base.height() + (padding * 2) + shadow_offset)
        drag_pixmap.fill(Qt.transparent)

        painter = QPainter(drag_pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 72))
        painter.drawRoundedRect(padding, padding + shadow_offset, base.width(), base.height(), 18, 18)
        painter.drawPixmap(padding, padding, base)
        painter.end()
        return drag_pixmap

    def _reorder_dragged_item(self, pos: QPoint) -> None:
        if self._dragged_item is None or self._drag_placeholder is None:
            return

        current_row = self.row(self._dragged_item)
        target_row = self._target_row_for_position(pos, current_row)
        if target_row is None or target_row == current_row:
            return

        self._move_item_with_widget(current_row, target_row, self._drag_placeholder)
        self.setCurrentItem(self._dragged_item)

    def _target_row_for_position(self, pos: QPoint, current_row: int) -> int | None:
        item = self.itemAt(pos)
        if item is None:
            if self.count() == 0:
                return None
            if pos.y() < 0:
                return 0
            return self.count() - 1

        row = self.row(item)
        rect = self.visualItemRect(item)
        insert_index = row if pos.y() < rect.center().y() else row + 1
        if insert_index > current_row:
            insert_index -= 1
        return max(0, min(self.count() - 1, insert_index))

    def _move_item_with_widget(self, from_row: int, to_row: int, widget: QWidget | None) -> None:
        if from_row == to_row:
            return

        item = self.item(from_row)
        if item is None:
            return

        if widget is not None:
            self.removeItemWidget(item)

        item = self.takeItem(from_row)
        self.insertItem(to_row, item)
        if widget is not None:
            self.setItemWidget(item, widget)
            item.setSizeHint(widget.sizeHint())


class DropArea(QFrame):
    add_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropArea")
        self.setProperty("dragActive", False)
        self.setProperty("compact", False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedLayout()
        outer.addLayout(self.stack)

        expanded_page = QWidget()
        expanded_layout = QVBoxLayout(expanded_page)
        expanded_layout.setContentsMargins(28, 28, 28, 28)
        expanded_layout.setSpacing(10)

        self.title_label = QLabel("Drag PDFs here")
        self.title_label.setObjectName("DropTitle")
        self.title_label.setAlignment(Qt.AlignCenter)

        self.subtitle_label = QLabel("or choose files from your computer")
        self.subtitle_label.setObjectName("SubtitleLabel")
        self.subtitle_label.setAlignment(Qt.AlignCenter)

        self.add_button = QPushButton("Add PDFs")
        self.add_button.setObjectName("AddButton")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self.add_clicked.emit)

        expanded_layout.addStretch()
        expanded_layout.addWidget(self.title_label)
        expanded_layout.addWidget(self.subtitle_label)
        expanded_layout.addWidget(self.add_button, alignment=Qt.AlignCenter)
        expanded_layout.addStretch()

        compact_page = QWidget()
        compact_layout = QHBoxLayout(compact_page)
        compact_layout.setContentsMargins(20, 12, 20, 12)
        compact_layout.setSpacing(14)

        self.compact_title_label = QLabel("Add more PDFs")
        self.compact_title_label.setObjectName("CompactDropTitle")
        self.compact_title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self.compact_hint_label = QLabel("Drop PDFs here or use the button")
        self.compact_hint_label.setObjectName("SubtitleLabel")
        self.compact_hint_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self.compact_add_button = QPushButton("Add PDFs")
        self.compact_add_button.setObjectName("CompactAddButton")
        self.compact_add_button.setCursor(Qt.PointingHandCursor)
        self.compact_add_button.clicked.connect(self.add_clicked.emit)

        compact_text = QVBoxLayout()
        compact_text.setContentsMargins(0, 0, 0, 0)
        compact_text.setSpacing(2)
        compact_text.addWidget(self.compact_title_label)
        compact_text.addWidget(self.compact_hint_label)

        compact_layout.addLayout(compact_text, stretch=1)
        compact_layout.addWidget(self.compact_add_button, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.stack.addWidget(expanded_page)
        self.stack.addWidget(compact_page)

        self.set_item_count(0)

    def set_item_count(self, item_count: int) -> None:
        compact = item_count > 0
        self.setProperty("compact", compact)

        if item_count <= 0:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.setMinimumHeight(220)
            self.setMaximumHeight(16777215)
            self.stack.setCurrentIndex(0)
            self.title_label.setText("Drag PDFs here")
            self.subtitle_label.setText("Build your merge list with drag and drop or the file picker")
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.stack.setCurrentIndex(1)
            self.setFixedHeight(88 if item_count == 1 else 72)
            self.compact_title_label.setText("Add more PDFs")
            self.compact_hint_label.setText("Drop PDFs here or use the button")
            self.compact_hint_label.setVisible(item_count == 1)

        self.style().unpolish(self)
        self.style().polish(self)

    def set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)


class PdfCardWidget(QFrame):
    remove_requested = Signal(str)
    move_requested = Signal(str, int)
    open_requested = Signal(str)
    preview_requested = Signal(object, object)
    preview_hidden = Signal()

    def __init__(self, entry: PdfEntry, thumbnail_width: int) -> None:
        super().__init__()
        self.entry = entry
        self.thumbnail_width = thumbnail_width
        self.thumbnail_image: QImage | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(1000)
        self._preview_timer.timeout.connect(self._emit_preview_request)

        self.setObjectName("CardFrame")
        self.setFrameShape(QFrame.NoFrame)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setCursor(Qt.OpenHandCursor)
        self.customContextMenuRequested.connect(self.show_context_menu)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        self.preview_label = PreviewHoverLabel()
        self.preview_label.setObjectName("PreviewLabel")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.hover_started.connect(self._handle_preview_hover_started)
        self.preview_label.hover_ended.connect(self._handle_preview_hover_ended)

        self.order_badge = QLabel("#1")
        self.order_badge.setObjectName("OrderBadge")
        self.order_badge.setAlignment(Qt.AlignCenter)

        self.duplicate_badge = QLabel("Duplicate")
        self.duplicate_badge.setObjectName("BadgeLabel")
        self.duplicate_badge.setVisible(False)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        self.title_label = QLabel(self.entry.file_name)
        self.title_label.setObjectName("CardTitle")
        self.title_label.setWordWrap(True)

        title_row.addWidget(self.order_badge, alignment=Qt.AlignTop)
        title_row.addWidget(self.title_label, stretch=1)
        title_row.addWidget(self.duplicate_badge, alignment=Qt.AlignTop)

        self.meta_label = QLabel()
        self.meta_label.setObjectName("MetaLabel")

        self.status_label = QLabel()
        self.status_label.setObjectName("StatusLabel")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)
        text_layout.addLayout(title_row)
        text_layout.addWidget(self.meta_label)
        text_layout.addWidget(self.status_label)
        text_layout.addStretch()

        controls = QVBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self.up_button = QToolButton()
        self.up_button.setText("^")
        self.up_button.setCursor(Qt.PointingHandCursor)
        self.up_button.clicked.connect(lambda: self.move_requested.emit(self.entry.item_id, -1))

        self.down_button = QToolButton()
        self.down_button.setText("v")
        self.down_button.setCursor(Qt.PointingHandCursor)
        self.down_button.clicked.connect(lambda: self.move_requested.emit(self.entry.item_id, 1))

        self.remove_button = QToolButton()
        self.remove_button.setText("Remove")
        self.remove_button.setCursor(Qt.PointingHandCursor)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.entry.item_id))

        controls.addWidget(self.up_button)
        controls.addWidget(self.down_button)
        controls.addSpacerItem(QSpacerItem(12, 12, QSizePolicy.Minimum, QSizePolicy.Expanding))
        controls.addWidget(self.remove_button)

        root.addWidget(self.preview_label)
        root.addLayout(text_layout, stretch=1)
        root.addLayout(controls)

        self.set_preview_width(thumbnail_width)
        self.refresh()

    def sizeHint(self) -> QSize:  # noqa: D401
        return QSize(720, self.preview_label.height() + 36)

    def set_order_index(self, order_index: int) -> None:
        self.order_badge.setText(f"#{order_index}")

    def set_preview_width(self, thumbnail_width: int) -> None:
        self.thumbnail_width = thumbnail_width
        preview_height = int(thumbnail_width * 1.35)
        self.preview_label.setFixedSize(thumbnail_width, preview_height)
        self._refresh_thumbnail()

    def set_duplicate(self, is_duplicate: bool) -> None:
        self.entry.is_duplicate = is_duplicate
        self.duplicate_badge.setVisible(is_duplicate)

    def set_preview(self, image: QImage) -> None:
        self.thumbnail_image = image
        self.entry.preview_image = image
        self._refresh_thumbnail()

    def set_page_count(self, page_count: int) -> None:
        self.entry.page_count = page_count
        self.refresh()

    def set_loading_state(self, is_loading: bool, error_message: str | None = None) -> None:
        self.entry.is_loading = is_loading
        self.entry.error_message = error_message
        self.refresh()

    def refresh(self) -> None:
        file_size = format_bytes(self.entry.file_size_bytes)
        if self.entry.page_count is None:
            page_text = "Pages: loading..."
        elif self.entry.page_count == 1:
            page_text = "1 page"
        else:
            page_text = f"{self.entry.page_count} pages"

        self.meta_label.setText(f"{page_text}  |  {file_size}")

        if self.entry.error_message:
            self.status_label.setText(self.entry.error_message)
            self.status_label.setProperty("error", True)
        elif self.entry.is_loading:
            self.status_label.setText("Loading first-page preview...")
            self.status_label.setProperty("error", False)
        else:
            self.status_label.setText("Right-click to open the original PDF.")
            self.status_label.setProperty("error", False)

        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.set_duplicate(self.entry.is_duplicate)
        self._refresh_thumbnail()

    def show_context_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        open_action = QAction("Open original PDF", self)
        open_action.triggered.connect(lambda: self.open_requested.emit(self.entry.file_path))
        menu.addAction(open_action)
        menu.exec(self.mapToGlobal(pos))

    def _refresh_thumbnail(self) -> None:
        if self.thumbnail_image is None:
            self.preview_label.setPixmap(self._placeholder_pixmap())
            return

        pixmap = QPixmap.fromImage(self.thumbnail_image).scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(pixmap)

    def _placeholder_pixmap(self) -> QPixmap:
        pixmap = QPixmap(self.preview_label.size())
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = pixmap.rect().adjusted(6, 6, -6, -6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.palette().alternateBase())
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(self.palette().text().color())
        painter.drawText(rect, Qt.AlignCenter, "PDF")
        painter.end()
        return pixmap

    def _handle_preview_hover_started(self) -> None:
        if self.thumbnail_image is None or self.entry.is_loading or self.entry.error_message:
            return
        self._preview_timer.start()

    def _handle_preview_hover_ended(self) -> None:
        self._preview_timer.stop()
        self.preview_hidden.emit()

    def _emit_preview_request(self) -> None:
        if self.thumbnail_image is None:
            return
        self.preview_requested.emit(self.thumbnail_image, self.preview_label)


class HoverPreviewOverlay(QFrame):
    def __init__(self) -> None:
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("PreviewOverlay")
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.preview_label)

    def show_preview(self, image: QImage, source_widget: QWidget) -> None:
        pixmap = QPixmap.fromImage(image).scaled(
            420,
            560,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(pixmap)
        self.adjustSize()

        screen = source_widget.screen()
        if screen is None:
            self.show()
            return

        screen_rect = screen.availableGeometry()
        source_global = source_widget.mapToGlobal(QPoint(0, 0))
        target_x = source_global.x() + source_widget.width() + 18
        target_y = source_global.y() - 10

        if target_x + self.width() > screen_rect.right():
            target_x = source_global.x() - self.width() - 18

        if target_x < screen_rect.left():
            target_x = screen_rect.left() + 12

        if target_y + self.height() > screen_rect.bottom():
            target_y = screen_rect.bottom() - self.height() - 12

        if target_y < screen_rect.top():
            target_y = screen_rect.top() + 12

        self.move(target_x, target_y)
        self.show()
        self.raise_()

    def hide_preview(self) -> None:
        self.hide()


class MergeHistoryItemWidget(QFrame):
    open_pdf_requested = Signal(str)
    open_folder_requested = Signal(str)

    def __init__(self, record: MergeRecord) -> None:
        super().__init__()
        self.record = record
        self.setObjectName("MergeHistoryItem")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title_label = QLabel(record.file_name)
        title_label.setObjectName("HistoryTitle")
        title_label.setWordWrap(True)

        meta_label = QLabel(f"{record.created_label}  |  {format_bytes(record.file_size_bytes)}")
        meta_label.setObjectName("HistoryMeta")

        folder_label = QLabel(record.folder_path)
        folder_label.setObjectName("HistoryMeta")
        folder_label.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        open_pdf_button = QPushButton("Open PDF")
        open_pdf_button.setCursor(Qt.PointingHandCursor)
        open_pdf_button.clicked.connect(lambda: self.open_pdf_requested.emit(record.output_path))

        open_folder_button = QPushButton("Open folder")
        open_folder_button.setCursor(Qt.PointingHandCursor)
        open_folder_button.clicked.connect(lambda: self.open_folder_requested.emit(record.output_path))

        actions.addWidget(open_pdf_button)
        actions.addWidget(open_folder_button)
        actions.addStretch()

        layout.addWidget(title_label)
        layout.addWidget(meta_label)
        layout.addWidget(folder_label)
        layout.addLayout(actions)


class MergeHistoryOverlay(QFrame):
    open_pdf_requested = Signal(str)
    open_folder_requested = Signal(str)
    state_changed = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("MergeOverlay")
        self.setVisible(False)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self.records: list[MergeRecord] = []
        self._max_records = 12
        self._anchor_button: QWidget | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        self.header_title = QLabel("Merge history")
        self.header_title.setObjectName("OverlayTitle")
        self.header_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.count_badge = QLabel("0")
        self.count_badge.setObjectName("BadgeLabel")

        self.clear_button = QPushButton("Clear history")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear_history)

        self.close_button = QToolButton()
        self.close_button.setText("X")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(self.hide_overlay)

        header_row.addWidget(self.header_title)
        header_row.addWidget(self.count_badge)
        header_row.addWidget(self.clear_button)
        header_row.addWidget(self.close_button)

        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_scroll.setFrameShape(QFrame.NoFrame)

        self.history_content = QWidget()
        self.history_layout = QVBoxLayout(self.history_content)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(10)
        self.history_scroll.setWidget(self.history_content)

        root.addLayout(header_row)
        root.addWidget(self.history_scroll)

        self.resize(520, 260)
        self._refresh()

    def load_records(self, serialized_value: str) -> None:
        if not serialized_value:
            return
        try:
            payload = json.loads(serialized_value)
        except json.JSONDecodeError:
            return

        self.records = [MergeRecord.from_dict(item) for item in payload if isinstance(item, dict)]
        self.records = self.records[: self._max_records]
        self._refresh()

    def serialize_records(self) -> str:
        return json.dumps([record.to_dict() for record in self.records[: self._max_records]])

    def record_success(self, output_path: str) -> None:
        file_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        record = MergeRecord(
            output_path=output_path,
            created_at_iso=QDateTime.currentDateTime().toString(Qt.ISODate),
            file_size_bytes=file_size,
        )
        self.records.insert(0, record)
        self.records = self.records[: self._max_records]
        self._refresh()

    def clear_history(self) -> None:
        self.records.clear()
        self.hide_overlay()
        self._refresh()

    def toggle_for_button(self, anchor_button: QWidget) -> None:
        if self.isVisible():
            self.hide_overlay()
        else:
            self.show_for_button(anchor_button)

    def show_for_button(self, anchor_button: QWidget) -> None:
        if not self.records:
            return
        self._anchor_button = anchor_button
        self._refresh()
        self._reposition()
        self.show()
        self.raise_()
        self.activateWindow()

    def reposition_to_anchor(self) -> None:
        if self.isVisible():
            self._reposition()

    def hide_overlay(self) -> None:
        self.hide()
        self.state_changed.emit()

    def record_count(self) -> int:
        return len(self.records)

    def _refresh(self) -> None:
        self.count_badge.setText(str(len(self.records)))
        self._clear_layout(self.history_layout)

        if not self.records:
            self.history_scroll.hide()
            self.clear_button.hide()
            self.count_badge.hide()
            self.state_changed.emit()
            return

        self.clear_button.show()
        self.count_badge.show()
        self.history_scroll.show()
        for record in self.records:
            history_widget = MergeHistoryItemWidget(record)
            history_widget.open_pdf_requested.connect(self.open_pdf_requested.emit)
            history_widget.open_folder_requested.connect(self.open_folder_requested.emit)
            self.history_layout.addWidget(history_widget)
        self.history_layout.addStretch()

        self.adjustSize()
        self.state_changed.emit()

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _reposition(self) -> None:
        if self._anchor_button is None:
            return

        screen = self._anchor_button.screen()
        if screen is None:
            return

        self.adjustSize()
        screen_rect = screen.availableGeometry()
        button_bottom_left = self._anchor_button.mapToGlobal(QPoint(0, self._anchor_button.height() + 8))
        x = button_bottom_left.x()
        y = button_bottom_left.y()

        if x + self.width() > screen_rect.right() - 12:
            x = screen_rect.right() - self.width() - 12
        if y + self.height() > screen_rect.bottom() - 12:
            y = self._anchor_button.mapToGlobal(QPoint(0, -self.height() - 8)).y()
        if x < screen_rect.left() + 12:
            x = screen_rect.left() + 12
        if y < screen_rect.top() + 12:
            y = screen_rect.top() + 12

        self.move(x, y)

    def hideEvent(self, event) -> None:  # noqa: ANN001
        super().hideEvent(event)
        self.state_changed.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("maxsc", "pdf-combiner")
        self.thread_pool = QThreadPool.globalInstance()
        self.item_lookup: dict[str, QListWidgetItem] = {}
        self.preview_tasks: dict[str, PreviewTask] = {}
        self.thumbnail_width = int(self.settings.value("ui/thumbnail_width", 170))
        self.theme_mode = str(self.settings.value("ui/theme_mode", "system"))
        self.merge_worker: MergeWorker | None = None
        self.preview_overlay = HoverPreviewOverlay()

        self.setWindowTitle("PDF Combiner")
        self.setMinimumSize(920, 700)
        self.resize(1160, 840)

        self._build_ui()
        self.merge_overlay.load_records(str(self.settings.value("merge/history", "")))
        self._apply_theme()
        self._restore_geometry()
        self._refresh_ui_state()
        QTimer.singleShot(0, self._sync_history_ui)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(22, 22, 22, 18)
        outer.setSpacing(16)

        self.header_frame = QFrame()
        self.header_frame.setObjectName("HeaderFrame")
        self.header_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(18)
        header_layout.setAlignment(Qt.AlignVCenter)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(4)
        title_column.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        title_label = QLabel("PDF Combiner")
        title_label.setObjectName("TitleLabel")
        title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        subtitle_label = QLabel("Add PDFs, drag them into the right order, then save one merged copy.")
        subtitle_label.setObjectName("SubtitleLabel")
        subtitle_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.summary_label = QLabel("No PDFs loaded yet.")
        self.summary_label.setObjectName("SummaryLabel")
        self.summary_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.summary_label.hide()

        title_column.addWidget(title_label, 0, Qt.AlignTop)
        title_column.addWidget(subtitle_label, 0, Qt.AlignTop)
        title_column.addWidget(self.summary_label, 0, Qt.AlignTop)

        controls_widget = QWidget()
        controls_widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        controls = QHBoxLayout(controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)

        self.add_button = QPushButton("Add PDFs")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self.choose_files)

        self.save_button = QPushButton("Save As...")
        self.save_button.setProperty("primary", True)
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.clicked.connect(self.save_as)

        self.clear_button = QPushButton("Clear all")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear_all)

        self.history_button = QPushButton("History")
        self.history_button.setCursor(Qt.PointingHandCursor)
        self.history_button.clicked.connect(self.toggle_history_overlay)
        self.history_button.hide()

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("System theme", "system")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self._set_theme_combo_value(self.theme_mode)

        controls.addWidget(self.add_button)
        controls.addWidget(self.clear_button)
        controls.addWidget(self.save_button)
        controls.addWidget(self.history_button)
        controls.addWidget(self.theme_combo)

        header_layout.addLayout(title_column, stretch=1)
        header_layout.addWidget(controls_widget, 0, Qt.AlignRight | Qt.AlignTop)

        self.duplicate_note = QLabel("Duplicate files are allowed and will be merged again wherever they appear in the list.")
        self.duplicate_note.setObjectName("WarningNote")
        self.duplicate_note.setVisible(False)

        self.drop_area = DropArea()
        self.drop_area.add_clicked.connect(self.choose_files)

        self.list_widget = PdfListWidget()
        self.list_widget.order_changed.connect(self._refresh_ui_state)
        self.list_widget.thumbnail_zoom_requested.connect(self.adjust_thumbnail_size)
        self.list_widget.files_dropped.connect(self.add_files)
        self.list_widget.file_drag_active_changed.connect(self.drop_area.set_drag_active)
        self.list_widget.verticalScrollBar().valueChanged.connect(self.preview_overlay.hide_preview)

        outer.addWidget(self.header_frame)
        outer.addWidget(self.duplicate_note)
        outer.addWidget(self.drop_area)
        outer.addWidget(self.list_widget, stretch=1)

        self.merge_overlay = MergeHistoryOverlay()
        self.merge_overlay.open_pdf_requested.connect(self.open_output_pdf)
        self.merge_overlay.open_folder_requested.connect(self.open_output_folder)
        self.merge_overlay.state_changed.connect(self._sync_history_ui)

        status_bar = QStatusBar()
        status_bar.setSizeGripEnabled(False)
        self.setStatusBar(status_bar)

        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("ProgressLabel")

        self.merge_status_text = QLabel("")
        self.merge_status_text.setObjectName("ProgressLabel")
        self.merge_status_text.hide()

        self.progress_indicator = QProgressBar()
        self.progress_indicator.setMinimumWidth(250)
        self.progress_indicator.hide()

        self.progress_widget = QWidget()
        progress_layout = QHBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)
        progress_layout.addWidget(self.progress_indicator)
        progress_layout.addWidget(self.merge_status_text)

        status_bar.addWidget(self.progress_label, 1)
        status_bar.addPermanentWidget(self.progress_widget)

        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self._event_has_pdf_urls(event):
            event.acceptProposedAction()
            self.drop_area.set_drag_active(True)
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._event_has_pdf_urls(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: ANN001
        self.drop_area.set_drag_active(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: ANN001
        self.drop_area.set_drag_active(False)
        paths = self._extract_pdf_paths(event)
        if not paths:
            event.ignore()
            return
        self.add_files(paths)
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.settings.setValue("ui/geometry", self.saveGeometry())
        self.settings.setValue("merge/history", self.merge_overlay.serialize_records())
        self.preview_overlay.hide_preview()
        self.merge_overlay.hide_overlay()
        self.thread_pool.waitForDone(5000)
        self.preview_tasks.clear()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self.merge_overlay.reposition_to_anchor()

    def moveEvent(self, event) -> None:  # noqa: ANN001
        super().moveEvent(event)
        self.merge_overlay.reposition_to_anchor()

    def choose_files(self) -> None:
        initial_dir = str(self.settings.value("paths/last_import_dir", desktop_path()))
        files, _filter = QFileDialog.getOpenFileNames(
            self,
            "Choose PDF files",
            initial_dir,
            "PDF files (*.pdf)",
        )
        if not files:
            return

        self.settings.setValue("paths/last_import_dir", str(Path(files[0]).resolve().parent))
        self.add_files(files)

    def add_files(self, paths: list[str]) -> None:
        added_any = False

        for raw_path in paths:
            file_path = str(Path(raw_path).expanduser().resolve())
            if Path(file_path).suffix.lower() != ".pdf" or not Path(file_path).is_file():
                continue

            file_size = Path(file_path).stat().st_size
            entry = PdfEntry(
                item_id=uuid.uuid4().hex,
                file_path=file_path,
                file_name=Path(file_path).name,
                file_size_bytes=file_size,
            )

            card = PdfCardWidget(entry, self.thumbnail_width)
            card.remove_requested.connect(self.remove_item)
            card.move_requested.connect(self.move_item)
            card.open_requested.connect(self.open_original_pdf)
            card.preview_requested.connect(self.show_preview_overlay)
            card.preview_hidden.connect(self.preview_overlay.hide_preview)

            item = QListWidgetItem()
            item.setData(Qt.UserRole, entry.item_id)
            item.setSizeHint(card.sizeHint())

            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)
            self.item_lookup[entry.item_id] = item
            added_any = True

            task = PreviewTask(entry.item_id, entry.file_path, max(320, self.thumbnail_width * 2))
            task.signals.loaded.connect(self.on_preview_loaded)
            task.signals.failed.connect(self.on_preview_failed)
            self.preview_tasks[entry.item_id] = task
            self.thread_pool.start(task)

        if not added_any:
            QMessageBox.warning(self, "No PDFs added", "Only existing PDF files can be added to the merge list.")
            return

        self._refresh_ui_state()

    def on_preview_loaded(self, item_id: str, page_count: int, image: QImage) -> None:
        self._discard_preview_task(item_id)
        card = self._card_for_item(item_id)
        if card is None:
            return
        card.set_page_count(page_count)
        card.set_preview(image)
        card.set_loading_state(False)
        self._update_item_size(item_id)
        self._refresh_ui_state()

    def on_preview_failed(self, item_id: str, error_message: str) -> None:
        self._discard_preview_task(item_id)
        card = self._card_for_item(item_id)
        if card is None:
            return
        card.set_loading_state(False, f"Could not load preview: {error_message}")
        self._refresh_ui_state()

    def move_item(self, item_id: str, offset: int) -> None:
        current_row = self._row_for_item(item_id)
        if current_row is None:
            return

        target_row = max(0, min(self.list_widget.count() - 1, current_row + offset))
        if target_row == current_row:
            return

        item = self.list_widget.item(current_row)
        widget = self.list_widget.itemWidget(item)
        if widget is not None:
            self.list_widget.removeItemWidget(item)

        item = self.list_widget.takeItem(current_row)
        self.list_widget.insertItem(target_row, item)
        if widget is not None:
            self.list_widget.setItemWidget(item, widget)
            item.setSizeHint(widget.sizeHint())
        self.list_widget.setCurrentItem(item)
        self._refresh_ui_state()

    def remove_item(self, item_id: str) -> None:
        row = self._row_for_item(item_id)
        if row is None:
            return

        item = self.list_widget.item(row)
        widget = self.list_widget.itemWidget(item)
        if widget is not None:
            self.list_widget.removeItemWidget(item)
            widget.deleteLater()

        item = self.list_widget.takeItem(row)
        self.item_lookup.pop(item_id, None)
        del item
        self._refresh_ui_state()

    def clear_all(self) -> None:
        self.preview_overlay.hide_preview()
        self.merge_overlay.hide_overlay()
        self.list_widget.clear()
        self.item_lookup.clear()
        self._refresh_ui_state()

    def save_as(self) -> None:
        if not self._can_save():
            return

        initial_dir = str(self.settings.value("paths/last_save_dir", desktop_path()))
        suggested_path = str(Path(initial_dir) / "merged.pdf")
        output_path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save merged PDF",
            suggested_path,
            "PDF files (*.pdf)",
        )
        if not output_path:
            return

        if Path(output_path).suffix.lower() != ".pdf":
            output_path = f"{output_path}.pdf"

        self.settings.setValue("paths/last_save_dir", str(Path(output_path).resolve().parent))
        self.start_merge(output_path)

    def start_merge(self, output_path: str) -> None:
        file_paths = [self._card_at(row).entry.file_path for row in range(self.list_widget.count())]
        self.merge_worker = MergeWorker(file_paths, output_path)
        self.merge_worker.progress.connect(self.on_merge_progress)
        self.merge_worker.succeeded.connect(self.on_merge_succeeded)
        self.merge_worker.failed.connect(self.on_merge_failed)
        self.merge_worker.finished.connect(self.on_merge_finished)

        self.progress_label.setText("Merging PDFs...")
        self.progress_indicator.setValue(0)
        self.progress_indicator.setMaximum(max(len(file_paths), 1))
        self.progress_indicator.show()
        self.merge_status_text.setText("Preparing merge...")
        self.merge_status_text.show()
        self._set_controls_enabled(False)
        self.merge_worker.start()

    def on_merge_progress(self, current: int, total: int, status_text: str) -> None:
        self.progress_indicator.setMaximum(max(total, 1))
        self.progress_indicator.setValue(current)
        self.merge_status_text.setText(status_text)

    def on_merge_succeeded(self, output_path: str) -> None:
        self.progress_label.setText("Merge complete.")
        self.merge_overlay.record_success(output_path)
        self.settings.setValue("merge/history", self.merge_overlay.serialize_records())
        self._sync_history_ui()
        self.merge_overlay.show_for_button(self.history_button)

    def on_merge_failed(self, error_message: str) -> None:
        self.progress_label.setText("Merge failed.")
        QMessageBox.critical(self, "Merge failed", error_message)

    def on_merge_finished(self) -> None:
        self.progress_indicator.hide()
        self.merge_status_text.hide()
        self._set_controls_enabled(True)
        self.merge_worker = None
        self._refresh_ui_state()

    def open_original_pdf(self, file_path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

    def open_output_pdf(self, output_path: str) -> None:
        self.merge_overlay.hide_overlay()
        QDesktopServices.openUrl(QUrl.fromLocalFile(output_path))

    def open_output_folder(self, output_path: str) -> None:
        self.merge_overlay.hide_overlay()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(output_path).resolve().parent)))

    def show_preview_overlay(self, image: QImage, source_widget: QWidget) -> None:
        self.preview_overlay.show_preview(image, source_widget)

    def adjust_thumbnail_size(self, direction: int) -> None:
        next_width = max(88, min(260, self.thumbnail_width + (direction * 16)))
        if next_width == self.thumbnail_width:
            return

        self.thumbnail_width = next_width
        self.settings.setValue("ui/thumbnail_width", self.thumbnail_width)

        for row in range(self.list_widget.count()):
            card = self._card_at(row)
            card.set_preview_width(self.thumbnail_width)
            self.list_widget.item(row).setSizeHint(card.sizeHint())

    def _refresh_ui_state(self) -> None:
        self._refresh_orders()
        duplicate_count = self._refresh_duplicates()
        self.duplicate_note.setVisible(duplicate_count > 0)

        item_count = self.list_widget.count()
        has_invalid = any(self._card_at(row).entry.error_message for row in range(item_count))
        loading_count = sum(1 for row in range(item_count) if self._card_at(row).entry.is_loading)

        self.drop_area.set_item_count(item_count)
        self.list_widget.setVisible(item_count > 0)
        self.clear_button.setEnabled(item_count > 0 and self.merge_worker is None)
        self.add_button.setEnabled(self.merge_worker is None)
        self.save_button.setEnabled(self._can_save())
        self.summary_label.setVisible(item_count > 0)

        if item_count == 0:
            self.summary_label.setText("")
        else:
            summary_parts = [f"{item_count} PDF{'s' if item_count != 1 else ''} in the merge list"]
            if loading_count:
                summary_parts.append(f"{loading_count} loading")
            if has_invalid:
                summary_parts.append("fix or remove invalid files before saving")
            self.summary_label.setText("  |  ".join(summary_parts))

        self.progress_label.setText("Ready" if self.merge_worker is None else "Merging PDFs...")
        self._sync_history_ui()

    def _refresh_orders(self) -> None:
        for row in range(self.list_widget.count()):
            self._card_at(row).set_order_index(row + 1)

    def _refresh_duplicates(self) -> int:
        counts: dict[str, int] = {}
        for row in range(self.list_widget.count()):
            key = normalize_path(self._card_at(row).entry.file_path)
            counts[key] = counts.get(key, 0) + 1

        duplicate_count = 0
        for row in range(self.list_widget.count()):
            card = self._card_at(row)
            is_duplicate = counts[normalize_path(card.entry.file_path)] > 1
            card.set_duplicate(is_duplicate)
            if is_duplicate:
                duplicate_count += 1

        return duplicate_count

    def _can_save(self) -> bool:
        if self.merge_worker is not None or self.list_widget.count() == 0:
            return False
        for row in range(self.list_widget.count()):
            entry = self._card_at(row).entry
            if entry.is_loading or entry.error_message:
                return False
        return True

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.add_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled and self.list_widget.count() > 0)
        self.save_button.setEnabled(enabled and self._can_save())
        self.theme_combo.setEnabled(enabled)
        self.drop_area.add_button.setEnabled(enabled)
        self.drop_area.compact_add_button.setEnabled(enabled)
        self.history_button.setEnabled(enabled and self.merge_overlay.record_count() > 0)
        self.list_widget.setEnabled(enabled)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        spec = theme_spec(self.theme_mode)
        app.setPalette(build_palette(spec))
        app.setStyleSheet(build_stylesheet(spec))

    def _on_theme_changed(self) -> None:
        self.theme_mode = str(self.theme_combo.currentData())
        self.settings.setValue("ui/theme_mode", self.theme_mode)
        self._apply_theme()

    def _set_theme_combo_value(self, theme_mode: str) -> None:
        for index in range(self.theme_combo.count()):
            if self.theme_combo.itemData(index) == theme_mode:
                self.theme_combo.setCurrentIndex(index)
                break

    def _restore_geometry(self) -> None:
        geometry = self.settings.value("ui/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def toggle_history_overlay(self) -> None:
        self.merge_overlay.toggle_for_button(self.history_button)
        self._sync_history_ui()

    def _sync_history_ui(self) -> None:
        history_count = self.merge_overlay.record_count()
        self.history_button.setVisible(history_count > 0)
        self.history_button.setEnabled(history_count > 0)
        if history_count > 0:
            self.history_button.setText(f"History ({history_count})")
        else:
            self.history_button.setText("History")
        self.settings.setValue("merge/history", self.merge_overlay.serialize_records())
        self.merge_overlay.reposition_to_anchor()

    def _discard_preview_task(self, item_id: str) -> None:
        self.preview_tasks.pop(item_id, None)

    def _event_has_pdf_urls(self, event) -> bool:  # noqa: ANN001
        return bool(extract_pdf_paths_from_mime_data(event.mimeData()))

    def _extract_pdf_paths(self, event) -> list[str]:  # noqa: ANN001
        return extract_pdf_paths_from_mime_data(event.mimeData())

    def _card_for_item(self, item_id: str) -> PdfCardWidget | None:
        item = self.item_lookup.get(item_id)
        if item is None:
            return None
        widget = self.list_widget.itemWidget(item)
        return widget if isinstance(widget, PdfCardWidget) else None

    def _row_for_item(self, item_id: str) -> int | None:
        item = self.item_lookup.get(item_id)
        if item is None:
            return None
        row = self.list_widget.row(item)
        return row if row >= 0 else None

    def _card_at(self, row: int) -> PdfCardWidget:
        item = self.list_widget.item(row)
        widget = self.list_widget.itemWidget(item)
        assert isinstance(widget, PdfCardWidget)
        return widget

    def _update_item_size(self, item_id: str) -> None:
        item = self.item_lookup.get(item_id)
        if item is None:
            return
        card = self._card_for_item(item_id)
        if card is None:
            return
        item.setSizeHint(card.sizeHint())


def run() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("maxsc")
    app.setApplicationName("PDF Combiner")

    window = MainWindow()
    window.show()
    return app.exec()
