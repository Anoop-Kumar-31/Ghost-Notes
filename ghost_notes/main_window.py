"""
Main notes window for Ghost Notes.
Frameless, translucent, always-on-top window with dark aesthetic and strict arrow cursor.
./main_window.py
"""

from typing import Optional, List, Tuple
from PySide6.QtCore import Qt, QPoint, QRect, QTimer, QSize
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
    QLabel,
    QTextEdit,
    QMessageBox,
    QFrame,
)

from .controls import ControlsWindow
from .win32_utils import set_click_through, exclude_from_taskbar, set_capture_excluded
from .persistence import (
    load_data,
    save_data,
    sanitize_geometry,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
)


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
    """
    Bottom-right resize grip widget that maintains the standard ArrowCursor.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(160, 160, 160, 120), 1.5))
        # Draw 3 subtle diagonal dots/lines
        painter.drawLine(10, 4, 10, 4)
        painter.drawLine(6, 8, 10, 8)
        painter.drawLine(2, 12, 10, 12)

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)


class MainWindow(QWidget):
    """
    Frameless, floating, always-on-top notes window.
    Supports translucent Ghost Mode with native Windows click-through.
    """

    def __init__(self):
        super().__init__()

        self._ghost_mode = False
        self._is_dragging = False
        self._is_resizing = False
        self._drag_start_pos = QPoint()
        self._resize_start_pos = QPoint()
        self._resize_start_geom = QRect()

        # Frameless, always on top, tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Requirement 13: strictly arrow cursor
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

        # Dedicated controls window with separate native HWND
        self.controls = ControlsWindow()
        self.controls.toggle_ghost_requested.connect(self.toggle_ghost_mode)
        self.controls.close_requested.connect(self.close_application)

        # Load persisted notes and geometry
        self._load_state()

    def _init_ui(self) -> None:
        self.setObjectName("GhostNotesRoot")

        # Outer container for rounded corners and dark background
        self.container = QFrame(self)
        self.container.setObjectName("Container")
        self.container.setCursor(Qt.CursorShape.ArrowCursor)

        # Stylesheet for sleek dark theme
        self.setStyleSheet(
            """
            #Container {
                background-color: rgba(24, 24, 27, 245);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 10px;
            }
            QLabel#TitleLabel {
                color: #a1a1aa;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.5px;
            }
            QLabel#SubtitleLabel {
                color: #71717a;
                font-size: 11px;
                font-weight: 500;
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
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.container)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(14, 10, 14, 10)
        container_layout.setSpacing(6)

        # Header area (Title and Subtitle)
        self.header_widget = QWidget(self.container)
        self.header_widget.setCursor(Qt.CursorShape.ArrowCursor)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 42, 0)  # Reserve space on right for controls window
        header_layout.setSpacing(8)

        titles_col = QVBoxLayout()
        titles_col.setContentsMargins(0, 0, 0, 0)
        titles_col.setSpacing(1)

        self.title_label = QLabel("GHOST NOTES", self.header_widget)
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setCursor(Qt.CursorShape.ArrowCursor)

        self.subtitle_label = QLabel("Today's notes", self.header_widget)
        self.subtitle_label.setObjectName("SubtitleLabel")
        self.subtitle_label.setCursor(Qt.CursorShape.ArrowCursor)

        titles_col.addWidget(self.title_label)
        titles_col.addWidget(self.subtitle_label)
        header_layout.addLayout(titles_col)
        header_layout.addStretch()

        container_layout.addWidget(self.header_widget)

        # Editor
        self.editor = NoIBeamTextEdit(self.container)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setPlaceholderText("• Task one\n• Important reminders\n• Ideas to remember...")
        self.editor.textChanged.connect(self._on_text_changed)
        container_layout.addWidget(self.editor)

        # Bottom row with resize grip
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.addStretch()

        self.resize_grip = ResizeGrip(self.container)
        bottom_row.addWidget(self.resize_grip)
        container_layout.addLayout(bottom_row)

    def _setup_shortcuts(self) -> None:
        # Ctrl+S: Save notes
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.save_immediately)

        # Ctrl+Shift+N: Clear editor with confirmation
        self.clear_shortcut = QShortcut(QKeySequence("Ctrl+Shift+N"), self)
        self.clear_shortcut.activated.connect(self.clear_editor_with_confirmation)

        # Escape: Hide application
        self.hide_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.hide_shortcut.activated.connect(self.hide_app)

    def _load_state(self) -> None:
        data = load_data()
        self.editor.setPlainText(data.get("text", ""))

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

        # Initial Ghost Mode state (default to False on launch for usability unless requested)
        initial_ghost = bool(data.get("ghost_mode", False))
        if initial_ghost:
            self.set_ghost_mode(True)
        else:
            self.set_ghost_mode(False)

    def _save_state(self) -> None:
        geom = self.geometry()
        data = {
            "text": self.editor.toPlainText(),
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
        """Trigger immediate save (e.g. for Ctrl+S or before close)."""
        self._save_timer.stop()
        self._save_state()

    def clear_editor_with_confirmation(self) -> None:
        """Prompts user before clearing editor (Ctrl+Shift+N)."""
        if not self.editor.toPlainText().strip():
            return

        reply = QMessageBox.question(
            self,
            "Clear Notes",
            "Are you sure you want to clear all notes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.editor.clear()
            self.save_immediately()

    def hide_app(self) -> None:
        """Hide both notes and controls window."""
        self.hide()
        self.controls.hide()

    def show_app(self) -> None:
        """Show both notes and controls window."""
        self.show()
        exclude_from_taskbar(int(self.winId()))
        self.controls.show()
        self.update_controls_position()

    def toggle_ghost_mode(self) -> None:
        """Toggle between Normal Mode and Ghost Mode."""
        self.set_ghost_mode(not self._ghost_mode)

    def set_ghost_mode(self, enabled: bool) -> None:
        """
        Configure Ghost Mode or Normal Mode:
        - Ghost Mode ON: 0.35 opacity, native click-through enabled, editor disabled for input.
        - Ghost Mode OFF: 1.0 opacity, click-through disabled, normal text editing.
        """
        self._ghost_mode = enabled
        self.controls.set_ghost_state(enabled)

        hwnd = int(self.winId())

        if enabled:
            self.setWindowOpacity(0.35)
            self.editor.setReadOnly(True)
            self.editor.clearFocus()
            set_click_through(hwnd, True)
        else:
            self.setWindowOpacity(1.0)
            self.editor.setReadOnly(False)
            set_click_through(hwnd, False)

        # Persist mode change
        self._save_timer.start()

    def update_controls_position(self) -> None:
        """Keep the independent controls window anchored to the top-right corner."""
        if not self.isVisible():
            return

        ctrl_w = self.controls.width()
        # Anchor controls 10px from right edge, 8px from top edge of notes window
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

    # --- Mouse interactions for moving and resizing in Normal Mode ---

    def mousePressEvent(self, event) -> None:
        if self._ghost_mode:
            # Ghost Mode passes through via Win32; if an event reaches here, ignore it
            return

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            # Check if clicked in bottom-right resize corner (18x18 area)
            if pos.x() >= self.width() - 18 and pos.y() >= self.height() - 18:
                self._is_resizing = True
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
            elif pos.y() <= 40:  # Header drag area
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        # Requirement 13: strictly arrow cursor
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
        """Clean shutdown: save state and close both windows."""
        self.save_immediately()
        self.controls.close()
        self.close()
        QGuiApplication.quit()

    def closeEvent(self, event) -> None:
        self.save_immediately()
        self.controls.close()
        super().closeEvent(event)
