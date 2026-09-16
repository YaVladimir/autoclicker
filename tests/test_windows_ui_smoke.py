"""Opt-in Windows GUI checks; never emit mouse input or write user settings."""

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt" and os.environ.get("RUN_WINDOWS_UI_SMOKE") == "1",
                     "set RUN_WINDOWS_UI_SMOKE=1 on a Windows desktop")
class WindowsLayoutTests(unittest.TestCase):
    def make_app(self, scale=1.0):
        import customtkinter as ctk
        import autoclicker
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = patch.object(autoclicker, "SETTINGS_PATH", Path(temporary.name) / "settings.json")
        settings.start()
        self.addCleanup(settings.stop)
        dpi = patch.object(ctk.ScalingTracker, "get_window_dpi_scaling", return_value=scale)
        dpi.start()
        self.addCleanup(dpi.stop)
        root = ctk.CTk()
        app = autoclicker.AutoClickerApp(root, enable_hotkeys=False)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        self.addCleanup(lambda: self.assertEqual(errors, [], "GUI callback failed"))
        return root, app

    def assert_inside(self, widget, container):
        self.assertTrue(widget.winfo_ismapped())
        self.assertGreaterEqual(widget.winfo_rootx(), container.winfo_rootx())
        self.assertGreaterEqual(widget.winfo_rooty(), container.winfo_rooty())
        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), container.winfo_rootx() + container.winfo_width())
        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), container.winfo_rooty() + container.winfo_height())

    def test_controls_fit_at_different_scales_and_short_window(self):
        for scale in (1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                root, app = self.make_app(scale)
                try:
                    root.update()
                    self.assertFalse(app.cookie_body.winfo_ismapped())
                    self.assertFalse(app.capture_button.winfo_ismapped())
                    for widget in (*app.speed_buttons, app.start_button, app.stop_button):
                        self.assert_inside(widget, root)
                    if app.settings_pane.content.winfo_height() <= app.form_canvas.winfo_height():
                        self.assertEqual(app.form_canvas.yview(), (0.0, 1.0))
                    else:
                        # Hosted Windows desktops can cap even a 100% window.
                        app.form_canvas.yview_moveto(1)
                        root.update()
                        self.assert_inside(app.cookie_summary, app.form_canvas)
                        app.form_canvas.yview_moveto(0)
                    app._toggle_cookies()
                    app.target_fixed.invoke()
                    root.geometry("420x480")
                    root.update()
                    self.assert_inside(app.start_button, root)
                    self.assert_inside(app.stop_button, root)
                    app.form_canvas.yview_moveto(1)
                    root.update()
                    self.assert_inside(app.cookie_hint, app.form_canvas)
                    # On a short display at 200%, the button and hint need not
                    # fit together. Keyboard focus must reveal the button.
                    app.settings_pane._focus_changed(SimpleNamespace(widget=app.region_button))
                    root.update()
                    self.assert_inside(app.region_button, app.form_canvas)
                    self.assert_inside(app.start_button, root)
                    self.assert_inside(app.stop_button, root)
                    app._toggle_cookies()
                    app.target_cursor.invoke()
                    root.geometry("480x850")
                    root.update()
                    if app.settings_pane.content.winfo_height() <= app.form_canvas.winfo_height():
                        self.assertEqual(app.form_canvas.yview(), (0.0, 1.0))
                    else:
                        # At 200%, the real display may cap the enlarged window.
                        app.form_canvas.yview_moveto(0)
                        self.assertEqual(app.form_canvas.yview()[0], 0)
                finally:
                    app.close()

    def test_controls_themes_and_preferences(self):
        import customtkinter as ctk
        from windows_ui import load_appearance
        root, app = self.make_app()
        try:
            root.update()
            app.speed_buttons[1].invoke()
            self.assertEqual(app.cps_var.get(), "20")
            self.assertEqual(app.speed_slider.get(), 20)
            app.cps_var.set("20,5")
            self.assertIn("20.5", app.speed_summary.cget("text"))
            app.cps_var.set("")
            self.assertIn("Проверьте", app.speed_summary.cget("text"))
            app.cps_var.set("100")
            app.mouse_buttons[1].invoke()
            self.assertEqual(app.button_var.get(), "right")
            app.golden_check.select()
            app.wrath_check.select()
            self.assertIn("золотые и красные", app.cookie_summary.cget("text"))
            app._toggle_appearance()
            for theme in ("Тёмная", "Светлая", "Системная"):
                app.theme_var.set(theme)
                app.accent_var.set("Фиолетовый")
                app._change_appearance()
                root.update()
                self.assertEqual(load_appearance(app.appearance_path), {"theme": theme, "accent": "Фиолетовый"})
                if theme != "Системная":
                    self.assertEqual(ctk.get_appearance_mode(), "Dark" if theme == "Тёмная" else "Light")
                self.assert_inside(app.stop_button, root)
        finally:
            app.close()

    def test_countdown_pause_resume_stop_and_validation(self):
        import autoclicker
        class Engine:
            running = False
            def start(self, config):
                self.config, self.running = config, True
                return True
            def stop(self):
                self.running = False
        root, app = self.make_app()
        app.engine = Engine()
        try:
            app.start_button.invoke()
            self.assertIsNotNone(app.countdown_id)
            self.assertIn("Отменить", app.start_button.cget("text"))
            self.assertEqual(app.speed_slider.cget("state"), "disabled")
            app.start_button.invoke()
            self.assertIsNone(app.countdown_id)
            self.assertFalse(app.engine.running)
            app.toggle()
            self.assertTrue(app.engine.running)
            self.assertEqual(app.engine.config.cps, 100)
            app.toggle()
            self.assertFalse(app.engine.running)
            self.assertIsNotNone(app.paused_config)
            self.assertEqual(app.cps.cget("state"), "disabled")
            app.toggle()
            self.assertTrue(app.engine.running)
            app.stop_button.invoke()
            self.assertIsNone(app.paused_config)
            self.assertEqual(app.cps.cget("state"), "normal")
            app.cps_var.set("invalid")
            with patch.object(autoclicker.messagebox, "showerror") as error:
                app.start()
                error.assert_called_once()
            self.assertFalse(app.engine.running)
            app.cps_var.set("100")
            app.target_fixed.invoke()
            with patch.object(autoclicker.messagebox, "showwarning") as warning:
                app.start()
                warning.assert_called_once()
            self.assertFalse(app.engine.running)
        finally:
            app.close()

    def test_screen_selection_and_wrath_only_watcher(self):
        import autoclicker
        root, app = self.make_app()
        try:
            app.capture_position()
            root.update()
            with patch.object(app, "_cursor_position", return_value=(-250, 400)):
                app._selection_press(SimpleNamespace(x=10, y=10))
            self.assertEqual(app.fixed_position, (-250, 400))
            self.assertEqual(app.target_var.get(), "fixed")
            app.capture_region()
            with patch.object(app, "_cursor_position", side_effect=[(-800, 100), (-100, 600)]):
                app._selection_press(SimpleNamespace(x=10, y=10))
                app._selection_release(SimpleNamespace(x=710, y=510))
            self.assertEqual(app.game_region, autoclicker.ScreenRegion(-800, 100, 700, 500))
            self.assertTrue(app._cookie_expanded)
            app.wrath_var.set(True)
            app.golden_var.set(False)
            config = autoclicker.ClickConfig(100, "right", (-250, 400))
            with patch.object(autoclicker, "GoldenCookieWatcher") as watcher:
                app._start_golden_watcher(config)
                finder = watcher.call_args.kwargs["finder"]
                self.assertTrue(finder.include_wrath)
                self.assertFalse(finder.include_golden)
            app.golden_watcher = None
        finally:
            app.close()
