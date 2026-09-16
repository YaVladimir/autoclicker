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
if sys.platform != "darwin":
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

    def test_saves_click_preferences_without_overwriting_hotkeys(self) -> None:
        hotkeys = {"toggle": 120, "capture": 122, "stop": 99}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(app, "SETTINGS_PATH", path):
                app.save_hotkeys(hotkeys)
                app.save_click_preferences("55", "0,5", "right")
                self.assertEqual(app.load_hotkeys(), hotkeys)
                self.assertEqual(
                    app.load_click_preferences(),
                    {"cps": "55", "delay": "0.5", "mouse_button": "right"},
                )

    def test_uses_fast_defaults_when_preferences_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "SETTINGS_PATH", Path(directory) / "settings.json"):
                self.assertEqual(app.load_click_preferences(), app.DEFAULT_CLICK_PREFERENCES)


class AppearanceTests(unittest.TestCase):
    def test_appearance_preserves_hotkeys_and_click_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "SETTINGS_PATH", Path(directory) / "settings.json"):
                app.save_hotkeys(app.DEFAULT_HOTKEYS)
                app.save_click_preferences("25", "1,5", "right")
                app.save_appearance("Тёмная", "Зелёный")
                self.assertEqual(app.load_appearance(), {"theme": "Тёмная", "accent": "Зелёный"})
                self.assertEqual(app.load_hotkeys(), app.DEFAULT_HOTKEYS)
                self.assertEqual(app.load_click_preferences()["delay"], "1.5")
                app.save_click_preferences("50", "0", "left")
                self.assertEqual(app.load_appearance()["theme"], "Тёмная")

    def test_invalid_appearance_falls_back_per_field(self):
        for saved in (None, [], {"theme": [], "accent": "Зелёный"}):
            with self.subTest(saved=saved), patch.object(app, "_load_settings", return_value={"appearance": saved}):
                self.assertEqual(app.load_appearance()["theme"], "Системная")
        with patch.object(app, "_save_settings") as save:
            with self.assertRaises(ValueError):
                app.save_appearance("unknown", "Синий")
            save.assert_not_called()


class CoordinatesTests(unittest.TestCase):
    def test_desktop_coordinates_use_points_on_all_sides_of_primary_display(self):
        for source, expected in (
            ((100, 800), (100, 100)),
            ((-400, 200), (-400, 700)),
            ((1600, 1000), (1600, -100)),
            ((20.5, -300.5), (20.5, 1200.5)),
        ):
            with self.subTest(source=source):
                self.assertEqual(app.cocoa_to_quartz(*source, 900), expected)


class ClickEngineTests(unittest.TestCase):
    def test_starts_and_stops_cleanly(self) -> None:
        clicks: list[tuple[str, tuple[float, float] | None]] = []
        engine = app.ClickEngine(lambda button, position: clicks.append((button, position)))
        self.assertTrue(engine.start(app.ClickConfig(100, "left", None)))
        self.assertFalse(engine.start(app.ClickConfig(100, "left", None)))
        engine.stop()
        self.assertFalse(engine.running)
        self.assertGreaterEqual(len(clicks), 1)
