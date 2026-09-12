"""Unit tests that do not require macOS permissions or a real display."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


# The functions under test do not call Quartz. A small placeholder keeps the
# tests portable, including on Linux in GitHub Actions.
sys.modules.setdefault("Quartz", types.SimpleNamespace())

import autoclicker_macos as app  # noqa: E402


class SettingsTests(unittest.TestCase):
    def test_accepts_comma_decimal_separator(self) -> None:
        self.assertEqual(app.parse_settings("20,5", "1,5"), (20.5, 1.5))

    def test_rejects_out_of_range_values(self) -> None:
        for cps, delay in (("0", "1"), ("101", "1"), ("20", "-1"), ("20", "11")):
            with self.subTest(cps=cps, delay=delay):
                with self.assertRaises(ValueError):
                    app.parse_settings(cps, delay)

    def test_restores_defaults_for_invalid_hotkeys(self) -> None:
        self.assertEqual(app.validate_hotkeys({"toggle": 1}), app.DEFAULT_HOTKEYS)

    def test_restores_defaults_for_duplicate_hotkeys(self) -> None:
        self.assertEqual(
            app.validate_hotkeys({"toggle": 97, "capture": 97, "stop": 100}),
            app.DEFAULT_HOTKEYS,
        )

    def test_saves_and_loads_valid_hotkeys(self) -> None:
        hotkeys = {"toggle": 120, "capture": 122, "stop": 99}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new-settings-folder" / "settings.json"
            with patch.object(app, "SETTINGS_PATH", path):
                app.save_hotkeys(hotkeys)
                self.assertTrue(path.exists())
                self.assertEqual(app.load_hotkeys(), hotkeys)


class ClickEngineTests(unittest.TestCase):
    def test_starts_and_stops_cleanly(self) -> None:
        clicks: list[tuple[str, tuple[float, float] | None]] = []
        engine = app.ClickEngine(lambda button, position: clicks.append((button, position)))
        self.assertTrue(engine.start(app.ClickConfig(100, "left", None)))
        self.assertFalse(engine.start(app.ClickConfig(100, "left", None)))
        engine.stop()
        self.assertFalse(engine.running)
        self.assertGreaterEqual(len(clicks), 1)
