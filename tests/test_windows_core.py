"""Windows-only checks that never emit real mouse input."""

from __future__ import annotations

import os
import queue
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt", "Windows input helpers require user32")
class GoldenClickTests(unittest.TestCase):
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
