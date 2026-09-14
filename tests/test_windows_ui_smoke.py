"""Opt-in layout checks on a Windows desktop; never emit mouse clicks."""

import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt" and os.environ.get("RUN_WINDOWS_UI_SMOKE") == "1",
                     "set RUN_WINDOWS_UI_SMOKE=1 on a Windows desktop")
class WindowsLayoutTests(unittest.TestCase):
    def test_controls_fit_at_different_scales_and_short_window(self) -> None:
        import tkinter as tk
        import autoclicker

        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                root = tk.Tk()
                root.tk.call("tk", "scaling", 96 / 72 * scale)
                app = autoclicker.AutoClickerApp(root, enable_hotkeys=False)
                try:
                    root.update()
                    for widget in (*app.speed_buttons, app.golden_check, app.wrath_check,
                                   app.start_button, app.stop_button):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertGreaterEqual(widget.winfo_rootx(), root.winfo_rootx())
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                             root.winfo_rootx() + root.winfo_width())
                    self.assertLessEqual(app.stop_button.winfo_rooty() + app.stop_button.winfo_height(),
                                         root.winfo_rooty() + root.winfo_height())
                    app.speed_buttons[-1].invoke()
                    self.assertEqual(app.cps_var.get(), "100")
                    root.geometry(f"{root.winfo_width()}x{root.minsize()[1]}")
                    root.update()
                    self.assertLessEqual(app.stop_button.winfo_rooty() + app.stop_button.winfo_height(),
                                         root.winfo_rooty() + root.winfo_height())
                    app.form_canvas.yview_moveto(1)
                    root.update()
                    self.assertGreaterEqual(app.wrath_check.winfo_rooty(), app.form_canvas.winfo_rooty())
                    self.assertLessEqual(app.region_button.winfo_rooty() + app.region_button.winfo_height(),
                                         app.form_canvas.winfo_rooty() + app.form_canvas.winfo_height())
                    app.wrath_var.set(True)
                    app.golden_var.set(False)
                    app.game_region = autoclicker.ScreenRegion(0, 0, 800, 600)
                    config = autoclicker.ClickConfig(100, "left", (100, 100))
                    with patch.object(autoclicker, "GoldenCookieWatcher") as watcher:
                        app._start_golden_watcher(config)
                        finder = watcher.call_args.kwargs["finder"]
                        self.assertTrue(finder.include_wrath)
                        self.assertFalse(finder.include_golden)
                    app.golden_watcher = None
                finally:
                    app.close()
