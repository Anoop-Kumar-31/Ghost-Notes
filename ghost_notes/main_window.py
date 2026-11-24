"""
Main notes window for Ghost Notes.
Frameless, translucent, always-on-top window supporting multiple notes,
home page with responsive grid / list view, note editing with distinct title line,
and a bottom-left Home button.
"""
import re
import uuid
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any
from PySide6.QtCore import Qt, QPoint, QRect, QTimer, QSize, Signal, QEvent
from PySide6.QtGui import (
    QGuiApplication,
    QKeySequence,
    QShortcut,
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
    QIcon,
    QPixmap,
    QCursor,
    QTextTable,
    QTextCursor,
    QTextCharFormat,
    QTextBlockFormat,
    QTextListFormat,
    QTextTableFormat,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QMessageBox,
    QFrame,
    QStackedWidget,
    QScrollArea,
    QPushButton,
    QToolButton,
    QComboBox,
    QSpinBox,
    QColorDialog,
    QInputDialog,
    QMenu,
)
from markdown_it import MarkdownIt

from .controls import ControlsWindow
from .platform_utils import set_click_through, exclude_from_taskbar, set_capture_excluded
from .persistence import (
    load_data,
    save_data,
    sanitize_geometry,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
)

def scale_stylesheet(stylesheet: str, scale: float) -> str:
    """Scale all explicit px and pt font sizes in a Qt stylesheet."""

    def replace_size(match):
        original = float(match.group(2))
        unit = match.group(3)

        new_size = max(6, round(original * scale))

        return f"{match.group(1)}{new_size}{unit}"

    return re.sub(
        r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(px|pt)",
        replace_size,
        stylesheet,
        flags=re.IGNORECASE,
    )

def derive_note_title(content: str) -> str:
    """Derive a friendly title from the first non-empty line of content."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if lines:
        first = lines[0].lstrip("•-*# ").strip()
        if len(first) > 24:
            return first[:22] + "..."
        return first or "Untitled Note"
    return "Untitled Note"


class NoIBeamLineEdit(QLineEdit):
    """QLineEdit that strictly preserves the standard ArrowCursor."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)



class NoIBeamTextEdit(QTextEdit):
    """
    QTextEdit that strictly preserves the standard ArrowCursor.
    Prevents the text editor viewport from showing an I-beam cursor.
    Supports interactive + dot controls on table hover to add rows/columns.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        self.md = MarkdownIt("default").enable([ "table", "strikethrough"  ])

        # Enable mouse tracking on viewport to detect table hover
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)

        # Floating + dot button for adding rows/columns to tables
        self.table_add_btn = QToolButton(self.viewport())
        self.table_add_btn.setText("+")
        self.table_add_btn.setFixedSize(10, 10)
        self.table_add_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.table_add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table_add_btn.setStyleSheet("""
            QToolButton {
                color: #000000;
                background-color: #7590bd;
                border: 0.5px solid rgba(255, 255, 255, 0.45);
                border-radius: 100%;
                font-size: 8px;
                font-weight: bold;
                padding: 0px;
            }
            QToolButton:hover {
                background-color: #60a5fa;
                border-color: #ffffff;
            }
        """)
        self.table_add_btn.hide()
        self._current_table_action = None
        self.table_add_btn.clicked.connect(self._on_table_add_clicked)

        self.verticalScrollBar().valueChanged.connect(self._on_editor_scrolled)
        self.horizontalScrollBar().valueChanged.connect(self._on_editor_scrolled)

    def _on_table_add_clicked(self):
        if self._current_table_action:
            action = self._current_table_action
            self._current_table_action = None
            self.table_add_btn.hide()
            action()

    def _on_editor_scrolled(self):
        if self.table_add_btn.isVisible():
            self._update_table_add_hover(self.viewport().mapFromGlobal(QCursor.pos()))

    def eventFilter(self, watched, event):
        if watched == self.viewport():
            if event.type() == QEvent.Type.MouseMove:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                self._update_table_add_hover(event.pos())
            elif event.type() == QEvent.Type.Leave:
                if not self.table_add_btn.underMouse():
                    self.table_add_btn.hide()
                    self._current_table_action = None
        return super().eventFilter(watched, event)

    def _update_table_add_hover(self, pos):
        # Keep button visible if mouse is hovering directly on the button or within 4px of it
        if self.table_add_btn.isVisible() and self.table_add_btn.geometry().adjusted(-4, -4, 4, 4).contains(pos):
            return

        doc = self.document()
        if not doc:
            self.table_add_btn.hide()
            return

        doc_layout = doc.documentLayout()
        root = doc.rootFrame()
        if not root:
            self.table_add_btn.hide()
            return

        tables = []
        def _collect(frame):
            for child in frame.childFrames():
                if isinstance(child, QTextTable):
                    tables.append(child)
                _collect(child)
        _collect(root)

        if not tables:
            self.table_add_btn.hide()
            self._current_table_action = None
            return

        scroll_x = self.horizontalScrollBar().value()
        scroll_y = self.verticalScrollBar().value()
        px = pos.x()
        py = pos.y()

        hit_threshold = 14

        for tbl in tables:
            f_rect = doc_layout.frameBoundingRect(tbl)
            vx = f_rect.x() - scroll_x
            vy = f_rect.y() - scroll_y
            vw = f_rect.width()
            vh = f_rect.height()

            # Fast boundary check around this table (expanded by 20px)
            if not (vx - 20 <= px <= vx + vw + 20 and vy - 20 <= py <= vy + vh + 20):
                continue

            # 1. Top border: add row at top
            if abs(py - vy) <= hit_threshold and (vx - 6 <= px <= vx + vw + 6):
                self.table_add_btn.move(int(vx + vw / 2 - 8), int(max(2, vy - 8)))
                self._current_table_action = lambda t=tbl: self._add_table_row(t, 0)
                self.table_add_btn.setToolTip("Add row at top")
                self.table_add_btn.show()
                self.table_add_btn.raise_()
                return

            # 2. Bottom border: add row at bottom
            if abs(py - (vy + vh)) <= hit_threshold and (vx - 6 <= px <= vx + vw + 6):
                self.table_add_btn.move(int(vx + vw / 2 - 8), int(min(self.viewport().height() - 18, vy + vh - 8)))
                self._current_table_action = lambda t=tbl: self._add_table_row(t, t.rows())
                self.table_add_btn.setToolTip("Add row at bottom")
                self.table_add_btn.show()
                self.table_add_btn.raise_()
                return

            # 3. Left border: add column at left
            if abs(px - vx) <= hit_threshold and (vy - 6 <= py <= vy + vh + 6):
                self.table_add_btn.move(int(max(2, vx - 8)), int(vy + vh / 2 - 8))
                self._current_table_action = lambda t=tbl: self._add_table_column(t, 0)
                self.table_add_btn.setToolTip("Add column at left")
                self.table_add_btn.show()
                self.table_add_btn.raise_()
                return

            # 4. Right border: add column at right
            if abs(px - (vx + vw)) <= hit_threshold and (vy - 6 <= py <= vy + vh + 6):
                self.table_add_btn.move(int(min(self.viewport().width() - 18, vx + vw - 8)), int(vy + vh / 2 - 8))
                self._current_table_action = lambda t=tbl: self._add_table_column(t, t.columns())
                self.table_add_btn.setToolTip("Add column at right")
                self.table_add_btn.show()
                self.table_add_btn.raise_()
                return

        self.table_add_btn.hide()
        self._current_table_action = None

    def _add_table_row(self, table, index):
        cursor = self.textCursor()
        cursor.beginEditBlock()
        table.insertRows(index, 1)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.setFocus()
        self.textChanged.emit()

    def _add_table_column(self, table, index):
        cursor = self.textCursor()
        cursor.beginEditBlock()
        table.insertColumns(index, 1)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.setFocus()
        self.textChanged.emit()

    def insertFromMimeData(self, source):

        # 1. If clipboard contains HTML, preserve rich formatting
        if source.hasHtml():
            super().insertFromMimeData(source)
            return

        # 2. If clipboard contains plain text, parse as Markdown
        if source.hasText():
            text = source.text()
            html = self.md.render(text)

            cursor = self.textCursor()
            cursor.insertHtml(html)
            self.setTextCursor(cursor)

            self.ensureCursorVisible()
            return

        # 3. Fallback
        super().insertFromMimeData(source)


    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)


class ResizeGrip(QWidget):
    """Bottom-right resize grip maintaining the standard ArrowCursor."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(160, 160, 160, 120), 1.5))
        painter.drawLine(10, 4, 10, 4)
        painter.drawLine(6, 8, 10, 8)
        painter.drawLine(2, 12, 10, 12)

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)


