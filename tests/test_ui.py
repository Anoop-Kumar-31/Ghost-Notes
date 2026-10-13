"""
Unit tests for UI components, cursors, HWND separation, taskbar exclusion,
multi-note home page, title input line, and bottom-left Home button navigation.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ghost_notes.main_window import MainWindow
from ghost_notes.win32_utils import is_click_through, is_taskbar_excluded, get_extended_style, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW


def test_ui_and_hwnd_separation(qapp):
    win = MainWindow()
    win.show_app()
    qapp.processEvents()

    # 1. Distinct HWNDs
    win_hwnd = int(win.winId())
    ctrl_hwnd = int(win.controls.winId())
    assert win_hwnd != 0
    assert ctrl_hwnd != 0
    assert win_hwnd != ctrl_hwnd

    # 2. Strict arrow cursor checks
    assert win.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.title_input.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.editor.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.editor.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.blue_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.red_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.resize_grip.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.home_btn.cursor().shape() == Qt.CursorShape.ArrowCursor

    # 3. Hit targets and dot dimensions
    assert win.controls.blue_btn.width() == 18
    assert win.controls.blue_btn.height() == 18
    assert win.controls.red_btn.width() == 18
    assert win.controls.red_btn.height() == 18
    assert win.controls.blue_btn.toolTip() == ""
    assert win.controls.red_btn.toolTip() == ""

    # 4. Taskbar and Alt+Tab exclusion
    assert is_taskbar_excluded(win_hwnd) is True
    assert is_taskbar_excluded(ctrl_hwnd) is True
    win_style = get_extended_style(win_hwnd)
    ctrl_style = get_extended_style(ctrl_hwnd)
    assert bool(win_style & WS_EX_TOOLWINDOW)
    assert not bool(win_style & WS_EX_APPWINDOW)
    assert bool(ctrl_style & WS_EX_TOOLWINDOW)
    assert not bool(ctrl_style & WS_EX_APPWINDOW)

    # 5. Mode toggles and opacity
    win.set_ghost_mode(False)
    assert win.windowOpacity() == 1.0
    assert win.editor.isReadOnly() is False
    assert win.title_input.isReadOnly() is False
    assert not is_click_through(win_hwnd)
    assert is_taskbar_excluded(win_hwnd) is True

    win.set_ghost_mode(True)
    assert round(win.windowOpacity(), 2) == 0.35
    assert win.editor.isReadOnly() is True
    assert win.title_input.isReadOnly() is True
    assert is_click_through(win_hwnd)
    assert is_taskbar_excluded(win_hwnd) is True
    assert not is_click_through(ctrl_hwnd)
    assert is_taskbar_excluded(ctrl_hwnd) is True

    win.set_ghost_mode(False)
    assert win.windowOpacity() == 1.0
    assert win.editor.isReadOnly() is False
    assert win.title_input.isReadOnly() is False
    assert not is_click_through(win_hwnd)
    assert is_taskbar_excluded(win_hwnd) is True

    # 6. Tracking positioning
    initial_ctrl_pos = win.controls.pos()
    win.move(win.x() + 50, win.y() + 50)
    qapp.processEvents()
    new_ctrl_pos = win.controls.pos()
    assert new_ctrl_pos.x() == initial_ctrl_pos.x() + 50
    assert new_ctrl_pos.y() == initial_ctrl_pos.y() + 50

    win.controls.close()
    win.close()


def test_multi_note_navigation_and_views(qapp):
    """Test Home Page (Grid/List), distinct title input line, and bottom-left Home button navigation."""
    win = MainWindow()
    win.show_app()
    qapp.processEvents()

    # 1. On launch, begins on Home View
    win.show_home_view()
    qapp.processEvents()
    assert win.stacked_widget.currentIndex() == 0
    assert win.title_label.text() == "GHOST NOTES"
    assert win.header_actions.isVisible() is True
    # Home button is hidden while on Home page
    assert win.home_btn.isHidden() is True

    # 2. Toggle View Mode (Grid <-> List)
    initial_mode = win._view_mode
    win._toggle_view_mode()
    assert win._view_mode != initial_mode
    win._toggle_view_mode()
    assert win._view_mode == initial_mode

    # 3. Create a new note -> Swaps to Note Detail View in same window
    initial_count = len(win._notes)
    win.create_new_note()
    qapp.processEvents()

    assert len(win._notes) == initial_count + 1
    assert win.stacked_widget.currentIndex() == 1
    assert win.header_actions.isHidden() is True
    # Bottom-left Home button is visible when editing note
    assert win.home_btn.isVisible() is True

    # 4. Test distinct title line input & fallback behavior
    # Custom title entered
    win.title_input.setText("Project Roadmap")
    win.editor.setPlainText("Q1 milestones and deliverables")
    win.save_immediately()
    current_note = next(n for n in win._notes if n.get("id") == win._active_note_id)
    assert current_note.get("title") == "Project Roadmap"

    # Blank title falls back to starting words of content
    win.title_input.setText("")
    win.editor.setPlainText("Quick snippet reminder")
    win.save_immediately()
    current_note = next(n for n in win._notes if n.get("id") == win._active_note_id)
    assert "Quick snippet reminder" in current_note.get("title")

    # 5. Click bottom-left Home button -> Returns to Home View
    win.home_btn.click()
    qapp.processEvents()
    assert win.stacked_widget.currentIndex() == 0
    assert win.title_label.text() == "GHOST NOTES"
    assert win.header_actions.isVisible() is True
    assert win.home_btn.isHidden() is True

    # 6. Open an existing note from Home
    target_id = win._notes[0]["id"]
    win.open_note(target_id)
    qapp.processEvents()
    assert win.stacked_widget.currentIndex() == 1
    assert win.home_btn.isVisible() is True

    win.controls.close()
    win.close()
