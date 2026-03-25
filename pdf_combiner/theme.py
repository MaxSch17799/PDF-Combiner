from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette


@dataclass(frozen=True)
class ThemeSpec:
    window: str
    surface: str
    surface_alt: str
    text: str
    text_muted: str
    border: str
    accent: str
    accent_hover: str
    accent_pressed: str
    success_bg: str
    success_border: str
    warning_bg: str
    warning_border: str
    selection: str
    shadow: str


LIGHT_THEME = ThemeSpec(
    window="#eef3f4",
    surface="#ffffff",
    surface_alt="#f6f8f8",
    text="#182329",
    text_muted="#607078",
    border="#d6e0e3",
    accent="#177e6a",
    accent_hover="#146e5d",
    accent_pressed="#0f594b",
    success_bg="#e7f6f1",
    success_border="#96d6bf",
    warning_bg="#fff6e5",
    warning_border="#f1c26b",
    selection="#dcefe9",
    shadow="rgba(24, 35, 41, 0.08)",
)


DARK_THEME = ThemeSpec(
    window="#11171b",
    surface="#192126",
    surface_alt="#222d34",
    text="#f1f5f6",
    text_muted="#a7b6bd",
    border="#334047",
    accent="#44b594",
    accent_hover="#54c6a4",
    accent_pressed="#30997b",
    success_bg="#13362c",
    success_border="#2e7b62",
    warning_bg="#3b2d14",
    warning_border="#9d7531",
    selection="#20362f",
    shadow="rgba(0, 0, 0, 0.28)",
)


def resolve_theme_mode(mode: str) -> str:
    if mode != "system":
        return mode

    color_scheme = QGuiApplication.styleHints().colorScheme()
    if color_scheme == Qt.ColorScheme.Dark:
        return "dark"
    return "light"


def theme_spec(mode: str) -> ThemeSpec:
    return DARK_THEME if resolve_theme_mode(mode) == "dark" else LIGHT_THEME


def build_palette(spec: ThemeSpec) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(spec.window))
    palette.setColor(QPalette.WindowText, QColor(spec.text))
    palette.setColor(QPalette.Base, QColor(spec.surface))
    palette.setColor(QPalette.AlternateBase, QColor(spec.surface_alt))
    palette.setColor(QPalette.ToolTipBase, QColor(spec.surface))
    palette.setColor(QPalette.ToolTipText, QColor(spec.text))
    palette.setColor(QPalette.Text, QColor(spec.text))
    palette.setColor(QPalette.Button, QColor(spec.surface))
    palette.setColor(QPalette.ButtonText, QColor(spec.text))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor(spec.accent))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.Link, QColor(spec.accent))
    return palette


def build_stylesheet(spec: ThemeSpec) -> str:
    return f"""
    QWidget {{
        color: {spec.text};
        font-size: 10.5pt;
    }}

    QMainWindow {{
        background: {spec.window};
    }}

    QLabel#TitleLabel {{
        font-size: 20pt;
        font-weight: 700;
        color: {spec.text};
    }}

    QLabel#SubtitleLabel,
    QLabel#SummaryLabel,
    QLabel#HintLabel,
    QLabel#MetaLabel,
    QLabel#ProgressLabel {{
        color: {spec.text_muted};
    }}

    QFrame#HeaderFrame,
    QFrame#DropArea,
    QFrame#CardFrame,
    QFrame#MergeOverlay,
    QFrame#PreviewOverlay {{
        background: {spec.surface};
        border: 1px solid {spec.border};
        border-radius: 18px;
    }}

    QFrame#DropArea[compact="true"] {{
        border-style: dashed;
        background: {spec.surface_alt};
    }}

    QFrame#DropArea[dragActive="true"] {{
        border: 2px dashed {spec.accent};
        background: {spec.selection};
    }}

    QLabel#DropTitle {{
        font-size: 16pt;
        font-weight: 650;
    }}

    QLabel#CompactDropTitle {{
        font-size: 12pt;
        font-weight: 650;
    }}

    QLabel#BadgeLabel {{
        background: {spec.warning_bg};
        border: 1px solid {spec.warning_border};
        border-radius: 10px;
        color: {spec.text};
        font-size: 9pt;
        font-weight: 700;
        padding: 2px 8px;
    }}

    QLabel#OrderBadge {{
        background: {spec.selection};
        border-radius: 12px;
        color: {spec.text};
        font-size: 9pt;
        font-weight: 700;
        padding: 4px 8px;
    }}

    QLabel#CardTitle {{
        font-size: 12pt;
        font-weight: 650;
    }}

    QLabel#StatusLabel {{
        color: {spec.text_muted};
    }}

    QLabel#StatusLabel[error="true"] {{
        color: #d44242;
        font-weight: 600;
    }}

    QLabel#PreviewLabel {{
        background: {spec.surface_alt};
        border: 1px solid {spec.border};
        border-radius: 14px;
    }}

    QFrame#MergeHistoryItem {{
        background: {spec.surface_alt};
        border: 1px solid {spec.border};
        border-radius: 14px;
    }}

    QFrame#DragPlaceholder {{
        background: {spec.selection};
        border: 2px dashed {spec.accent};
        border-radius: 18px;
    }}

    QLabel#OverlayTitle,
    QLabel#HistoryTitle {{
        font-weight: 700;
        font-size: 11pt;
    }}

    QLabel#HistoryMeta {{
        color: {spec.text_muted};
    }}

    QLabel#WarningNote {{
        background: {spec.warning_bg};
        border: 1px solid {spec.warning_border};
        border-radius: 12px;
        padding: 8px 12px;
        color: {spec.text};
    }}

    QListWidget {{
        background: transparent;
        border: none;
        outline: none;
    }}

    QScrollArea {{
        background: transparent;
        border: none;
    }}

    QListWidget::item {{
        border: none;
        margin: 0px;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 14px;
        margin: 6px 0px;
    }}

    QScrollBar::handle:vertical {{
        background: {spec.border};
        border-radius: 7px;
        min-height: 40px;
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
        border: none;
        height: 0px;
    }}

    QPushButton,
    QToolButton,
    QComboBox {{
        background: {spec.surface};
        border: 1px solid {spec.border};
        border-radius: 12px;
        padding: 9px 14px;
    }}

    QPushButton:hover,
    QToolButton:hover,
    QComboBox:hover {{
        border-color: {spec.accent};
    }}

    QPushButton:disabled,
    QToolButton:disabled,
    QComboBox:disabled {{
        color: {spec.text_muted};
        border-color: {spec.border};
        background: {spec.surface_alt};
    }}

    QPushButton[primary="true"] {{
        background: {spec.accent};
        color: white;
        border-color: {spec.accent};
        font-weight: 700;
    }}

    QPushButton[primary="true"]:hover {{
        background: {spec.accent_hover};
        border-color: {spec.accent_hover};
    }}

    QPushButton[primary="true"]:pressed {{
        background: {spec.accent_pressed};
        border-color: {spec.accent_pressed};
    }}

    QPushButton[danger="true"] {{
        background: transparent;
    }}

    QProgressBar {{
        min-width: 220px;
        background: {spec.surface_alt};
        border: 1px solid {spec.border};
        border-radius: 9px;
        text-align: center;
        padding: 1px;
    }}

    QProgressBar::chunk {{
        background: {spec.accent};
        border-radius: 7px;
    }}

    QMenu {{
        background: {spec.surface};
        border: 1px solid {spec.border};
        padding: 8px;
    }}

    QMenu::item {{
        padding: 8px 20px;
        border-radius: 8px;
    }}

    QMenu::item:selected {{
        background: {spec.selection};
    }}
    """