class NoteCard(QFrame):
    """
    Clickable note card component for the Grid and List views.
    Shows note title, preview snippet, and delete button.
    Strictly preserves Qt.CursorShape.ArrowCursor.
    """

    clicked = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, note: Dict[str, Any], is_list_view: bool = False, parent: Optional[QWidget] = None, ui_scale: float=1.0):
        super().__init__(parent)
        self.note_id = str(note.get("id", ""))
        self.is_list_view = is_list_view
        self.setCursor(Qt.CursorShape.ArrowCursor)

        title = str(note.get("title") or derive_note_title(note.get("content", "")))
        content = str(note.get("content", ""))
        date_str = str(note.get("updated_at", ""))

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        snippet = "Empty note"
        if len(lines) > 1:
            snippet = " ".join(lines[1:3])
        elif lines:
            snippet = lines[0]
        if len(snippet) > 60:
            snippet = snippet[:57] + "..."

        self.setStyleSheet(
            scale_stylesheet("""
            QFrame#NoteCard {
                background-color: rgba(39, 39, 42, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            QFrame#NoteCard:hover {
                background-color: rgba(59, 130, 246, 0.15);
                border: 1px solid rgba(59, 130, 246, 0.4);
            }
            """, ui_scale)
        )
        self.setObjectName("NoteCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header row: Title + Delete button
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        self.title_lbl = QLabel(title, self)
        self.title_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self.title_lbl.setStyleSheet(scale_stylesheet("color: #f4f4f5; font-size: 11px; font-weight: 700; background: transparent;", ui_scale))
        top_row.addWidget(self.title_lbl)
        top_row.addStretch()

        self.del_btn = QPushButton("×", self)
        self.del_btn.setFixedSize(16, 16)
        self.del_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.del_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.del_btn.setStyleSheet(
            """
            QPushButton {
                color: #71717a;
                background: transparent;
                border: none;
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                color: #ef4444;
            }
            """
        )
        self.del_btn.clicked.connect(self._on_delete_clicked)
        top_row.addWidget(self.del_btn)
        layout.addLayout(top_row)

        # Snippet preview
        self.snippet_lbl = QLabel(snippet, self)
        self.snippet_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self.snippet_lbl.setWordWrap(True)
        self.snippet_lbl.setStyleSheet(scale_stylesheet("color: #a1a1aa; font-size: 10px; background: transparent;", ui_scale))
        layout.addWidget(self.snippet_lbl)

        # Footer row: Date
        if date_str:
            self.date_lbl = QLabel(date_str, self)
            self.date_lbl.setCursor(Qt.CursorShape.ArrowCursor)
            self.date_lbl.setStyleSheet(scale_stylesheet("color: #71717a; font-size: 9px; background: transparent;", ui_scale))
            layout.addWidget(self.date_lbl)

        if not is_list_view:
            self.setMinimumHeight(80)
            self.setMaximumHeight(110)
        else:
            self.setMinimumHeight(44)
            self.setMaximumHeight(65)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.note_id)
        super().mousePressEvent(event)

    def _on_delete_clicked(self) -> None:
        self.delete_requested.emit(self.note_id)


