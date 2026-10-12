# 👻 GhostNotes — The Invisible Floating Overlay for Windows

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows_10_%7C_11-0078D6.svg)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PySide6-41CD52.svg?logo=qt&logoColor=white)](https://www.qt.io/qt-for-python)

**GhostNotes** is a lightweight, frameless, always-on-top desktop scratchpad engineered natively for Windows 10 and Windows 11. Designed for developers, presenters, gamers, and multitaskers who need notes, prompts, or snippets on screen without cluttering their workflow or exposing notes to others.

---

## ⚡ Flagship Features

### 👁️ Total Ghost Mode (Screen Share & Screenshot Invisible)
*Your notes are for your eyes only.*
- Utilizing native Windows Win32 display affinity (`WDA_EXCLUDEFROMCAPTURE`), GhostNotes is **completely invisible to screenshots, video recordings, and screen sharing applications**.
- Share your full desktop on **Discord, Zoom, Microsoft Teams, Google Meet, OBS, or Slack** without your audience ever seeing your notes.
- Windows Snipping Tool and screenshot shortcuts will capture right through GhostNotes as if it were not there.

### 🎯 Not a Shower (Strict Zero-Distraction Cursor)
*No mouse giveaways.*
- **Never changes your mouse cursor**: Hovering over text, buttons, headers, or resize areas never changes the mouse pointer into an I-beam, text selector, pointing hand, or resize arrow.
- The standard Windows arrow pointer (`Qt.CursorShape.ArrowCursor`) is strictly preserved across the entire interface.
- In Ghost Mode, your cursor passes through seamlessly and respects the underlying window's cursor behavior without interference.

### 🖱️ True Ghost Click-Through
*Interact with what's underneath.*
- Press the **Blue Dot** to activate Ghost Mode: opacity drops to **35%**, and native Win32 extended styles (`WS_EX_LAYERED | WS_EX_TRANSPARENT`) route all clicks, scrolls, and mouse movements directly to the applications underneath.
- Code, browse, game, or read beneath your floating notes without having to minimize or reposition them.
- Accidental keystrokes are prevented while Ghost Mode is engaged.

### 🥷 Phantom Taskbar & Alt+Tab Exclusion
*Zero desktop footprint.*
- Neither the notes overlay nor the controls appear as an application tile on the Windows taskbar.
- Excluded from the **Alt+Tab** switcher via native `WS_EX_TOOLWINDOW` extended styles.
- Stays quietly pinned above your workspace without cluttering your OS navigation.

### 🔴 Minimalist Micro-Controls (Zero Tooltip Overlay)
*Clean and distraction-free.*
- Two discrete micro-controls aligned at the top-right:
  - **Blue Dot:** Toggle Ghost Mode (5 × 5 px visible dot, 18 × 18 px clickable hit target).
  - **Red Dot:** Clean Exit & Save (5 × 5 px visible dot, 18 × 18 px clickable hit target).
- **No hover popups or tooltip overlays**: Buttons never display distracting hover text boxes that block your view.

### 🧩 Independent HWND Architecture
*Never get trapped in click-through mode.*
- The controls window operates on a distinct native Windows window handle (`HWND`) from the notes window.
- Even when the notes window is 100% click-through, the Blue Dot remains independently interactive so you can instantly switch back to Normal Mode.

### 💾 Atomic Persistence & Display Recovery
*Reliable and resilient.*
- Automatically saves text and coordinates (debounced 500ms) to `%LOCALAPPDATA%\GhostNotes\notes.json`.
- Uses atomic file swaps (`os.replace`) to prevent corruption during sudden power losses or system reboots.
- **Smart multi-monitor recovery**: Disconnecting an external monitor automatically snaps GhostNotes back onto your primary active display so your notes are never lost off-screen.

### 🚀 Silent Background Launcher
- Start GhostNotes instantly with `GhostNotes.vbs` without spawning a black Command Prompt or terminal console window.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl + S` | Immediately save notes and window position |
| `Ctrl + Shift + N` | Clear notes editor (prompts for confirmation) |
| `Escape` | Hide notes and controls overlay |

---

## 📂 Project Structure

```
ghost-notes/
├── .editorconfig          # Code style and indentation rules
├── .gitattributes         # Git LF/CRLF normalization
├── .gitignore             # Comprehensive Python/Win32 ignore rules
├── GhostNotes.vbs         # Silent background launcher (no console window)
├── LICENSE                # Apache License 2.0
├── README.md              # Documentation
├── requirements.txt       # Dependencies (PySide6, pytest)
├── main.py                # Application entry point
├── ghost_notes/           # Core application package
│   ├── __init__.py
│   ├── controls.py        # Independent Blue/Red control window
│   ├── main_window.py     # Main floating notes window & UI
│   ├── persistence.py     # Atomic JSON load/save & screen geometry sanitization
│   └── win32_utils.py     # Win32 ctypes API (WS_EX styles, capture affinity, taskbar exclusion)
└── tests/                 # Automated test suite (13 passing tests)
    ├── __init__.py
    ├── conftest.py        # Shared pytest fixtures
    ├── test_persistence.py# Persistence, atomic writes, corrupted JSON recovery
    ├── test_ui.py         # UI dimensions, cursors, HWND separation
    └── test_win32.py      # Win32 click-through, capture exclusion, taskbar styles
```

---

## 🛠️ Installation & Setup

### Requirements
- **Operating System:** Windows 10 or Windows 11 (64-bit recommended)
- **Python:** Python 3.11+ (Python 3.12 supported)

### 1. Setup Virtual Environment

Open PowerShell in the `ghost-notes` directory:

```powershell
# Create virtual environment
py -3 -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1
```

*(If PowerShell script execution is restricted, run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` or directly invoke `.\.venv\Scripts\python.exe`)*

