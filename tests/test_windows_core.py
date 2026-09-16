"""Windows-only checks that never emit real mouse input."""

from __future__ import annotations

import os
import queue
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(os.name == "nt", "Windows input helpers require user32")
class GoldenClickTests(unittest.TestCase):
    def test_virtual_screen_geometry_uses_absolute_negative_coordinates(self) -> None:
        import autoclicker

        self.assertEqual(autoclicker.virtual_screen_geometry(-2560, -200, 5120, 1600), "5120x1600+-2560+-200")

    def test_golden_cookie_always_uses_left_button(self) -> None:
        import autoclicker

        with patch.object(autoclicker, "click_then_restore") as click:
            autoclicker.click_golden_cookie((320, 240), (100, 120))

        click.assert_called_once_with("left", (320, 240), (100, 120))

    def test_click_and_cursor_restore_share_one_critical_section(self) -> None:
        import autoclicker

        operations: list[tuple[str, object]] = []
        with (
            patch.object(autoclicker.user32, "SetCursorPos", side_effect=lambda *point: operations.append(("move", point))),
            patch.object(autoclicker, "_emit_mouse_click", side_effect=lambda button: operations.append(("click", button))),
        ):
            autoclicker.click_then_restore("left", (320, 240), (100, 120))

        self.assertEqual(
            operations,
            [("move", (320, 240)), ("click", "left"), ("move", (100, 120))],
        )

    def test_cursor_mode_restores_current_position_for_each_cookie_under_lock(self) -> None:
        import autoclicker

        operations = []
        positions = iter([(-100, 120), (200, 300)])

        def read_cursor(pointer):
            self.assertTrue(autoclicker.MOUSE_LOCK.locked())
            pointer._obj.x, pointer._obj.y = next(positions)
            operations.append(("read", None))
            return 1

        def record(kind, value):
            self.assertTrue(autoclicker.MOUSE_LOCK.locked())
            operations.append((kind, value))

        with (
            patch.object(autoclicker.user32, "GetCursorPos", side_effect=read_cursor),
            patch.object(autoclicker.user32, "SetCursorPos", side_effect=lambda *point: record("move", point)),
            patch.object(autoclicker, "_emit_mouse_click", side_effect=lambda button: record("click", button)),
        ):
            autoclicker.click_golden_cookie((320, 240), None)
            autoclicker.click_golden_cookie((400, 500), None)

        self.assertEqual(operations, [
            ("read", None), ("move", (320, 240)), ("click", "left"), ("move", (-100, 120)),
            ("read", None), ("move", (400, 500)), ("click", "left"), ("move", (200, 300)),
        ])

    def test_unknown_cursor_position_does_not_move_or_click(self) -> None:
        import autoclicker

        with (
            patch.object(autoclicker.user32, "GetCursorPos", return_value=0),
            patch.object(autoclicker.user32, "SetCursorPos") as move,
            patch.object(autoclicker, "_emit_mouse_click") as click,
        ):
            autoclicker.click_golden_cookie((320, 240), None)
        move.assert_not_called()
        click.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Windows interface requires user32")
class GoldenStartTests(unittest.TestCase):
    def make_app(self, *, golden=True, wrath=False, target="cursor", position=None):
        import autoclicker

        app = autoclicker.AutoClickerApp.__new__(autoclicker.AutoClickerApp)
        for name, value in (("cps", "100"), ("delay", "0"), ("button", "left"),
                            ("golden", golden), ("wrath", wrath), ("target", target)):
            setattr(app, name + "_var", Mock(get=Mock(return_value=value)))
        app.fixed_position = position
        app.game_region = autoclicker.ScreenRegion(0, 0, 800, 600)
        app.root = Mock()
        app.engine = Mock(running=False)
        app.selection_overlay = None
        app.countdown_id = app.paused_config = None
        app._set_controls = Mock()
        app.stop_button = Mock()
        app._begin = Mock()
        app._countdown = Mock()
        for name in ("missing_dependencies", "save_click_preferences"):
            mocked = patch.object(autoclicker, name, return_value=None)
            mocked.start()
            self.addCleanup(mocked.stop)
        return app

    def test_f6_starts_cursor_mode_with_either_cookie_kind_and_ignores_saved_point(self):
        import autoclicker

        for golden, wrath in ((True, False), (False, True), (True, True)):
            for position in (None, (100, 120)):
                with self.subTest(golden=golden, wrath=wrath, position=position):
                    app = self.make_app(golden=golden, wrath=wrath, position=position)
                    with patch.object(autoclicker.messagebox, "showwarning") as warning:
                        app.toggle()
                    warning.assert_not_called()
                    app.target_var.set.assert_not_called()
                    app._begin.assert_called_once_with(autoclicker.ClickConfig(100, "left", None))
                    app._countdown.assert_not_called()
                    self.assertTrue(app._golden_pending)

    def test_cursor_mode_button_start_keeps_three_second_delay(self):
        import autoclicker

        app = self.make_app()
        app.start(from_button=True)
        app._begin.assert_not_called()
        app._countdown.assert_called_once_with(autoclicker.ClickConfig(100, "left", None), 3)

    def test_fixed_mode_still_requires_and_uses_selected_point(self):
        import autoclicker

        app = self.make_app(target="fixed")
        with patch.object(autoclicker.messagebox, "showwarning") as warning:
            app.start()
        warning.assert_called_once()
        app._begin.assert_not_called()
        app.fixed_position = (100, 120)
        app.start()
        app._begin.assert_called_once_with(autoclicker.ClickConfig(100, "left", (100, 120)))

    def test_watcher_runs_in_cursor_mode_and_passes_dynamic_restore(self):
        import autoclicker

        app = self.make_app()
        app._golden_session = 0
        app.golden_events = queue.SimpleQueue()
        app.detail_var = Mock()
        with (
            patch.object(autoclicker, "GoldenCookieWatcher") as watcher,
            patch.object(autoclicker, "click_golden_cookie") as click,
        ):
            app._start_golden_watcher(autoclicker.ClickConfig(100, "right", None))
            watcher.return_value.start.assert_called_once()
            watcher.call_args.args[1]((320, 240))
            click.assert_called_once_with((320, 240), None)


@unittest.skipUnless(os.name == "nt", "Windows interface requires user32")
class GoldenStatusTests(unittest.TestCase):
    def test_active_search_error_keeps_normal_clicking_status(self) -> None:
        import autoclicker

        class Value:
            def __init__(self) -> None:
                self.value = ""

            def set(self, value: str) -> None:
                self.value = value

        class Engine:
            running = True

        class Root:
            def after(self, delay: int, callback: object) -> None:
                pass

        app = autoclicker.AutoClickerApp.__new__(autoclicker.AutoClickerApp)
        app._golden_session = 8
        app.golden_watcher = object()
        app.golden_events = queue.SimpleQueue()
        app.golden_events.put((7, "golden-error", "устаревшая ошибка"))
        app.golden_events.put((8, "golden-error", "текущая ошибка"))
        app.engine = Engine()
        app.status_var = Value()
        app.detail_var = Value()
        app.root = Root()

        app._poll_golden_events()

        self.assertEqual(app.status_var.value, "РАБОТАЕТ")
        self.assertEqual(app.detail_var.value, "Обычные клики продолжаются. текущая ошибка")
        self.assertIsNone(app.golden_watcher)


if __name__ == "__main__":
    unittest.main()