class MainWindow(QWidget):
    """
    Frameless, floating, always-on-top notes window.
    Features:
    - Home Page: responsive Grid / List preview of multiple notes.
    - Note Detail Page: distinct title line at top, text editor, and bottom-left Home button.
    - True Win32 / macOS Ghost Mode click-through.
    """

    def __init__(self):
        super().__init__()

        self._ghost_mode = False
        self._is_dragging = False
        self._is_resizing = False
        self._drag_start_pos = QPoint()
        self._resize_start_pos = QPoint()
        self._resize_start_geom = QRect()

        self._ui_scale = 1.0

        # State
        self._notes: List[Dict[str, Any]] = []
        self._active_note_id: Optional[str] = None
        self._view_mode: str = "grid"  # "grid" or "list"
        self._current_cols: int = -1

        # Window Flags: Frameless, Tool, Always On Top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # Autosave debounce timer (500ms)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_state)

        # Build UI layout
        self._init_ui()

        self._base_stylesheet = self.styleSheet()

        # Keyboard shortcuts
        self._setup_shortcuts()

        # Independent controls window (Blue & Red micro-dots)
        self.controls = ControlsWindow()

        self.controls.toggle_ghost_requested.connect(self.toggle_ghost_mode)
        self.controls.close_requested.connect(self.close_application)
        self.controls.zoom_in_requested.connect(lambda: self._change_ui_scale(0.1))
        self.controls.zoom_out_requested.connect(lambda: self._change_ui_scale(-0.1))

        # Load persisted data
        self._load_state()

    def _init_ui(self) -> None:
        self.setObjectName("GhostNotesRoot")

        self.container = QFrame(self)
        self.container.setObjectName("Container")
        self.container.setCursor(Qt.CursorShape.ArrowCursor)

        self.setStyleSheet(
            """
            #Container {
                background-color: rgba(24, 24, 27, 245);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 10px;
            }
            QLabel#TitleLabel {
                color: #a1a1aa;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1.2px;
            }
            QLabel#SubtitleLabel {
                color: #71717a;
                font-size: 10px;
                font-weight: 500;
            }
            QPushButton.HeaderActionBtn {
                color: #a1a1aa;
                background-color: rgba(255, 255, 255, 12);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 4px;
                font-size: 11px;
                padding: 2px 7px;
                font-weight: 600;
            }
            QPushButton.HeaderActionBtn:hover {
                color: #ffffff;
                background-color: rgba(59, 130, 246, 0.3);
                border: 1px solid rgba(59, 130, 246, 0.5);
            }
            QPushButton#HomeBtn {
                color: #a1a1aa;
                background-color: rgba(255, 255, 255, 10);
                border: 1px solid rgba(255, 255, 255, 18);
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
            }
            QPushButton#HomeBtn:hover {
                color: #ffffff;
                background-color: rgba(59, 130, 246, 0.25);
                border: 1px solid rgba(59, 130, 246, 0.5);
            }
            QLineEdit#NoteTitleInput {
                background-color: transparent;
                border: none;
                border-bottom: 1px solid rgba(255, 255, 255, 0.15);
                color: #ffffff;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                font-size: 14px;
                font-weight: 700;
                padding: 2px 4px 6px 4px;
                margin-bottom: 4px;
                selection-background-color: #3b82f6;
                selection-color: #ffffff;
            }
            QLineEdit#NoteTitleInput:focus {
                border-bottom: 1px solid rgba(59, 130, 246, 0.7);
            }
            QTextEdit {
                background-color: transparent;
                border: none;
                color: #f4f4f5;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                font-size: 13px;
                line-height: 1.4;
                selection-background-color: #3b82f6;
                selection-color: #ffffff;
                padding: 4px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.container)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(14, 10, 14, 10)
        container_layout.setSpacing(6)

        # --- Header Area ---
        self.header_widget = QWidget(self.container)
        self.header_widget.setCursor(Qt.CursorShape.ArrowCursor)
        header_layout = QHBoxLayout(self.header_widget)
        # 42px right margin leaves space for the independent blue & red micro-dots
        header_layout.setContentsMargins(0, 0, 42, 0)
        header_layout.setSpacing(8)

        # Left titles: Title + Subtitle
        titles_col = QVBoxLayout()
        titles_col.setContentsMargins(0, 0, 0, 0)
        titles_col.setSpacing(1)

        self.title_label = QLabel("GHOST NOTES", self.header_widget)
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setCursor(Qt.CursorShape.ArrowCursor)

        self.subtitle_label = QLabel("All notes", self.header_widget)
        self.subtitle_label.setObjectName("SubtitleLabel")
        self.subtitle_label.setCursor(Qt.CursorShape.ArrowCursor)

        titles_col.addWidget(self.title_label)
        titles_col.addWidget(self.subtitle_label)
        header_layout.addLayout(titles_col)
        header_layout.addStretch()

        # Header Action Controls (New Note & View Mode Toggle)
        self.header_actions = QWidget(self.header_widget)
        self.header_actions.setCursor(Qt.CursorShape.ArrowCursor)
        actions_layout = QHBoxLayout(self.header_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)

        # Toggle Grid / List
        self.toggle_view_btn = QPushButton("⊞", self.header_actions)
        self.toggle_view_btn.setObjectName("ToggleViewBtn")
        self.toggle_view_btn.setProperty("class", "HeaderActionBtn")
        self.toggle_view_btn.setToolTip("Toggle Grid / List view")
        self.toggle_view_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.toggle_view_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle_view_btn.clicked.connect(self._toggle_view_mode)
        actions_layout.addWidget(self.toggle_view_btn)

        # New Note Button
        self.new_note_btn = QPushButton("+ New", self.header_actions)
        self.new_note_btn.setObjectName("NewNoteBtn")
        self.new_note_btn.setProperty("class", "HeaderActionBtn")
        self.new_note_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.new_note_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.new_note_btn.clicked.connect(self.create_new_note)
        actions_layout.addWidget(self.new_note_btn)

        header_layout.addWidget(self.header_actions)
        container_layout.addWidget(self.header_widget)

        # --- Stacked Widget (Home View vs Note Detail View) ---
        self.stacked_widget = QStackedWidget(self.container)
        self.stacked_widget.setCursor(Qt.CursorShape.ArrowCursor)

        # Page 0: Home Page (Scroll Area for Grid / List preview)
        self.home_scroll = QScrollArea(self.stacked_widget)
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.home_scroll.setStyleSheet("background: transparent; border: none;")
        self.home_scroll.setCursor(Qt.CursorShape.ArrowCursor)
        self.home_scroll.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        self.home_content = QWidget()
        self.home_content.setStyleSheet("background: transparent;")
        self.home_content.setCursor(Qt.CursorShape.ArrowCursor)
        self.home_layout = QVBoxLayout(self.home_content)
        self.home_layout.setContentsMargins(0, 2, 0, 2)
        self.home_layout.setSpacing(6)
        self.home_scroll.setWidget(self.home_content)
        self.stacked_widget.addWidget(self.home_scroll)

        # Page 1: Note Detail View (Title Line + Multiline Text Editor)
        self.detail_widget = QWidget(self.stacked_widget)
        self.detail_widget.setCursor(Qt.CursorShape.ArrowCursor)
        detail_layout = QVBoxLayout(self.detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(2)

        # Title input field (larger font, distinct from the note below)
        self.title_input = NoIBeamLineEdit(self.detail_widget)
        self.title_input.setObjectName("NoteTitleInput")
        self.title_input.setPlaceholderText("Title (optional)...")
        self.title_input.textChanged.connect(self._on_text_changed)
        detail_layout.addWidget(self.title_input)

        self.editor = NoIBeamTextEdit(self.detail_widget)
        self.editor.setLineWrapMode( QTextEdit.LineWrapMode.WidgetWidth )
        self.editor.setAcceptRichText(True)
        self.editor.setPlaceholderText( "Type your notes here... (Ctrl+S to save, Ctrl+Shift+N to clear)" )
        self.editor.textChanged.connect(self._on_text_changed)

        # Editor expands to consume the available vertical space
        detail_layout.addWidget(self.editor, 1)

        # Formatting toolbar directly below the editor
        self._build_format_toolbar(detail_layout)
        self.stacked_widget.addWidget(self.detail_widget)

        container_layout.addWidget(self.stacked_widget)

        # Bottom row: Home Button (at bottom left) + Resize grip (at bottom right)
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)

        self.home_btn = QPushButton("⌂ Home", self.container)
        self.home_btn.setObjectName("HomeBtn")
        self.home_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.home_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.home_btn.clicked.connect(self.show_home_view)
        bottom_row.addWidget(self.home_btn)

        bottom_row.addStretch()

        self.resize_grip = ResizeGrip(self.container)
        bottom_row.addWidget(self.resize_grip)
        container_layout.addLayout(bottom_row)

    def _change_ui_scale(self, amount: float):
        """Increase/decrease application interface font scale."""

        self._ui_scale = round(
            max(0.8, min(1.4, self._ui_scale + amount)),
            2
        )

        self._apply_ui_scale()
        self._save_timer.start()


    def _apply_ui_scale(self):
        """Apply the saved font scale to application stylesheets."""

        self.setStyleSheet(
            scale_stylesheet(
                self._base_stylesheet,
                self._ui_scale
            )
        )

        if hasattr(self, "_toolbar_base_stylesheet"):
            self.format_toolbar.setStyleSheet(
                scale_stylesheet(
                    self._toolbar_base_stylesheet,
                    self._ui_scale
                )
            )

        # Refresh cards so their local font styles are also scaled
        if (
            hasattr(self, "stacked_widget")
            and self.stacked_widget.currentIndex() == 0
        ):
            self._render_notes_list()

    def _make_format_button(
        self,
        label: str,
        callback=None,
        checkable: bool = False,
        tooltip: str = "",
        width: int = 22,
    ) -> QToolButton:
        button = QToolButton(self.format_toolbar)
        button.setText(label)
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(width, 22)
        if tooltip:
            button.setToolTip(tooltip)
        if callback:
            button.clicked.connect(callback)
        return button

    def _make_toolbar_divider(self) -> QFrame:
        div = QFrame(self.format_toolbar)
        div.setFrameShape(QFrame.Shape.VLine)
        div.setFixedWidth(1)
        div.setFixedHeight(12)
        div.setStyleSheet("background-color: rgba(255, 255, 255, 0.12); border: none;")
        return div

    def _create_table_matrix_icon(self) -> QIcon:
        """Create a crisp 2x2 matrix icon composed of 4 squares."""
        def _render_pixmap(color_hex: str) -> QPixmap:
            pix = QPixmap(16, 16)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            pen = QPen(QColor(color_hex), 1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            # 4 distinct squares arranged in a 2x2 matrix
            p.drawRect(2, 2, 5, 5)
            p.drawRect(9, 2, 5, 5)
            p.drawRect(2, 9, 5, 5)
            p.drawRect(9, 9, 5, 5)
            p.end()
            return pix

        icon = QIcon()
        icon.addPixmap(_render_pixmap("#a1a1aa"), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(_render_pixmap("#60a5fa"), QIcon.Mode.Normal, QIcon.State.On)
        icon.addPixmap(_render_pixmap("#ffffff"), QIcon.Mode.Active)
        return icon

    def _build_format_toolbar(self, detail_layout):

        self.format_toolbar = QFrame(self.detail_widget)
        self.format_toolbar.setObjectName("FormatToolbar")

        outer = QVBoxLayout(self.format_toolbar)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(3)

        # ---------------- ROW 1: Paragraph, Font Family, Font Size ----------------

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(4)

        self.paragraph_combo = QComboBox(self.format_toolbar)
        self.paragraph_combo.addItems(["Normal", "Heading 1", "Heading 2", "Heading 3", "Quote"])
        self.paragraph_combo.setFixedWidth(82)
        self.paragraph_combo.setFixedHeight(22)
        self.paragraph_combo.setCursor(Qt.CursorShape.ArrowCursor)
        self.paragraph_combo.setToolTip("Paragraph style")
        self.paragraph_combo.currentTextChanged.connect(self._set_paragraph_style)

        self.font_combo = QComboBox(self.format_toolbar)
        self.font_combo.setEditable(False)
        self.font_combo.addItems(["Segoe UI", "Arial", "Consolas", "Times New Roman", "Georgia"])
        self.font_combo.setCurrentText("Segoe UI")
        self.font_combo.setFixedWidth(88)
        self.font_combo.setFixedHeight(22)
        self.font_combo.setCursor(Qt.CursorShape.ArrowCursor)
        self.font_combo.setToolTip("Font family")
        self.font_combo.currentTextChanged.connect(self._set_font_family)

        row1.addWidget(self.paragraph_combo)
        row1.addWidget(self.font_combo)
        row1.addWidget(self._make_toolbar_divider())

        # Size Stepper
        self.font_size_down = self._make_format_button(
            "−", lambda: self._adjust_font_size(-1), tooltip="Decrease font size", width=20
        )

        self.font_size_spin = QSpinBox(self.format_toolbar)
        self.font_size_spin.setRange(6, 72)
        self.font_size_spin.setValue(13)
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.font_size_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.font_size_spin.setFixedSize(48, 22)
        self.font_size_spin.setCursor(Qt.CursorShape.ArrowCursor)
        self.font_size_spin.setToolTip("Font size")
        self.font_size_spin.valueChanged.connect(self._set_font_size)

        self.font_size_up = self._make_format_button(
            "+", lambda: self._adjust_font_size(1), tooltip="Increase font size", width=20
        )

        row1.addWidget(self.font_size_down)
        row1.addWidget(self.font_size_spin)
        row1.addWidget(self.font_size_up)
        row1.addStretch()

        outer.addLayout(row1)

        # ---------------- ROW 2: Formatting buttons ----------------

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(2)

        self.bold_btn = self._make_format_button("B", self._toggle_bold, True, "Bold (Ctrl+B)")
        self.italic_btn = self._make_format_button("I", self._toggle_italic, True, "Italic (Ctrl+I)")
        self.underline_btn = self._make_format_button("U", self._toggle_underline, True, "Underline (Ctrl+U)")
        self.strike_btn = self._make_format_button("S", self._toggle_strike, True, "Strikethrough")

        for button in (self.bold_btn, self.italic_btn, self.underline_btn, self.strike_btn):
            row2.addWidget(button)

        row2.addWidget(self._make_toolbar_divider())

        self.bullet_btn = self._make_format_button(
            "•", lambda: self._insert_list(QTextListFormat.Style.ListDisc), checkable=True, tooltip="Bulleted list"
        )
        self.number_btn = self._make_format_button(
            "1.", lambda: self._insert_list(QTextListFormat.Style.ListDecimal), checkable=True, tooltip="Numbered list"
        )
        self.checklist_btn = self._make_format_button(
            "☑", self._insert_checklist_item, checkable=True, tooltip="Checklist item"
        )

        for button in (self.bullet_btn, self.number_btn, self.checklist_btn):
            row2.addWidget(button)

        row2.addWidget(self._make_toolbar_divider())

        self.table_btn = self._make_format_button("", self._insert_table, checkable=True, tooltip="Insert table")
        self.table_btn.setIcon(self._create_table_matrix_icon())
        self.table_btn.setIconSize(QSize(16, 16))
        self.code_btn = self._make_format_button("</>", self._insert_code_block, checkable=True, tooltip="Code block", width=24)

        row2.addWidget(self.table_btn)
        row2.addWidget(self.code_btn)

        row2.addWidget(self._make_toolbar_divider())

        self.more_btn = QToolButton(self.format_toolbar)
        self.more_btn.setText("⋯")
        self.more_btn.setToolTip("More formatting options")
        self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.more_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more_btn.setFixedSize(22, 22)

        self.more_menu = QMenu(self.more_btn)
        self.more_menu.setCursor(Qt.CursorShape.ArrowCursor)

        self.more_menu.addAction("Text colour...", self._choose_text_color)
        self.more_menu.addAction("Highlight colour...", self._choose_highlight_color)
        self.more_menu.addAction("Insert hyperlink...", self._insert_link)

        alignment_menu = self.more_menu.addMenu("Alignment")
        alignment_menu.setCursor(Qt.CursorShape.ArrowCursor)

        alignment_menu.addAction("Left", lambda: self.editor.setAlignment(Qt.AlignmentFlag.AlignLeft))
        alignment_menu.addAction("Centre", lambda: self.editor.setAlignment(Qt.AlignmentFlag.AlignHCenter))
        alignment_menu.addAction("Right", lambda: self.editor.setAlignment(Qt.AlignmentFlag.AlignRight))
        alignment_menu.addAction("Justify", lambda: self.editor.setAlignment(Qt.AlignmentFlag.AlignJustify))

        self.more_menu.addSeparator()
        self.more_menu.addAction("Insert horizontal divider", self._insert_horizontal_divider)
        self.more_menu.addAction("Clear formatting", self._clear_formatting)
        self.more_menu.addSeparator()
        self.more_menu.addAction("Undo", self.editor.undo)
        self.more_menu.addAction("Redo", self.editor.redo)

        row2.addWidget(self.more_btn)
        row2.addStretch()

        outer.addLayout(row2)

        # Toolbar styling
        self.format_toolbar.setStyleSheet("""
            QFrame#FormatToolbar {
                background-color: rgba(24, 24, 27, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }

            QFrame#FormatToolbar QToolButton {
                color: #a1a1aa;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 0px;
            }

            QFrame#FormatToolbar QToolButton:hover {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.14);
                color: #ffffff;
            }

            QFrame#FormatToolbar QToolButton:checked {
                background: rgba(59, 130, 246, 0.25);
                border: 1px solid rgba(59, 130, 246, 0.6);
                color: #60a5fa;
            }

            QFrame#FormatToolbar QComboBox {
                color: #e4e4e7;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding-left: 6px;
                font-size: 11px;
                font-weight: 500;
            }

            QFrame#FormatToolbar QComboBox:hover {
                background: rgba(255, 255, 255, 0.09);
                border-color: rgba(255, 255, 255, 0.2);
            }

            QFrame#FormatToolbar QComboBox QAbstractItemView {
                color: #f4f4f5;
                background: #27272a;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                selection-background-color: #3b82f6;
                selection-color: #ffffff;
                padding: 2px;
            }

            QFrame#FormatToolbar QSpinBox {
                color: #f4f4f5;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                font-size: 11px;
                font-weight: 500;
            }

            QFrame#FormatToolbar QSpinBox:hover {
                background: rgba(255, 255, 255, 0.09);
                border-color: rgba(255, 255, 255, 0.2);
            }

            QFrame#FormatToolbar QSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 0px;
                height: 0px;
                border: none;
            }

            QFrame#FormatToolbar QSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 0px;
                height: 0px;
                border: none;
            }

            QMenu {
                background-color: #1c1c1f;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 4px;
                color: #e4e4e7;
                font-size: 11px;
            }
            QMenu::item {
                padding: 4px 16px 4px 8px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #3b82f6;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(255, 255, 255, 0.08);
                margin: 4px 2px;
            }
        """)

        self._toolbar_base_stylesheet = (
            self.format_toolbar.styleSheet()
        )

        self.editor.cursorPositionChanged.connect(
            self._sync_format_toolbar)

        # Insert toolbar after editor
        detail_layout.addWidget(self.format_toolbar)

    
    # ---------------- TEXT FORMATTING ----------------

    def _apply_char_format(self, fmt: QTextCharFormat):
        self.editor.mergeCurrentCharFormat(fmt)
        self.editor.setFocus()


    def _toggle_bold(self, checked=False):
        fmt = QTextCharFormat()
        fmt.setFontWeight(
            QFont.Weight.Bold if checked else QFont.Weight.Normal
        )
        self._apply_char_format(fmt)


    def _toggle_italic(self, checked=False):
        fmt = QTextCharFormat()
        fmt.setFontItalic(checked)
        self._apply_char_format(fmt)


    def _toggle_underline(self, checked=False):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(checked)
        self._apply_char_format(fmt)


    def _toggle_strike(self, checked=False):
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(checked)
        self._apply_char_format(fmt)


    def _set_font_size(self, size):
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(size))
        self._apply_char_format(fmt)


    def _adjust_font_size(self, amount):
        new_size = max(
            6,
            min(72, self.font_size_spin.value() + amount)
        )
        self.font_size_spin.setValue(new_size)


    def _set_font_family(self, family):
        if not family.strip():
            return

        fmt = QTextCharFormat()
        fmt.setFontFamily(family)
        self._apply_char_format(fmt)


    # ---------------- HEADINGS ----------------

    def _set_paragraph_style(self, style):

        sizes = {
            "Normal": 13,
            "Heading 1": 22,
            "Heading 2": 18,
            "Heading 3": 15,
            "Quote": 13,
        }

        size = sizes.get(style, 13)

        cursor = self.editor.textCursor()

        block_fmt = QTextBlockFormat()
        char_fmt = QTextCharFormat()

        block_fmt.setTopMargin(6)
        block_fmt.setBottomMargin(6)

        if style == "Quote":
            block_fmt.setLeftMargin(16)
            char_fmt.setFontItalic(True)
            char_fmt.setForeground(QColor("#a1a1aa"))

        else:
            block_fmt.setLeftMargin(0)
            char_fmt.setFontWeight(
                QFont.Weight.Bold
                if style != "Normal"
                else QFont.Weight.Normal
            )

        char_fmt.setFontPointSize(size)

        cursor.beginEditBlock()
        cursor.mergeBlockFormat(block_fmt)
        cursor.mergeCharFormat(char_fmt)
        cursor.endEditBlock()

        self.editor.setTextCursor(cursor)
        self.editor.setFocus()


    # ---------------- LISTS ----------------

    def _insert_list(self, list_style):

        cursor = self.editor.textCursor()
        current_list = cursor.currentList()
        block = cursor.block()
        line_text = block.text()

        # If already in a list of this style, toggle off
        if current_list and current_list.format().style() == list_style:
            current_list.removeItem(current_list.itemNumber(block))
            block_format = QTextBlockFormat()
            block_format.setIndent(0)
            cursor.setBlockFormat(block_format)
            self.editor.setTextCursor(cursor)
            self.editor.setFocus()
            self._sync_format_toolbar()
            return

        # If plain text bullet and bullet was clicked, remove prefix
        stripped = line_text.lstrip()
        if list_style == QTextListFormat.Style.ListDisc and stripped.startswith(("• ", "- ", "* ")):
            leading_spaces = len(line_text) - len(stripped)
            cursor.beginEditBlock()
            cursor.setPosition(block.position() + leading_spaces)
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 2)
            cursor.removeSelectedText()
            cursor.endEditBlock()
            self.editor.setTextCursor(cursor)
            self.editor.setFocus()
            self._sync_format_toolbar()
            return

        # If plain text numbered list and number was clicked, remove prefix
        if list_style == QTextListFormat.Style.ListDecimal:
            m = re.match(r"^(\d+[\.\)]\s)", stripped)
            if m:
                leading_spaces = len(line_text) - len(stripped)
                cursor.beginEditBlock()
                cursor.setPosition(block.position() + leading_spaces)
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(m.group(1)))
                cursor.removeSelectedText()
                cursor.endEditBlock()
                self.editor.setTextCursor(cursor)
                self.editor.setFocus()
                self._sync_format_toolbar()
                return

        list_format = QTextListFormat()
        list_format.setStyle(list_style)
        list_format.setIndent(1)

        cursor.createList(list_format)

        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self._sync_format_toolbar()


    def _insert_checklist_item(self):

        cursor = self.editor.textCursor()
        block = cursor.block()
        existing = block.text()
        stripped = existing.lstrip()
        leading_spaces = len(existing) - len(stripped)

        cursor.beginEditBlock()
        cursor.setPosition(block.position() + leading_spaces)

        if stripped.startswith("☐ "):
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                2
            )
            cursor.insertText("☑ ")

        elif stripped.startswith("☑ "):
            # Toggle off checklist item
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                2
            )
            cursor.removeSelectedText()

        elif stripped.startswith(("[ ] ", "[x] ", "[X] ")):
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                4
            )
            cursor.removeSelectedText()

        else:
            cursor.insertText("☐ ")

        cursor.endEditBlock()

        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self._sync_format_toolbar()


    # ---------------- COLOURS ----------------

    def _choose_text_color(self):

        color = QColorDialog.getColor(
            QColor("#f4f4f5"),
            self,
            "Choose Text Colour"
        )

        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(QBrush(color))
            self._apply_char_format(fmt)


    def _choose_highlight_color(self):

        color = QColorDialog.getColor(
            QColor("#854d0e"),
            self,
            "Choose Highlight Colour"
        )

        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setBackground(QBrush(color))
            self._apply_char_format(fmt)


    # ---------------- TABLE ----------------

    def _insert_table(self):

        cursor = self.editor.textCursor()
        table = cursor.currentTable()

        # If already inside a table, add another row to it
        if table:
            table.appendRows(1)
            self.editor.setTextCursor(cursor)
            self.editor.setFocus()
            self._sync_format_toolbar()
            return

        # Insert a clean 1 row, 2 columns table without blocking modal dialogs
        table_format = QTextTableFormat()
        table_format.setBorder(1)
        table_format.setCellPadding(6)
        table_format.setCellSpacing(0)
        table_format.setBorderBrush(
            QBrush(QColor("#52525b"))
        )
        table_format.setBackground(
            QBrush(QColor("#27272a"))
        )

        cursor.insertTable(1, 2, table_format)

        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self._sync_format_toolbar()


    # ---------------- CODE BLOCK ----------------

    def _insert_code_block(self):

        cursor = self.editor.textCursor()
        block = cursor.block()
        is_code = (
            block.blockFormat().background().color() == QColor("#27272a")
            or cursor.charFormat().font().family() in ("Consolas", "Courier New", "monospace")
        )

        cursor.beginEditBlock()

        if is_code:
            # Revert code block formatting back to normal
            normal_block_fmt = QTextBlockFormat()
            normal_char_fmt = QTextCharFormat()
            normal_char_fmt.setFontFamily(self.font_combo.currentText() or "Segoe UI")
            normal_char_fmt.setFontPointSize(self.font_size_spin.value() or 13)
            normal_char_fmt.setForeground(QColor("#f4f4f5"))
            cursor.setBlockFormat(normal_block_fmt)
            cursor.setCharFormat(normal_char_fmt)
        else:
            block_format = QTextBlockFormat()
            block_format.setBackground(
                QBrush(QColor("#27272a"))
            )
            block_format.setLeftMargin(8)
            block_format.setRightMargin(8)
            block_format.setTopMargin(5)
            block_format.setBottomMargin(5)

            char_format = QTextCharFormat()
            char_format.setFontFamily("Consolas")
            char_format.setFontPointSize(10)
            char_format.setForeground(
                QColor("#e4e4e7")
            )

            if not cursor.hasSelection() and block.text().strip():
                cursor.insertBlock(
                    block_format,
                    char_format
                )
            else:
                cursor.mergeBlockFormat(block_format)
                cursor.mergeCharFormat(char_format)

        cursor.endEditBlock()

        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self._sync_format_toolbar()


    # ---------------- HYPERLINK ----------------

    def _insert_link(self):

        cursor = self.editor.textCursor()

        url, ok = QInputDialog.getText(
            self,
            "Insert Hyperlink",
            "Enter URL:"
        )

        if not ok or not url.strip():
            return

        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(url.strip())
        fmt.setForeground(QBrush(QColor("#60a5fa")))
        fmt.setFontUnderline(True)

        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        else:
            cursor.insertText(url.strip(), fmt)

        self.editor.setTextCursor(cursor)
        self.editor.setFocus()


    # ---------------- DIVIDER ----------------

    def _insert_horizontal_divider(self):

        cursor = self.editor.textCursor()
        cursor.insertBlock()

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#71717a"))

        cursor.insertText(
            "────────────────────────",
            fmt
        )

        cursor.insertBlock()
        self.editor.setTextCursor(cursor)


    # ---------------- CLEAR FORMATTING ----------------

    def _clear_formatting(self):

        cursor = self.editor.textCursor()

        cursor.beginEditBlock()
        cursor.setCharFormat(QTextCharFormat())
        cursor.setBlockFormat(QTextBlockFormat())
        cursor.endEditBlock()

        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _sync_format_toolbar(self):

        cursor = self.editor.textCursor()
        fmt = self.editor.currentCharFormat()
        block = cursor.block()
        block_text = block.text()
        block_fmt = block.blockFormat()
        current_list = cursor.currentList()

        # Character formats (Bold, Italic, Underline, Strike)
        self.bold_btn.setChecked(fmt.fontWeight() >= QFont.Weight.Bold)
        self.italic_btn.setChecked(fmt.fontItalic())
        self.underline_btn.setChecked(fmt.fontUnderline())
        self.strike_btn.setChecked(fmt.fontStrikeOut())

        # Unordered & Ordered Lists
        is_bullet = False
        is_ordered = False
        if current_list:
            style = current_list.format().style()
            if style in (
                QTextListFormat.Style.ListDisc,
                QTextListFormat.Style.ListCircle,
                QTextListFormat.Style.ListSquare,
            ):
                is_bullet = True
            elif style in (
                QTextListFormat.Style.ListDecimal,
                QTextListFormat.Style.ListLowerAlpha,
                QTextListFormat.Style.ListUpperAlpha,
                QTextListFormat.Style.ListLowerRoman,
                QTextListFormat.Style.ListUpperRoman,
            ):
                is_ordered = True
        else:
            stripped = block_text.lstrip()
            if stripped.startswith(("•", "-", "* ")) and not stripped.startswith(("---", "***", "___")):
                is_bullet = True
            elif re.match(r"^\d+[\.\)]\s", stripped):
                is_ordered = True

        self.bullet_btn.setChecked(is_bullet)
        self.number_btn.setChecked(is_ordered)

        # Checklist (☐ or ☑)
        is_checklist = block_text.lstrip().startswith(("☐", "☑", "[ ]", "[x]", "[X]"))
        self.checklist_btn.setChecked(is_checklist)

        # Table
        is_table = cursor.currentTable() is not None
        self.table_btn.setChecked(is_table)

        # Code block
        is_code = (
            block_fmt.background().color() == QColor("#27272a")
            or fmt.font().family() in ("Consolas", "Courier New", "monospace")
        )
        self.code_btn.setChecked(is_code)

        # Font size spin
        size = fmt.fontPointSize()
        if size <= 0:
            size = 13

        self.font_size_spin.blockSignals(True)
        self.font_size_spin.setValue(max(6, min(72, round(size))))
        self.font_size_spin.blockSignals(False)

        # Font family combo
        self.font_combo.blockSignals(True)
        fams = fmt.fontFamilies()
        family = fams[0] if (fams and isinstance(fams, (list, tuple))) else ""
        if family:
            idx = self.font_combo.findText(family, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self.font_combo.setCurrentIndex(idx)
        self.font_combo.blockSignals(False)



    def _setup_shortcuts(self) -> None:
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.save_immediately)

        self.clear_shortcut = QShortcut(QKeySequence("Ctrl+Shift+N"), self)
        self.clear_shortcut.activated.connect(self._handle_clear_or_new)

        self.hide_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.hide_shortcut.activated.connect(self._handle_escape)

    def _handle_clear_or_new(self) -> None:
        """On Note page, clear note with confirmation; on Home page, create new note."""
        if self.stacked_widget.currentIndex() == 1:
            self.clear_editor_with_confirmation()
        else:
            self.create_new_note()

    def _handle_escape(self) -> None:
        """On Note page, press Escape to return to Home; on Home page, hide app."""
        if self.stacked_widget.currentIndex() == 1:
            self.show_home_view()
        else:
            self.hide_app()

    def _load_state(self) -> None:
        data = load_data()
        self._notes = data.get("notes", [])
        self._active_note_id = data.get("active_note_id")
        self._view_mode = data.get("view_mode", "grid")
        try:
            self._ui_scale = max(0.8, min(1.4, float(data.get("ui_scale", 1.0))))
        except (TypeError, ValueError):
            self._ui_scale = 1.0
        self._apply_ui_scale()
        current_view = data.get("current_view", "home")

        # If no notes exist, provide one initial note
        if not self._notes:
            initial_note = {
                "id": str(uuid.uuid4())[:8],
                "title": "Today's notes",
                "custom_title": "",
                "content": data.get("text", "") or "• Important reminders\n• Ideas to remember...",
                "updated_at": datetime.now().strftime("%b %d, %H:%M"),
                "created_at": datetime.now().strftime("%b %d, %H:%M"),
            }
            self._notes.append(initial_note)
            self._active_note_id = initial_note["id"]

        self._update_view_mode_btn_icon()

        # Geometry validation against active screens
        screen_rects: List[Tuple[int, int, int, int]] = []
        for screen in QGuiApplication.screens():
            geom = screen.availableGeometry()
            screen_rects.append((geom.x(), geom.y(), geom.width(), geom.height()))

        geom_data = data.get("geometry", {})
        gx = geom_data.get("x")
        gy = geom_data.get("y")
        gw = geom_data.get("width", DEFAULT_WIDTH)
        gh = geom_data.get("height", DEFAULT_HEIGHT)

        sanitized_x, sanitized_y, sanitized_w, sanitized_h = sanitize_geometry(gx, gy, gw, gh, screen_rects)
        self.setGeometry(sanitized_x, sanitized_y, sanitized_w, sanitized_h)

        if current_view == "note" and self._active_note_id:
            self.open_note(self._active_note_id)
        else:
            self.show_home_view()

        initial_ghost = bool(data.get("ghost_mode", False))
        self.set_ghost_mode(initial_ghost)

    def _save_state(self) -> None:
        geom = self.geometry()

        # If currently editing a note, sync title and editor content into active note
        if self._active_note_id and self.stacked_widget.currentIndex() == 1:
            content = self.editor.toPlainText()
            content_html = self.editor.toHtml()
            custom_title = self.title_input.text().strip()
            effective_title = custom_title if custom_title else derive_note_title(content)

            for n in self._notes:
                if n.get("id") == self._active_note_id:
                    n["content"] = content
                    n["content_html"] = content_html  # NEW
                    n["custom_title"] = custom_title
                    n["title"] = effective_title
                    n["updated_at"] = datetime.now().strftime("%b %d, %H:%M")
                    break

        active_text = ""
        for n in self._notes:
            if n.get("id") == self._active_note_id:
                active_text = n.get("content", "")
                break

        current_view_str = "note" if self.stacked_widget.currentIndex() == 1 else "home"

        data = {
            "text": active_text,
            "notes": self._notes,
            "active_note_id": self._active_note_id,
            "view_mode": self._view_mode,
            "current_view": current_view_str,
            "ui_scale": self._ui_scale,
            "geometry": {
                "x": geom.x(),
                "y": geom.y(),
                "width": geom.width(),
                "height": geom.height(),
            },
            "ghost_mode": self._ghost_mode,
        }
        save_data(data)

    def _on_text_changed(self) -> None:
        self._save_timer.start()

    def save_immediately(self) -> None:
        self._save_timer.stop()
        self._save_state()

    # --- Home Page & Note Switching ---

    def show_home_view(self) -> None:
        """Switch to Home View (All notes preview)."""
        self.save_immediately()
        self.stacked_widget.setCurrentIndex(0)

        # Header updates
        self.title_label.setText("GHOST NOTES")
        count = len(self._notes)
        self.subtitle_label.setText(f"All notes ({count})")
        self.header_actions.show()

        # Hide bottom-left Home button on Home page
        self.home_btn.hide()

        self._render_notes_list()

    def open_note(self, note_id: str) -> None:
        """Open a note in the same window with bottom-left Home button."""
        self._save_state()
        self._active_note_id = note_id

        note = next((n for n in self._notes if n.get("id") == note_id), None)
        if not note:
            return

        # Populate custom title (if given) or empty placeholder
        self.title_input.blockSignals(True)
        self.title_input.setText(note.get("custom_title", ""))
        self.title_input.blockSignals(False)

        # Populate note content while preserving formatting
        self.editor.blockSignals(True)

        saved_html = note.get("content_html")

        if saved_html:
            self.editor.setHtml(saved_html)
        else:
            # Backward compatibility with old notes
            self.editor.setPlainText(note.get("content", ""))

        self.editor.blockSignals(False)

        self.stacked_widget.setCurrentIndex(1)

        # Header titles
        self.title_label.setText("GHOST NOTES")
        self.subtitle_label.setText(str(note.get("title", "Untitled Note")))
        self.header_actions.hide()

        # Show bottom-left Home button when editing note
        self.home_btn.show()

    def create_new_note(self) -> None:
        """Create a fresh note and immediately open it."""
        now = datetime.now().strftime("%b %d, %H:%M")
        new_note = {
            "id": str(uuid.uuid4())[:8],
            "title": "Untitled Note",
            "custom_title": "",
            "content": "",
            "content_html": "",
            "updated_at": now,
            "created_at": now,
        }
        self._notes.insert(0, new_note)
        self._active_note_id = new_note["id"]
        self.save_immediately()
        self.open_note(new_note["id"])

    def delete_note(self, note_id: str) -> None:
        """Delete a note and refresh Home view."""
        self._notes = [n for n in self._notes if n.get("id") != note_id]
        if self._active_note_id == note_id:
            self._active_note_id = self._notes[0]["id"] if self._notes else None
        self.save_immediately()
        self._render_notes_list()
        self.subtitle_label.setText(f"All notes ({len(self._notes)})")

    def _toggle_view_mode(self) -> None:
        """Toggle between Grid and List view."""
        self._view_mode = "list" if self._view_mode == "grid" else "grid"
        self._update_view_mode_btn_icon()
        self._render_notes_list()
        self._save_timer.start()

    def _update_view_mode_btn_icon(self) -> None:
        self.toggle_view_btn.setText("☰" if self._view_mode == "grid" else "⊞")

    def _render_notes_list(self) -> None:
        """Render notes inside home_layout in responsive Grid or List view."""
        while self.home_layout.count():
            item = self.home_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

        if not self._notes:
            empty_lbl = QLabel("No notes yet.\nClick + New to create one.", self.home_content)
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #71717a; font-size: 11px; padding: 30px;")
            empty_lbl.setCursor(Qt.CursorShape.ArrowCursor)
            self.home_layout.addWidget(empty_lbl)
            self.home_layout.addStretch()
            return

        viewport_w = max(100, self.home_scroll.viewport().width() - 16)

        if self._view_mode == "grid":
            card_min_width = 130
            cols = max(1, viewport_w // card_min_width)
            self._current_cols = cols

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(8)

            for idx, note in enumerate(self._notes):
                card = NoteCard(note, is_list_view=False, parent=self.home_content, ui_scale=self._ui_scale)
                card.clicked.connect(self.open_note)
                card.delete_requested.connect(self.delete_note)
                r = idx // cols
                c = idx % cols
                grid.addWidget(card, r, c)

            self.home_layout.addLayout(grid)
            self.home_layout.addStretch()
        else:
            self._current_cols = 1
            for note in self._notes:
                card = NoteCard(note, is_list_view=True, parent=self.home_content, ui_scale=self._ui_scale)
                card.clicked.connect(self.open_note)
                card.delete_requested.connect(self.delete_note)
                self.home_layout.addWidget(card)
            self.home_layout.addStretch()

    # --- Mode & Window Management ---

    def clear_editor_with_confirmation(self) -> None:
        if not self.editor.toPlainText().strip() and not self.title_input.text().strip():
            return

        reply = QMessageBox.question( self,
            "Clear Note",
            "Are you sure you want to clear this note?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.title_input.clear()
            self.editor.clear()
            self.save_immediately()

    def hide_app(self) -> None:
        self.hide()
        self.controls.hide()

    def show_app(self) -> None:
        self.show()
        hwnd = int(self.winId())
        exclude_from_taskbar(hwnd)
        set_capture_excluded(hwnd)
        self.controls.show()
        self.update_controls_position()

    def toggle_ghost_mode(self) -> None:
        self.set_ghost_mode(not self._ghost_mode)

    def set_ghost_mode(self, enabled: bool) -> None:
        self._ghost_mode = enabled
        self.controls.set_ghost_state(enabled)

        hwnd = int(self.winId())
        if enabled:
            self.setWindowOpacity(0.35)
            self.title_input.setReadOnly(True)
            self.editor.setReadOnly(True)
            self.editor.clearFocus()
            self.title_input.clearFocus()
            set_click_through(hwnd, True)
        else:
            self.setWindowOpacity(1.0)
            self.title_input.setReadOnly(False)
            self.editor.setReadOnly(False)
            set_click_through(hwnd, False)

        self._save_timer.start()

    def update_controls_position(self) -> None:
        if not self.isVisible():
            return

        ctrl_w = self.controls.width()
        pos_x = self.x() + self.width() - ctrl_w - 10
        pos_y = self.y() + 8
        self.controls.move(pos_x, pos_y)
        if not self.controls.isVisible():
            self.controls.show()
        self.controls.raise_()

    # --- Window Events ---

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.update_controls_position()
        self._save_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_controls_position()

        # Recalculate grid columns if on Home view
        if self.stacked_widget.currentIndex() == 0 and self._view_mode == "grid":
            viewport_w = max(100, self.home_scroll.viewport().width() - 16)
            cols = max(1, viewport_w // 130)
            if cols != self._current_cols:
                self._render_notes_list()

        self._save_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        hwnd = int(self.winId())
        exclude_from_taskbar(hwnd)
        set_capture_excluded(hwnd)
        self.controls.show()
        self.update_controls_position()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.controls.hide()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            if self.isMinimized():
                self.controls.hide()
            elif self.isVisible():
                self.controls.show()
                self.update_controls_position()

    # --- Mouse interactions for dragging & resizing ---

    def mousePressEvent(self, event) -> None:
        if self._ghost_mode:
            return

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if pos.x() >= self.width() - 18 and pos.y() >= self.height() - 18:
                self._is_resizing = True
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
            elif pos.y() <= 38:
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)

        if self._ghost_mode:
            return

        if self._is_resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            new_w = max(240, self._resize_start_geom.width() + delta.x())
            new_h = max(180, self._resize_start_geom.height() + delta.y())
            self.resize(new_w, new_h)
            return

        if self._is_dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start_pos)
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._is_resizing = False
            self._save_timer.start()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)

    def close_application(self) -> None:
        self.save_immediately()
        self.controls.close()
        self.close()
        QGuiApplication.quit()

    def closeEvent(self, event) -> None:
        self.save_immediately()
        self.controls.close()
        super().closeEvent(event)
