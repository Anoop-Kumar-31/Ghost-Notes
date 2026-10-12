"""
Entry point for Ghost Notes.
Initializes the application, sets up display scaling, and manages the main window.
"""

import sys
import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ghost_notes.main_window import MainWindow

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ghost_notes")


def main() -> int:
    # High DPI scaling is handled automatically in Qt 6 / PySide6,
    # but we ensure proper attributes are set.
    app = QApplication(sys.argv)
    app.setApplicationName("Ghost Notes")
    app.setOrganizationName("GhostNotes")

    # Requirement 13: Standard arrow cursor everywhere
    app.setOverrideCursor(Qt.CursorShape.ArrowCursor)

    window = MainWindow()
    window.show_app()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
