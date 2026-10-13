"""
Main notes window for Ghost Notes.
Frameless, translucent, always-on-top window supporting multiple notes,
home page with responsive grid / list view, note editing with distinct title line,
and a bottom-left Home button.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any
from PySide6.QtCore import Qt, QPoint, QRect, QTimer, QSize, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QKeySequence,
    QShortcut,
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
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
)

from .controls import ControlsWindow
from .platform_utils import set_click_through, exclude_from_taskbar, set_capture_excluded
from .persistence import (
    load_data,
    save_data,
    sanitize_geometry,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
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
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

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

    def __init__(self, note: Dict[str, Any], is_list_view: bool = False, parent: Optional[QWidget] = None):
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
            """
            QFrame#NoteCard {
                background-color: rgba(39, 39, 42, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            QFrame#NoteCard:hover {
                background-color: rgba(59, 130, 246, 0.15);
                border: 1px solid rgba(59, 130, 246, 0.4);
            }
            """
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
        self.title_lbl.setStyleSheet("color: #f4f4f5; font-size: 11px; font-weight: 700; background: transparent;")
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
        self.snippet_lbl.setStyleSheet("color: #a1a1aa; font-size: 10px; background: transparent;")
        layout.addWidget(self.snippet_lbl)

        # Footer row: Date
        if date_str:
            self.date_lbl = QLabel(date_str, self)
            self.date_lbl.setCursor(Qt.CursorShape.ArrowCursor)
            self.date_lbl.setStyleSheet("color: #71717a; font-size: 9px; background: transparent;")
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

        # Keyboard shortcuts
        self._setup_shortcuts()

        # Independent controls window (Blue & Red micro-dots)
        self.controls = ControlsWindow()
        self.controls.toggle_ghost_requested.connect(self.toggle_ghost_mode)
        self.controls.close_requested.connect(self.close_application)

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
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setPlaceholderText("Type your notes here... (Ctrl+S to save, Ctrl+Shift+N to clear)")
        self.editor.textChanged.connect(self._on_text_changed)
        detail_layout.addWidget(self.editor)
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

        sanitized_x, sanitized_y, sanitized_w, sanitized_h = sanitize_geometry(
            gx, gy, gw, gh, screen_rects
        )
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
            custom_title = self.title_input.text().strip()
            effective_title = custom_title if custom_title else derive_note_title(content)

            for n in self._notes:
                if n.get("id") == self._active_note_id:
                    n["content"] = content
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

        # Populate note content
        self.editor.blockSignals(True)
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
                card = NoteCard(note, is_list_view=False, parent=self.home_content)
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
                card = NoteCard(note, is_list_view=True, parent=self.home_content)
                card.clicked.connect(self.open_note)
                card.delete_requested.connect(self.delete_note)
                self.home_layout.addWidget(card)
            self.home_layout.addStretch()

    # --- Mode & Window Management ---

    def clear_editor_with_confirmation(self) -> None:
        if not self.editor.toPlainText().strip() and not self.title_input.text().strip():
            return

        reply = QMessageBox.question(
            self,
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
