"""Controller behavior without a native window, permissions, or real mouse input.

Only the Cocoa bridge is replaced. The actual controller methods and core
settings validation run on every platform; native layout has separate smoke tests.
"""

import importlib.util
from pathlib import Path
import queue
import sys
import types
import unittest
from unittest.mock import Mock, patch

if sys.platform != "darwin":
    sys.modules.setdefault("Quartz", types.SimpleNamespace())
import autoclicker_macos as core


def load_controller():
    appkit = types.SimpleNamespace(NSView=object, NSWindow=object)
    foundation = types.SimpleNamespace(NSObject=object, NSMakeRect=Mock(), NSTimer=Mock())
    spec = importlib.util.spec_from_file_location("_macos_controller_test", Path(__file__).parents[1] / "macos_cocoa_ui.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "AppKit": appkit, "objc": types.SimpleNamespace(python_method=lambda method: method),
        "Foundation": foundation,
    }):
        spec.loader.exec_module(module)
    return module


class FakeEngine:
    running = False

    def __init__(self):
        self.started = []

    def start(self, config):
        self.running = True
        self.started.append(config)
        return True

    def stop(self):
        self.running = False


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.module = load_controller()
        self.controller = self.module.CocoaAutoClickerApp()
        app = self.controller
        app.engine = FakeEngine()
        app.hotkeys = core.DEFAULT_HOTKEYS.copy()
        app.events = queue.SimpleQueue()
        app.fixed_position = None
        app.active_config = app.paused_config = app.countdown_config = app.countdown_timer = None
        app.selection_windows = []
        app._closed = False
        app.cps_field = Mock()
        app.cps_field.stringValue.return_value = "100"
        app.delay_field = Mock()
        app.delay_field.stringValue.return_value = "0"
        app.target_popup = Mock()
        app.target_popup.selectedSegment.return_value = 0
        app.button_popup = Mock()
        app.button_popup.selectedSegment.return_value = 0
        app.setting_controls = [Mock(), Mock()]
        app.start_button = Mock()
        app.stop_button = Mock()
        app.status_title_label = Mock()
        app.status_detail_label = Mock()
        app.position_label = Mock()
        app.show = Mock()
        app._show_alert = Mock()
        save = patch.object(core, "save_click_preferences")
        save.start()
        self.addCleanup(save.stop)

    def test_hotkey_start_pause_and_resume_preserve_session(self):
        app = self.controller
        app.toggleClicking_(None)
        config = app.engine.started[0]
        app.toggleClicking_(None)
        self.assertFalse(app.engine.running)
        self.assertEqual(app.paused_config, config)
        app.toggleClicking_(None)
        self.assertEqual(app.engine.started, [config, config])
        self.assertIsNone(app.countdown_timer)
        app._stop_all()
        self.assertIsNone(app.paused_config)
        self.assertIsNone(app.active_config)
        for control in app.setting_controls:
            control.setEnabled_.assert_called_with(True)

    def test_button_start_and_resume_wait_before_cursor_clicks(self):
        app = self.controller
        with patch.object(self.module.time, "monotonic", return_value=100):
            app.toggleClicking_(object())
        self.assertEqual(app.countdown_deadline, 103)
        self.assertEqual(app.engine.started, [])
        with patch.object(self.module.time, "monotonic", return_value=103):
            app._countdown_tick()
        self.assertTrue(app.engine.running)
        app.toggleClicking_(None)
        with patch.object(self.module.time, "monotonic", return_value=200):
            app.toggleClicking_(object())
        self.assertEqual(app.countdown_deadline, 203)
        self.assertFalse(app.engine.running)
        self.assertEqual(len(app.engine.started), 1)

    def test_explicit_delay_is_used_for_button_and_hotkey(self):
        app = self.controller
        for sender in (None, object()):
            app.delay_field.stringValue.return_value = "1,5"
            with patch.object(self.module.time, "monotonic", return_value=10):
                app.toggleClicking_(sender)
            self.assertEqual(app.countdown_deadline, 11.5)
            self.assertFalse(app.engine.running)
            app._stop_all()

    def test_fixed_target_starts_without_automatic_delay(self):
        app = self.controller
        app.fixed_position = (-150, 100)
        app.target_popup.selectedSegment.return_value = 1
        app.toggleClicking_(object())
        self.assertEqual(app.engine.started[0].fixed_position, (-150, 100))
        app.toggleClicking_(None)
        app.toggleClicking_(object())
        self.assertEqual(len(app.engine.started), 2)
        self.assertIsNone(app.countdown_timer)

    def test_stop_cancels_countdown_and_late_timer_callback(self):
        app = self.controller
        app.toggleClicking_(object())
        timer = app.countdown_timer
        app._stop_all()
        app._countdown_tick()
        timer.invalidate.assert_called_once_with()
        self.assertEqual(app.engine.started, [])
        self.assertIsNone(app.countdown_config)

    def test_missing_point_and_invalid_settings_do_not_start(self):
        app = self.controller
        app.target_popup.selectedSegment.return_value = 1
        app.toggleClicking_(None)
        app._show_alert.assert_called_once()
        app.cps_field.stringValue.return_value = "nan"
        app.target_popup.selectedSegment.return_value = 0
        app.toggleClicking_(None)
        self.assertEqual(app._show_alert.call_count, 2)
        self.assertEqual(app.engine.started, [])

    def test_selection_blocks_start_and_escape_preserves_old_point(self):
        app = self.controller
        window = Mock()
        app.selection_windows = [window]
        app.fixed_position = (45, 67)
        app.toggleClicking_(None)
        app._start()
        self.assertEqual(app.engine.started, [])
        app.events.put(("key", 53))
        app.pollEvents_(None)
        self.assertEqual(app.fixed_position, (45, 67))
        self.assertEqual(app.selection_windows, [])
        window.close.assert_called_once()
        app.show.assert_called_once()

    def test_selection_saves_point_and_cleans_up_all_overlays(self):
        app = self.controller
        windows = [Mock(), Mock()]
        app.selection_windows = windows
        app._finish_point_selection((-340.5, -120))
        self.assertEqual(app.fixed_position, (-340.5, -120))
        app.target_popup.setSelectedSegment_.assert_called_once_with(1)
        for window in windows:
            window.close.assert_called_once()
        self.assertEqual(app.engine.started, [])

    def test_cannot_change_point_while_paused(self):
        app = self.controller
        app.paused_config = core.ClickConfig(100, "left", None)
        app.capturePosition_(None)
        self.assertEqual(app.selection_windows, [])

    def test_closing_during_selection_does_not_restore_window(self):
        app = self.controller
        window = Mock()
        app.selection_windows = [window]
        app._ui_smoke_mode = True
        app.event_timer = Mock()
        app.windowWillClose_(None)
        window.close.assert_called_once()
        app.show.assert_not_called()
        app.event_timer.invalidate.assert_called_once()
