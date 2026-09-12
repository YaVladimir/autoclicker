"""A real macOS UI smoke test, intended to run on a logged-in Mac desktop."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.uname().sysname == "Darwin" and os.environ.get("RUN_MACOS_UI_SMOKE") == "1",
    "set RUN_MACOS_UI_SMOKE=1 on a logged-in Mac desktop to run native UI checks",
)
class CocoaUiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUTOCLICKER_UI_SMOKE"] = "1"
        import AppKit
        from macos_cocoa_ui import CocoaAutoClickerApp

        self.appkit = AppKit
        AppKit.NSApplication.sharedApplication()
        self.controller = CocoaAutoClickerApp.alloc().init()
        self.controller.show()

    def tearDown(self) -> None:
        self.controller.window.close()
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
        self.assertEqual(self.controller.cps_field.stringValue(), "20")
        self.assertEqual(self.controller.delay_field.stringValue(), "2")
        self.assertEqual(self.controller.target_popup.indexOfSelectedItem(), 0)

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
