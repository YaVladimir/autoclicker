"""A real macOS UI smoke test, intended to run on a logged-in Mac desktop."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(
    sys.platform == "darwin" and os.environ.get("RUN_MACOS_UI_SMOKE") == "1",
    "set RUN_MACOS_UI_SMOKE=1 on a logged-in Mac desktop to run native UI checks",
)
class CocoaUiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUTOCLICKER_UI_SMOKE"] = "1"
        import AppKit
        import autoclicker_macos as core
        from macos_cocoa_ui import CocoaAutoClickerApp

        self.appkit = AppKit
        self.settings_directory = tempfile.TemporaryDirectory()
        self.settings_patch = patch.object(core, "SETTINGS_PATH", Path(self.settings_directory.name) / "settings.json")
        self.settings_patch.start()
        AppKit.NSApplication.sharedApplication()
        self.controller = CocoaAutoClickerApp.alloc().init()
        self.controller.show()

    def tearDown(self) -> None:
        self.controller.window.close()
        self.settings_patch.stop()
        self.settings_directory.cleanup()
        os.environ.pop("AUTOCLICKER_UI_SMOKE", None)

    def test_window_contains_visible_controls(self) -> None:
        self.assertEqual(self.controller.window.title(), "Автокликер для macOS")
        self.assertTrue(self.controller.window.isVisible())
        self.assertGreaterEqual(len(self.controller.content.subviews()), 20)
        self.assertEqual(self.controller.start_button.title(), "Запустить")
        self.assertEqual(self.controller.hotkeys_button.title(), "Горячие клавиши…")
        self.assertIn("F6", self.controller.hotkey_summary_label.stringValue())
        self.assertFalse(self.controller.topmost_check.state())
        self.assertEqual(self.controller.window.level(), self.appkit.NSNormalWindowLevel)

    def test_default_values_are_rendered(self) -> None:
        self.assertEqual(self.controller.cps_field.stringValue(), "100")
        self.assertEqual(self.controller.delay_field.stringValue(), "0")
        self.assertEqual(self.controller.target_popup.selectedSegment(), 0)
        self.assertEqual(self.controller.button_popup.selectedSegment(), 0)
        self.assertEqual(self.controller.speed_slider.doubleValue(), 100)

    def test_footer_stays_visible_when_window_is_resized(self):
        app = self.controller
        self.assertTrue(app.window.styleMask() & self.appkit.NSWindowStyleMaskResizable)
        for width, height in ((580, 360), (600, 650), (900, 780)):
            with self.subTest(size=(width, height)):
                app.window.setContentSize_((width, height))
                app._layout()
                bounds = app.footer.bounds()
                for control in (app.start_button, app.stop_button, app.status_detail_label):
                    self.assertTrue(self.appkit.NSContainsRect(bounds, control.frame()))
                self.assertEqual(app.footer.frame().origin.y, 0)
                self.assertGreaterEqual(app.scroll_view.frame().origin.y, 150)
                for control in app.content.subviews():
                    self.assertTrue(self.appkit.NSContainsRect(app.content.bounds(), control.frame()))

    def test_presets_and_slider_stay_in_sync(self):
        app = self.controller
        app.setSpeed_(app.speed_presets[1])
        self.assertEqual(app.cps_field.stringValue(), "20")
        self.assertEqual(app.speed_slider.doubleValue(), 20)
        app.speed_slider.setDoubleValue_(45)
        app.slideSpeed_(app.speed_slider)
        self.assertEqual(app.cps_field.stringValue(), "45")

    def test_appearance_switches_without_rebuilding_window(self):
        app = self.controller
        for theme, name in (("Светлая", self.appkit.NSAppearanceNameAqua), ("Тёмная", self.appkit.NSAppearanceNameDarkAqua)):
            for accent in ("Синий", "Фиолетовый", "Зелёный"):
                app.appearance = {"theme": theme, "accent": accent}
                app._apply_appearance()
                self.assertEqual(app.window.appearance().name(), name)
                self.assertTrue(app.window.isVisible())
        app.appearance["theme"] = "Системная"
        app._apply_appearance()
        self.assertIsNone(app.window.appearance())

    def test_point_selection_can_be_cancelled_without_input_permissions(self):
        app = self.controller
        app.fixed_position = (40, 60)
        app.capturePosition_(None)
        try:
            self.assertEqual(len(app.selection_windows), len(self.appkit.NSScreen.screens()))
            self.assertFalse(app.window.isVisible())
            for window in app.selection_windows:
                self.assertTrue(window.isVisible())
                self.assertTrue(window.canBecomeKeyWindow())
            app._cancel_point_selection()
            self.assertTrue(app.window.isVisible())
            self.assertEqual(app.fixed_position, (40, 60))
            self.assertEqual(app.selection_windows, [])
        finally:
            app._stop_all()

    def test_starts_at_100_clicks_per_second_without_delay(self) -> None:
        class FakeEngine:
            running = False

            def __init__(self) -> None:
                self.config = None

            def start(self, config):  # type: ignore[no-untyped-def]
                self.config = config
                self.running = True
                return True

            def stop(self) -> None:
                self.running = False

        engine = FakeEngine()
        self.controller.engine = engine
        self.controller.cps_field.setStringValue_("100")
        self.controller.delay_field.setStringValue_("0")

        self.controller._start()

        self.assertIsNotNone(engine.config)
        self.assertEqual(engine.config.cps, 100)
        self.assertEqual(engine.config.fixed_position, None)
        self.assertEqual(self.controller.status_title_label.stringValue(), "РАБОТАЕТ")