### 2. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 3. Launch GhostNotes

#### Option A: Silent Background Launch (Recommended)
Double-click `GhostNotes.vbs` in File Explorer, or run:
```powershell
wscript.exe GhostNotes.vbs
```
*Launches GhostNotes silently using `pythonw.exe` without opening a terminal window.*

#### Option B: Terminal Launch
```powershell
python main.py
```

### 4. Run Automated Test Suite

```powershell
python -m pytest -v
```

All 13 automated tests validate:
- Persistence, corrupted JSON recovery, and atomic writing.
- Off-screen monitor recovery and geometry sanitization.
- Strict arrow cursor enforcement across all UI components.
- Dual HWND separation and independent controls responsiveness.
- Win32 click-through styles (`WS_EX_TRANSPARENT | WS_EX_LAYERED`).
- Taskbar and Alt+Tab exclusion (`WS_EX_TOOLWINDOW`).

---

## 🔬 Under the Hood: Win32 Architecture

GhostNotes interfaces with the Windows Win32 API via Python's `ctypes`:

1. **Click-Through Routing:**
   - Adds `WS_EX_LAYERED (0x00080000)` and `WS_EX_TRANSPARENT (0x00000020)` to the notes window HWND.
   - Windows passes mouse hit-tests (`WM_NCHITTEST`) through to underlying windows.
2. **Screen Capture Exclusion:**
   - Calls `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE [0x00000011])` to render the window completely invisible to Desktop Duplication API, screen share encoders, and screen grabbers.
3. **Taskbar & Alt+Tab Stripping:**
   - Sets `WS_EX_TOOLWINDOW (0x00000080)` and clears `WS_EX_APPWINDOW (0x00040000)`.
4. **Independent Control HWND:**
   - The controls window lives as a separate native OS window. When the notes window is set to click-through, the controls window is unaffected and remains clickable.

---

## 📦 Packaging & Standalone Execution

### No Need to Install or Build? Use `GhostNotes.vbs`!
If you don't want to install PyInstaller or build a binary, **you don't have to**:
- Simply double-click **`GhostNotes.vbs`**.
- It runs GhostNotes silently in the background via `pythonw.exe` without opening a terminal window.
- You get the exact same clean, console-less experience as a compiled desktop app with zero compilation time.

---

### Optional: Compiling into a Standalone `.exe` (PyInstaller)
If you want to distribute GhostNotes as a single, portable executable to a machine that doesn't have Python installed:

```powershell
pip install pyinstaller
pyinstaller --noconsole --name "GhostNotes" --clean main.py
```

The compiled standalone executable will be generated at `dist/GhostNotes.exe`.

---

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).
