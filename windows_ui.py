"""CustomTkinter presentation for the Windows app; clicking stays in autoclicker.py."""

from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk

import customtkinter as ctk


BACKGROUND = ("#F4F5F7", "#1A1C20")
PANEL = ("#FFFFFF", "#24262C")
TEXT = ("#20242D", "#F0F1F5")
MUTED = ("#626873", "#A9ADB9")
LINE = ("#DEE2E9", "#3B3F49")
TRACK = ("#E7EAF0", "#32353E")
ON_ACCENT = ("#FFFFFF", "#101B25")
ACCENTS = {
    "Синий": (("#315CDA", "#87A5FF"), ("#264CBF", "#A3BAFF"), ("#EAF0FF", "#303D60")),
    "Фиолетовый": (("#7043C4", "#BAA0FF"), ("#5E35AB", "#CBB7FF"), ("#F2EBFF", "#403457")),
    "Зелёный": (("#21705B", "#79D6BA"), ("#195B49", "#9AE3CD"), ("#E5F3ED", "#263F37")),
}
THEMES = {"Системная": "system", "Светлая": "light", "Тёмная": "dark"}


def load_appearance(path: Path) -> dict[str, str]:
    defaults = {"theme": "Системная", "accent": "Синий"}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults
    if isinstance(saved, dict):
        for key, choices in (("theme", THEMES), ("accent", ACCENTS)):
            if isinstance(saved.get(key), str) and saved[key] in choices:
                defaults[key] = saved[key]
    return defaults


class SettingsPane(ctk.CTkFrame):
    """A DPI-aware form with a scrollbar that disappears when everything fits."""

    def __init__(self, master):
        super().__init__(master, fg_color=BACKGROUND, corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, yscrollincrement=1,
                                background=self._apply_appearance_mode(BACKGROUND))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ctk.CTkScrollbar(self, width=10, command=self.canvas.yview,
                                          fg_color=BACKGROUND, button_color=LINE, button_hover_color=MUTED)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self._scroll_changed)
        self.content = ctk.CTkFrame(self.canvas, fg_color=BACKGROUND, bg_color=BACKGROUND, corner_radius=0)
        self.window_id = self.canvas.create_window(0, 0, anchor="nw", window=self.content)
        self.content.bind("<Configure>", self._content_resized)
        self.canvas.bind("<Configure>", self._canvas_resized)
        self.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")
        self.winfo_toplevel().bind("<FocusIn>", self._focus_changed, add="+")

    def _scroll_changed(self, first, last):
        self.scrollbar.set(first, last)
        # Keep the narrow gutter to prevent the form changing width at the threshold.
        color = BACKGROUND if float(first) <= 0 and float(last) >= 1 else LINE
        self.scrollbar.configure(button_color=color, button_hover_color=color if color == BACKGROUND else MUTED)

    def _content_resized(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self.content.winfo_height() <= self.canvas.winfo_height():
            self.canvas.yview_moveto(0)

    def _canvas_resized(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        self._content_resized()

    def _contains(self, widget):
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _wheel(self, event):
        if self._contains(event.widget) and self.content.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta / 120) * 30, "units")

    def _focus_changed(self, event):
        if not self._contains(event.widget):
            return
        top = event.widget.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        delta = top - 8 if top < 0 else bottom - self.canvas.winfo_height() + 8 if bottom > self.canvas.winfo_height() else 0
        if delta:
            offset = self.canvas.canvasy(0) + delta
            self.canvas.yview_moveto(max(0, offset) / max(1, self.content.winfo_height()))

    def _set_appearance_mode(self, mode_string):
        super()._set_appearance_mode(mode_string)
        if hasattr(self, "canvas"):
            self.canvas.configure(background=self._apply_appearance_mode(BACKGROUND))


