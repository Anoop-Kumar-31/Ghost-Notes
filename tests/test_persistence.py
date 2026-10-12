"""
Unit tests for Ghost Notes persistence and geometry validation.
Tests run headless and do not require Windows GUI or HWND interactions.
"""

import json
from pathlib import Path
import pytest

from ghost_notes.persistence import (
    load_data,
    save_data,
    sanitize_geometry,
    DEFAULT_DATA,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
)


def test_missing_json_file(tmp_path: Path):
    """Test loading from a non-existent file returns sensible defaults."""
    non_existent = tmp_path / "does_not_exist.json"
    data = load_data(non_existent)
    assert data["text"] == ""
    assert data["ghost_mode"] is False
    assert data["geometry"]["width"] == DEFAULT_WIDTH
    assert data["geometry"]["height"] == DEFAULT_HEIGHT
    assert not non_existent.exists()


def test_save_and_load_text(tmp_path: Path):
    """Test saving and loading note text."""
    target_file = tmp_path / "notes.json"
    sample_text = "• Important reminder\n• Call at 3pm\nMultiline notes with UTF-8: 🚀"

    save_payload = {
        "text": sample_text,
        "geometry": {"x": 120, "y": 80, "width": 400, "height": 320},
        "ghost_mode": False,
    }

    assert save_data(save_payload, target_file) is True
    assert target_file.is_file()

    loaded = load_data(target_file)
    assert loaded["text"] == sample_text
    assert loaded["ghost_mode"] is False


def test_save_and_restore_geometry(tmp_path: Path):
    """Test saving and restoring window coordinates and dimensions."""
    target_file = tmp_path / "notes.json"
    save_payload = {
        "text": "Some notes",
        "geometry": {"x": 500, "y": 250, "width": 450, "height": 350},
        "ghost_mode": True,
    }

    assert save_data(save_payload, target_file) is True
    loaded = load_data(target_file)

    assert loaded["geometry"]["x"] == 500
    assert loaded["geometry"]["y"] == 250
    assert loaded["geometry"]["width"] == 450
    assert loaded["geometry"]["height"] == 350
    assert loaded["ghost_mode"] is True


def test_malformed_json_graceful_recovery(tmp_path: Path):
    """Test that malformed JSON is handled gracefully without crashing or deleting the file."""
    corrupt_file = tmp_path / "notes.json"
    corrupt_file.write_text("{ this is not valid json : [", encoding="utf-8")

    loaded = load_data(corrupt_file)
    # Returns default data
    assert loaded["text"] == ""
    assert loaded["geometry"]["width"] == DEFAULT_WIDTH

    # Ensure corrupt file is NOT deleted or erased
    assert corrupt_file.exists()
    assert "{ this is not valid json : [" in corrupt_file.read_text(encoding="utf-8")


def test_empty_json_file(tmp_path: Path):
    """Test that an empty file returns default data without raising an exception."""
    empty_file = tmp_path / "notes.json"
    empty_file.write_text("", encoding="utf-8")

    loaded = load_data(empty_file)
    assert loaded == DEFAULT_DATA


def test_atomic_save_behavior(tmp_path: Path):
    """Test that save writes atomically and produces valid formatted JSON."""
    target_file = tmp_path / "subdir" / "notes.json"
    data = {
        "text": "Testing atomic write",
        "geometry": {"x": 200, "y": 150, "width": 380, "height": 280},
        "ghost_mode": False,
    }

    success = save_data(data, target_file)
    assert success is True
    assert target_file.is_file()

    # Verify no dangling temporary files remain
    tmp_files = list((tmp_path / "subdir").glob("*.tmp"))
    assert len(tmp_files) == 0

    # Verify valid JSON
    with open(target_file, "r", encoding="utf-8") as f:
        parsed = json.load(f)
        assert parsed["text"] == "Testing atomic write"
        assert parsed["geometry"]["width"] == 380


def test_sanitize_geometry_within_screen():
    """Test geometry that already fits within a screen is preserved."""
    screens = [(0, 0, 1920, 1080)]
    x, y, w, h = sanitize_geometry(100, 100, 400, 300, screens)
    assert (x, y, w, h) == (100, 100, 400, 300)


def test_sanitize_geometry_offscreen_repositions_to_primary():
    """Test geometry on disconnected monitor is repositioned into primary screen."""
    screens = [(0, 0, 1920, 1080)]
    # Window positioned way out at x=3500 (e.g. secondary monitor now unplugged)
    x, y, w, h = sanitize_geometry(3500, 100, 400, 300, screens)
    assert w == 400
    assert h == 300
    # Must now be on the primary screen (0 <= x <= 1920 - 400)
    assert 0 <= x <= 1920 - w
    assert 0 <= y <= 1080 - h


def test_sanitize_geometry_default_upper_right():
    """Test default placement when x and y are None."""
    screens = [(0, 0, 1920, 1080)]
    x, y, w, h = sanitize_geometry(None, None, 360, 300, screens)
    assert w == 360
    assert h == 300
    assert x == 1920 - 360 - 40
    assert y == 60
