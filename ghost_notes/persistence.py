"""
Persistence module for Ghost Notes.
Handles atomic saving, loading, and geometry validation for notes and settings.
./persistence.py
"""

import os
import json
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = 360
DEFAULT_HEIGHT = 300
MIN_WIDTH = 200
MIN_HEIGHT = 150

DEFAULT_DATA: Dict[str, Any] = {
    "text": "",
    "geometry": {
        "x": None,
        "y": None,
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
    },
    "ghost_mode": False,
}


def get_default_storage_path() -> Path:
    """Return the default JSON storage file path (%LOCALAPPDATA%\\GhostNotes\\notes.json on Windows)."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data)
    else:
        # Cross-platform fallback
        base_dir = Path.home() / ".config"
    return base_dir / "GhostNotes" / "notes.json"


def load_data(storage_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load notes and geometry from disk.
    Returns default data if file is missing, empty, or malformed.
    Never raises an exception or corrupts/deletes existing files.
    """
    path = storage_path or get_default_storage_path()
    if not path.is_file():
        logger.info("Storage file not found at %s. Using default settings.", path)
        return dict(DEFAULT_DATA)

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                logger.warning("Storage file at %s is empty. Using default settings.", path)
                return dict(DEFAULT_DATA)
            data = json.loads(content)

        if not isinstance(data, dict):
            logger.warning("Storage JSON is not an object. Using default settings.")
            return dict(DEFAULT_DATA)

        # Merge with defaults to ensure all keys are present
        result = dict(DEFAULT_DATA)
        if "text" in data and isinstance(data["text"], str):
            result["text"] = data["text"]
        if "ghost_mode" in data and isinstance(data["ghost_mode"], bool):
            result["ghost_mode"] = data["ghost_mode"]

        if "geometry" in data and isinstance(data["geometry"], dict):
            geom = data["geometry"]
            result_geom = dict(DEFAULT_DATA["geometry"])
            for key in ("x", "y", "width", "height"):
                val = geom.get(key)
                if isinstance(val, (int, float)):
                    result_geom[key] = int(val)
            result["geometry"] = result_geom

        return result
    except (json.JSONDecodeError, OSError, PermissionError) as exc:
        logger.error("Error reading storage file at %s: %s. Preserving file and returning defaults.", path, exc)
        return dict(DEFAULT_DATA)


def save_data(data: Dict[str, Any], storage_path: Optional[Path] = None) -> bool:
    """
    Atomically save notes and geometry to disk.
    Uses a temporary file in the destination folder and os.replace to guarantee atomic updates.
    """
    path = storage_path or get_default_storage_path()
    try:
        parent_dir = path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "text": str(data.get("text", "")),
            "geometry": {
                "x": data.get("geometry", {}).get("x"),
                "y": data.get("geometry", {}).get("y"),
                "width": max(MIN_WIDTH, int(data.get("geometry", {}).get("width", DEFAULT_WIDTH))),
                "height": max(MIN_HEIGHT, int(data.get("geometry", {}).get("height", DEFAULT_HEIGHT))),
            },
            "ghost_mode": bool(data.get("ghost_mode", False)),
        }

        # Write to temporary file in the same directory for atomic replace
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=parent_dir,
            delete=False,
            encoding="utf-8",
            suffix=".tmp",
        ) as tmp_file:
            json.dump(payload, tmp_file, indent=2, ensure_ascii=False)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            temp_path = Path(tmp_file.name)

        os.replace(temp_path, path)
        logger.debug("Successfully saved notes to %s", path)
        return True
    except Exception as exc:
        logger.error("Failed to atomically save data to %s: %s", path, exc)
        return False


def sanitize_geometry(
    x: Optional[int],
    y: Optional[int],
    width: Optional[int],
    height: Optional[int],
    screen_rects: List[Tuple[int, int, int, int]],
) -> Tuple[int, int, int, int]:
    """
    Ensures that window dimensions and position remain on a visible monitor.
    screen_rects is a list of (left, top, width, height) for each active screen.
    Returns (x, y, width, height).
    """
    w = max(MIN_WIDTH, width if width is not None else DEFAULT_WIDTH)
    h = max(MIN_HEIGHT, height if height is not None else DEFAULT_HEIGHT)

    if not screen_rects:
        # Default fallback if no screens detected
        return (x if x is not None else 100, y if y is not None else 100, w, h)

    primary = screen_rects[0]

    # If x or y is not specified, place near upper right of primary screen
    if x is None or y is None:
        px, py, pw, _ = primary
        default_x = px + pw - w - 40
        default_y = py + 60
        return (default_x, default_y, w, h)

    # Check if window intersects with any active screen by at least 50x50 pixels
    for sx, sy, sw, sh in screen_rects:
        intersects_x = (x + w > sx + 50) and (x < sx + sw - 50)
        intersects_y = (y + h > sy + 50) and (y < sy + sh - 50)
        if intersects_x and intersects_y:
            return (x, y, w, h)

    # Off-screen (e.g. disconnected monitor): reposition to upper-right of primary screen
    px, py, pw, _ = primary
    fallback_x = px + pw - w - 40
    fallback_y = py + 60
    return (fallback_x, fallback_y, w, h)
