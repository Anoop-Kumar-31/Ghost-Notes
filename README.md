# GhostNotes — Transparent Floating Overlay for Windows

**GhostNotes** is a lightweight, frameless, always-on-top desktop note-taking utility engineered specifically for Windows 10 and Windows 11 using Python 3 and PySide6.

It features **Ghost Mode**: a translucent state where mouse clicks and scroll events pass completely through the notes window to whatever application is running underneath, while keeping two discrete controls independently accessible at the top-right corner.

---

## What is GhostNotes?

When working across multiple windows, codebases, or reference documents, switching windows or tiling screens breaks focus. **GhostNotes** floats seamlessly above your active workspace:
- Keep tasks, snippets, or reminders in direct view.
- In **Normal Mode**, edit notes freely, resize the window, or drag it across monitors.
- In **Ghost Mode**, the notes fade to 35% opacity and ignore all mouse clicks, allowing you to click, scroll, and type directly into the applications behind it as if the notes were etched onto your screen.
- The dedicated **Blue Dot** control remains independently clickable at all times to instantly return to Normal Mode.

---

## Key Features

- **Ghost Mode (Blue Dot):**
  - Opacity drops to `0.35`.
  - Clicks and scroll events pass directly through to underlying windows via native Windows Win32 extended window styles (`WS_EX_LAYERED | WS_EX_TRANSPARENT`).
  - Read-only protection prevents accidental keystrokes while clicking through.
- **Normal Mode:**
  - Full opacity (`1.0`) with dark aesthetic.
  - Multiline text editor with word wrapping.
  - Movable (drag header area) and resizable (bottom-right grip).
- **Independent Controls Window:**
  - Houses the **Blue** (Ghost Mode toggle) and **Red** (Close app) controls.
  - Built on a separate native Windows window handle (`HWND`), ensuring controls remain fully interactive even when the notes window itself is click-through.
  - Each visible dot is **exactly 5 × 5 logical pixels**, centered in an approximately **18 × 18 logical pixel** clickable hit target.
  - Clean minimalist interface with no distracting hover tooltip overlays.
- **Windows Taskbar & Alt+Tab Exclusion:**
  - Neither the notes window nor the controls window creates an entry on the Windows taskbar.
  - Completely excluded from the Windows Alt+Tab application switcher using `WS_EX_TOOLWINDOW` and stripping `WS_EX_APPWINDOW`.
  - Floats cleanly without cluttering your OS navigation.
- **Strict Mouse Cursor Preservation:**
  - Preserves the standard Windows arrow pointer (`Qt.CursorShape.ArrowCursor`) across all components.
  - Never displays an I-beam, pointing hand, resize cursor, or move cursor.
- **Atomic Local Persistence:**
  - Automatically saves notes and window geometry (debounced 500ms) to `%LOCALAPPDATA%\GhostNotes\notes.json`.
  - Atomic file replacement (`os.replace`) prevents corruption during unexpected shutdowns.
  - Multi-monitor geometry sanitization: if a display is disconnected, notes automatically reposition onto your primary visible monitor.

---

## Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl + S` | Save notes and window geometry immediately |
| `Ctrl + Shift + N` | Clear notes editor (prompts with confirmation dialog) |
| `Escape` | Hide the notes and controls window |

---

## Project Structure

```
ghost-notes/
├── .editorconfig          # Editor indentation and line ending rules
├── .gitattributes         # Git line ending normalization
├── .gitignore             # Git ignored files (caches, builds, venv)
├── GhostNotes.vbs         # Silent background launcher (no terminal window)
├── LICENSE                # MIT License
├── README.md              # Documentation and guide
├── requirements.txt       # Project dependencies (PySide6, pytest)
├── main.py                # Main application entry point
├── ghost_notes/           # Core application package
│   ├── __init__.py
│   ├── controls.py        # Independent Blue/Red control window
│   ├── main_window.py     # Main floating notes window & UI
│   ├── persistence.py     # Atomic JSON load/save & screen geometry sanitization
│   └── win32_utils.py     # Win32 ctypes API (WS_EX styles, click-through, taskbar exclusion)
└── tests/                 # Automated test suite
    ├── __init__.py
    ├── conftest.py        # Shared pytest fixtures (QApplication)
    ├── test_persistence.py# Persistence, atomic writes, corrupted JSON recovery tests
    ├── test_ui.py         # UI dimensions, cursors, HWND separation tests
    └── test_win32.py      # Win32 click-through & taskbar exclusion tests
```

---

## Installation & Setup

### System Requirements
- **OS:** Windows 10 or Windows 11 (64-bit recommended)
- **Python:** Python 3.11+ (Python 3.12 supported)

### 1. Create and Activate Virtual Environment

Open PowerShell or Command Prompt in the `ghost-notes` directory:

```powershell
# Create virtual environment
py -3 -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1
```

*(If PowerShell script execution is restricted, run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` or directly use `.\.venv\Scripts\python.exe`)*

### 2. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 3. Launching GhostNotes

#### Option A: Silent Background Launch (Recommended)
Double-click `GhostNotes.vbs` in File Explorer, or execute:
```powershell
wscript.exe GhostNotes.vbs
```
This runs GhostNotes silently in the background with `pythonw.exe` without opening a terminal window.

#### Option B: Standard Terminal Launch
```powershell
python main.py
```

### 4. Running the Automated Tests

Run the full pytest suite:

```powershell
python -m pytest -v
```

All 13 automated tests verify persistence, atomic file writes, screen boundary sanitization, UI cursor shapes, independent HWND separation, native click-through styles, and taskbar exclusion.

---

## How Ghost Mode Works Under the Hood

Ghost Mode utilizes Windows Win32 API functions (`GetWindowLongPtrW`, `SetWindowLongPtrW`, and `SetWindowPos`) through Python's `ctypes` library:

1. **Activation:**
   - Adds the extended window styles `WS_EX_LAYERED (0x00080000)` and `WS_EX_TRANSPARENT (0x00000020)` to the notes window's native `HWND`.
   - Windows redirects all mouse hit tests (`WM_NCHITTEST`) through the notes window to the window beneath it.
   - Adjusts window opacity to `0.35` via PySide6.
2. **Deactivation:**
   - Clears `WS_EX_TRANSPARENT` while preserving `WS_EX_LAYERED`, `WS_EX_TOOLWINDOW`, and existing styles.
   - Restores window opacity to `1.0`.
3. **Controls Accessibility:**
   - The controls window has an independent native `HWND`.
   - Because `WS_EX_TRANSPARENT` is applied solely to the notes window `HWND` and **never** to the controls window `HWND`, the blue dot can always receive mouse clicks to exit Ghost Mode.
4. **Taskbar & Alt+Tab Exclusion:**
   - Both windows receive `WS_EX_TOOLWINDOW (0x00000080)` and strip `WS_EX_APPWINDOW (0x00040000)`, preventing Windows from displaying a taskbar icon or adding GhostNotes to the Alt+Tab window list.

---

## Building a Standalone Executable (PyInstaller)

To build a standalone single-file `.exe` that runs without requiring Python installed:

```powershell
pip install pyinstaller
pyinstaller --noconsole --name "GhostNotes" --clean main.py
```

The resulting executable will be generated in `dist/GhostNotes.exe`.

---

## License

This project is licensed under the [MIT License](LICENSE).
