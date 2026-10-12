"""
Unit tests for UI components, cursors, HWND separation, taskbar exclusion, and mode toggling.
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
    assert win.editor.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.editor.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.blue_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.red_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.resize_grip.cursor().shape() == Qt.CursorShape.ArrowCursor

    # 3. Hit targets and dot dimensions
    assert win.controls.blue_btn.width() == 18
    assert win.controls.blue_btn.height() == 18
    assert win.controls.red_btn.width() == 18
    assert win.controls.red_btn.height() == 18

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
    # Normal mode initially
    win.set_ghost_mode(False)
    assert win.windowOpacity() == 1.0
    assert win.editor.isReadOnly() is False
    assert not is_click_through(win_hwnd)
    assert is_taskbar_excluded(win_hwnd) is True

    # Ghost mode
    win.set_ghost_mode(True)
    assert round(win.windowOpacity(), 2) == 0.35
    assert win.editor.isReadOnly() is True
    assert is_click_through(win_hwnd)
    assert is_taskbar_excluded(win_hwnd) is True
    # Crucial: controls window itself must NOT be click-through!
    assert not is_click_through(ctrl_hwnd)
    assert is_taskbar_excluded(ctrl_hwnd) is True

    # Toggle back to normal
    win.set_ghost_mode(False)
    assert win.windowOpacity() == 1.0
    assert win.editor.isReadOnly() is False
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