class WindowsInterface:
    def _build(self) -> None:
        appearance = load_appearance(self.appearance_path)
        self.theme_var = tk.StringVar(master=self.root, value=appearance["theme"])
        self.accent_var = tk.StringVar(master=self.root, value=appearance["accent"])
        self._cookie_expanded = False
        self._appearance_expanded = False
        self._accent_controls = []
        self._secondary_controls = []
        self.root.title("Автокликер")
        self.root.configure(fg_color=BACKGROUND)
        ctk.set_appearance_mode(THEMES[appearance["theme"]])
        self.root.resizable(True, True)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.root, fg_color=BACKGROUND, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 14))
        header.grid_columnconfigure(0, weight=1)
        self._label(header, "Автокликер", size=26, bold=True).grid(row=0, column=0, sticky="w")
        self.appearance_button = self._button(header, "Вид", self._toggle_appearance, width=56, height=30)
        self.appearance_button.grid(row=0, column=1, sticky="e")
        self._label(header, "Ваш ритм. Ни одного лишнего клика.", size=12, muted=True).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.appearance_panel = ctk.CTkFrame(header, fg_color=BACKGROUND)
        self.appearance_panel.grid_columnconfigure((0, 1), weight=1, uniform="appearance")
        self._label(self.appearance_panel, "Тема", size=12, muted=True).grid(row=0, column=0, sticky="w")
        self._label(self.appearance_panel, "Акцент", size=12, muted=True).grid(row=0, column=1, sticky="w", padx=(10, 0))
        for column, variable, values in ((0, self.theme_var, THEMES), (1, self.accent_var, ACCENTS)):
            menu = ctk.CTkOptionMenu(self.appearance_panel, variable=variable, values=list(values),
                                     command=self._change_appearance, width=120, height=32, font=("Segoe UI", 13),
                                     fg_color=PANEL, button_color=TRACK, button_hover_color=LINE, text_color=TEXT,
                                     dropdown_fg_color=PANEL, dropdown_text_color=TEXT, dropdown_hover_color=TRACK)
            menu.grid(row=1, column=column, sticky="ew", padx=(10 if column else 0, 0), pady=(4, 0))

        self.settings_pane = SettingsPane(self.root)
        self.settings_pane.grid(row=1, column=0, sticky="nsew", padx=(24, 14))
        self.form_canvas = self.settings_pane.canvas
        body = self.settings_pane.content
        body.grid_columnconfigure(0, weight=1)

        speed = ctk.CTkFrame(body, fg_color=PANEL, border_width=1, border_color=LINE, corner_radius=14)
        speed.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        speed.grid_columnconfigure(0, weight=1)
        self._label(speed, "Скорость", bold=True).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        value_row = ctk.CTkFrame(speed, fg_color="transparent")
        value_row.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 4))
        self.cps = ctk.CTkEntry(value_row, textvariable=self.cps_var, width=114, height=60,
                               font=("Segoe UI", 44, "bold"), fg_color=PANEL, border_width=0,
                               text_color=TEXT, corner_radius=5)
        self.cps.pack(side="left")
        self._label(value_row, "кликов / сек", muted=True).pack(side="left", padx=(4, 0), pady=(20, 0))
        self.speed_slider = ctk.CTkSlider(speed, from_=1, to=100, number_of_steps=99, height=20,
                                         command=lambda value: self.cps_var.set(str(round(value))), fg_color=TRACK)
        self.speed_slider.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        presets = ctk.CTkFrame(speed, fg_color="transparent")
        presets.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 16))
        presets.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="presets")
        self.speed_buttons = []
        for column, value in enumerate((10, 20, 50, 100)):
            button = self._button(presets, str(value), lambda item=value: self.cps_var.set(str(item)), width=50, height=30)
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 7, 0))
            self.speed_buttons.append(button)

        self._label(body, "Куда кликать", bold=True).grid(row=1, column=0, sticky="w")
        target, controls = self._segments(body, self.target_var, (("Под курсором", "cursor"), ("В точке", "fixed")))
        target.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        self.target_cursor, self.target_fixed = controls
        self.point_row = ctk.CTkFrame(body, fg_color="transparent")
        self.point_row.grid_columnconfigure(0, weight=1)
        self.capture_button = self._button(self.point_row, "Выбрать точку     F7", self.capture_position)
        self.capture_button.grid(row=0, column=0, sticky="ew")
        self.position_label = self._label(self.point_row, variable=self.position_var, size=12, muted=True)
        self.position_label.grid(row=1, column=0, sticky="w", pady=(5, 0))

        self._label(body, "Кнопка мыши", bold=True).grid(row=4, column=0, sticky="w", pady=(16, 0))
        mouse, self.mouse_buttons = self._segments(body, self.button_var, (("Левая", "left"), ("Правая", "right"), ("Средняя", "middle")))
        mouse.grid(row=5, column=0, sticky="ew", pady=(7, 0))
        delay_row = ctk.CTkFrame(body, fg_color="transparent")
        delay_row.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        delay_row.grid_columnconfigure(0, weight=1)
        self._label(delay_row, "Задержка старта", bold=True).grid(row=0, column=0, sticky="w")
        self.delay = ctk.CTkEntry(delay_row, textvariable=self.delay_var, width=62, height=32, font=("Segoe UI", 14),
                                 fg_color=PANEL, text_color=TEXT, border_color=LINE, border_width=1, corner_radius=8)
        self.delay.grid(row=0, column=1)
        self._label(delay_row, "сек", muted=True).grid(row=0, column=2, padx=(8, 0))
        self.delay_hint = self._label(body, size=12, muted=True)
        self.delay_hint.grid(row=7, column=0, sticky="ew", pady=(7, 0))

        self.cookie_card = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=12, border_width=1, border_color=LINE)
        self.cookie_card.grid(row=8, column=0, sticky="ew", pady=(18, 12))
        self.cookie_card.grid_columnconfigure(0, weight=1)
        self.cookie_button = self._button(self.cookie_card, "Cookie Clicker     +", self._toggle_cookies, height=38, anchor="w")
        self.cookie_button.grid(row=0, column=0, sticky="ew", padx=9, pady=(7, 0))
        self.cookie_summary = self._label(self.cookie_card, "Автоматический сбор печенек", size=12, muted=True)
        self.cookie_summary.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))
        self.cookie_body = ctk.CTkFrame(self.cookie_card, fg_color="transparent")
        self.cookie_body.grid_columnconfigure(0, weight=1)
        self.golden_check = ctk.CTkSwitch(self.cookie_body, text="Золотые печеньки", variable=self.golden_var,
                                          font=("Segoe UI", 13), text_color=TEXT, fg_color=TRACK, height=32)
        self.golden_check.grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.wrath_check = ctk.CTkSwitch(self.cookie_body, text="Красные печеньки", variable=self.wrath_var,
                                         font=("Segoe UI", 13), text_color=TEXT, fg_color=TRACK, height=32)
        self.wrath_check.grid(row=1, column=0, sticky="w", pady=(0, 10))
        self.region_button = self._button(self.cookie_body, "Выбрать область игры     F9", self.capture_region)
        self.region_button.grid(row=2, column=0, sticky="ew")
        self.region_label = self._label(self.cookie_body, variable=self.region_var, size=12, muted=True)
        self.region_label.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.cookie_hint = self._label(self.cookie_body, "Выберите основное печенье клавишей F7: после сбора курсор вернётся к нему.", size=12, muted=True)
        self.cookie_hint.grid(row=4, column=0, sticky="ew", pady=(8, 0))

        footer = ctk.CTkFrame(self.root, fg_color=PANEL, corner_radius=0)
        footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        footer.grid_columnconfigure(0, weight=1)
        status_row = ctk.CTkFrame(footer, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="ew", padx=24, pady=(14, 0))
        status_row.grid_columnconfigure(1, weight=1)
        self.status_label = self._label(status_row, "●  Готов к запуску", size=12, bold=True)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.speed_summary = self._label(status_row, size=12, muted=True)
        self.speed_summary.grid(row=0, column=1, sticky="e")
        self.detail_label = self._label(footer, variable=self.detail_var, size=12, muted=True)
        self.detail_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(4, 0))
        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=24, pady=(12, 0))
        actions.grid_columnconfigure(0, weight=1)
        self.start_button = self._button(actions, "Запустить     F6", lambda: self.toggle(from_button=True), height=44, bold=True)
        self.start_button.grid(row=0, column=0, sticky="ew")
        self._accent_controls.append(self.start_button)
        self.stop_button = self._button(actions, "Стоп   F8", self.stop, width=100, height=44)
        self.stop_button.grid(row=0, column=1, padx=(9, 0))
        self.stop_button.configure(state="disabled")
        self._label(footer, "F6  старт / пауза     ·     F7  точка     ·     F9  область", size=11, muted=True).grid(row=3, column=0, pady=(9, 14))
        self.setting_controls = [self.cps, self.delay, self.speed_slider, self.capture_button,
                                 self.target_cursor, self.target_fixed, *self.mouse_buttons, *self.speed_buttons,
                                 self.golden_check, self.wrath_check, self.region_button]
        self._wrapped = (self.delay_hint, self.position_label, self.region_label, self.cookie_hint)
        body.bind("<Configure>", self._wrap_form, add="+")
        footer.bind("<Configure>", lambda event: self.detail_label.configure(wraplength=max(160, int(event.width / ctk.ScalingTracker.get_widget_scaling(footer)) - 48)))
        for variable in (self.cps_var, self.button_var, self.target_var, self.delay_var, self.golden_var, self.wrath_var):
            variable.trace_add("write", self._sync_settings)
        self.status_var.trace_add("write", self._sync_status)
        self.region_var.trace_add("write", self._region_changed)
        self._change_appearance(save=False)
        self._sync_status()
        self.root.update_idletasks()
        window_scale = ctk.ScalingTracker.get_window_scaling(self.root)
        widget_scale = ctk.ScalingTracker.get_widget_scaling(self.root)
        width = min(480, int((self.root.winfo_screenwidth() - 60) / window_scale))
        # Measure the default form so it fits without scrolling on a normal screen.
        wanted_height = (header.winfo_reqheight() + body.winfo_reqheight() + footer.winfo_reqheight()) / window_scale + 50 * widget_scale / window_scale
        height = min(round(wanted_height), int((self.root.winfo_screenheight() - 100) / window_scale))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(width, 420), min(height, 480))

    def _label(self, master, text="", *, variable=None, size=13, bold=False, muted=False):
        return ctk.CTkLabel(master, text=text, textvariable=variable, font=("Segoe UI", size, "bold" if bold else "normal"),
                            text_color=MUTED if muted else TEXT, anchor="w", justify="left", height=20)

    def _button(self, master, text, command, *, width=100, height=36, bold=False, anchor="center"):
        button = ctk.CTkButton(master, text=text, command=command, width=width, height=height,
                               font=("Segoe UI", 13, "bold" if bold else "normal"), fg_color=PANEL,
                               hover_color=TRACK, text_color=TEXT, text_color_disabled=MUTED,
                               border_color=LINE, border_width=1, corner_radius=8, anchor=anchor)
        self._secondary_controls.append(button)
        # CTk buttons draw on a Canvas. Make that surface reachable with Tab too.
        button._canvas.configure(takefocus=1)
        button.bind("<Return>", lambda event: button.invoke())
        button.bind("<space>", lambda event: button.invoke())
        button.bind("<FocusIn>", lambda event: button.configure(border_color=ACCENTS[self.accent_var.get()][0], border_width=2))
        button.bind("<FocusOut>", lambda event: self._sync_settings())
        return button

    def _segments(self, master, variable, options):
        frame = ctk.CTkFrame(master, fg_color=TRACK, corner_radius=10)
        controls = []
        for column, (label, value) in enumerate(options):
            frame.grid_columnconfigure(column, weight=1, uniform="segments")
            button = self._button(frame, label, lambda item=value: variable.set(item), width=70, height=34)
            button.grid(row=0, column=column, sticky="ew", padx=3, pady=3)
            button.selection = (variable, value)
            controls.append(button)
        return frame, controls

    def _wrap_form(self, _event=None):
        width = self.settings_pane.content.winfo_width() / ctk.ScalingTracker.get_widget_scaling(self.root)
        for label in self._wrapped:
            label.configure(wraplength=max(140, int(width) - (40 if label in (self.region_label, self.cookie_hint) else 4)))

    def _toggle_appearance(self):
        self._appearance_expanded = not self._appearance_expanded
        if self._appearance_expanded:
            self.appearance_panel.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        else:
            self.appearance_panel.grid_remove()

    def _toggle_cookies(self):
        self._cookie_expanded = not self._cookie_expanded
        self.cookie_button.configure(text="Cookie Clicker     −" if self._cookie_expanded else "Cookie Clicker     +")
        if self._cookie_expanded:
            self.cookie_body.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 16))
        else:
            self.cookie_body.grid_remove()

    def _region_changed(self, *_):
        if self.game_region is not None and not self._cookie_expanded:
            self._toggle_cookies()

    def _change_appearance(self, _value=None, *, save=True):
        ctk.set_appearance_mode(THEMES[self.theme_var.get()])
        accent, hover, _soft = ACCENTS[self.accent_var.get()]
        for control in self._accent_controls:
            control.configure(fg_color=accent, hover_color=hover, text_color=ON_ACCENT, border_color=accent)
        self.speed_slider.configure(progress_color=accent, button_color=accent, button_hover_color=hover)
        for control in (self.golden_check, self.wrath_check):
            control.configure(progress_color=accent, button_color=("#FFFFFF", "#F0F1F5"), button_hover_color=("#F4F5F7", "#FFFFFF"))
        self._sync_settings()
        if save:
            try:
                self.appearance_path.parent.mkdir(parents=True, exist_ok=True)
                self.appearance_path.write_text(json.dumps({"theme": self.theme_var.get(), "accent": self.accent_var.get()}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                self.detail_var.set("Оформление изменено, но сохранить его на диск не удалось")

    def _sync_settings(self, *_):
        accent, _hover, soft = ACCENTS[self.accent_var.get()]
        for control in self._secondary_controls:
            if control in self._accent_controls:
                continue
            control.configure(fg_color=PANEL, text_color=TEXT, border_color=LINE, border_width=1)
            if hasattr(control, "selection"):
                variable, value = control.selection
                selected = variable.get() == value
                control.configure(fg_color=PANEL if selected else TRACK, text_color=TEXT if selected else MUTED,
                                  border_color=LINE if selected else TRACK)
        try:
            cps = float(self.cps_var.get().replace(",", "."))
        except ValueError:
            cps = 0
        if 1 <= cps <= 100:
            self.speed_slider.set(cps)
        for button, value in zip(self.speed_buttons, (10, 20, 50, 100)):
            if cps == value:
                button.configure(fg_color=soft, text_color=accent, border_color=accent)
        mouse = {"left": "Левая", "right": "Правая", "middle": "Средняя"}.get(self.button_var.get(), "")
        self.speed_summary.configure(text=f"{cps:g} кликов/с · {mouse}" if 1 <= cps <= 100 else "Проверьте скорость")
        if self.target_var.get() == "fixed":
            self.point_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        else:
            self.point_row.grid_remove()
        try:
            delay = float(self.delay_var.get().replace(",", "."))
        except ValueError:
            delay = -1
        hint = "Задержка: от 0 до 10 секунд."
        if delay == 0:
            hint = "При запуске кнопкой — 3 сек, чтобы навести курсор." if self.target_var.get() == "cursor" else "Клики начнутся сразу в выбранной точке."
        elif 0 < delay <= 10:
            hint = f"Запуск через {delay:g} сек после нажатия."
        self.delay_hint.configure(text=hint)
        kinds = [label for enabled, label in ((self.golden_var.get(), "золотые"), (self.wrath_var.get(), "красные")) if enabled]
        self.cookie_summary.configure(text="Сбор: " + " и ".join(kinds) if kinds else "Автоматический сбор печенек")

    def _sync_status(self, *_):
        states = {
            "ГОТОВ": ("Готов к запуску", ("#23734D", "#86D7AA")),
            "РАБОТАЕТ": ("Работает", ("#23734D", "#86D7AA")),
            "НА ПАУЗЕ": ("На паузе", ("#98641C", "#EDBC74")),
            "СТАРТ ЧЕРЕЗ…": ("Подготовка…", ("#315CDA", "#87A5FF")),
        }
        text, color = states.get(self.status_var.get(), (self.status_var.get(), TEXT))
        self.status_label.configure(text="●  " + text, text_color=color)
