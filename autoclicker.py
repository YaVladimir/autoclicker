"""Windows interface for the Cookie Clicker Autoclicker."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from golden_cookie_detector import GoldenCookieFinder, GoldenCookieWatcher, ScreenRegion, detector_self_check, missing_dependencies


if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR))


class INPUT_UNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT),)


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = (("type", ctypes.c_ulong), ("union", INPUT_UNION))


class POINT(ctypes.Structure):
    _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))


INPUT_MOUSE = 0
MOUSE_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
VK_F6, VK_F7, VK_F8, VK_F9 = 0x75, 0x76, 0x77, 0x78
DEFAULT_CLICK_PREFERENCES = {"cps": "100", "delay": "0", "mouse_button": "left"}
SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Autoclicker" / "settings.json"
MOUSE_LOCK = threading.Lock()
user32 = ctypes.windll.user32
user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)


def _enable_dpi_awareness() -> None:
    """Keep screenshot pixels and mouse coordinates identical on scaled displays."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # Per-monitor v2
    except AttributeError:
        try:
            user32.SetProcessDPIAware()
        except AttributeError:
            pass


_enable_dpi_awareness()


@dataclass(frozen=True)
class ClickConfig:
    cps: float
    mouse_button: str
    fixed_position: tuple[int, int] | None


def parse_settings(cps_text: str, delay_text: str) -> tuple[float, float]:
    try:
        cps = float(cps_text.replace(",", "."))
        delay = float(delay_text.replace(",", "."))
    except ValueError as exc:
        raise ValueError("Укажите скорость от 1 до 100 и задержку от 0 до 10.") from exc
    if not 1 <= cps <= 100:
        raise ValueError("Скорость должна быть от 1 до 100 кликов/с.")
    if not 0 <= delay <= 10:
        raise ValueError("Задержка должна быть от 0 до 10 секунд.")
    return cps, delay


def load_click_preferences() -> dict[str, str]:
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CLICK_PREFERENCES.copy()
    if not isinstance(saved, dict):
        return DEFAULT_CLICK_PREFERENCES.copy()
    cps_text, delay_text = str(saved.get("cps", "")), str(saved.get("delay", ""))
    if saved.get("mouse_button") not in {"left", "right", "middle"}:
        return DEFAULT_CLICK_PREFERENCES.copy()
    try:
        parse_settings(cps_text, delay_text)
    except ValueError:
        return DEFAULT_CLICK_PREFERENCES.copy()
    return {"cps": cps_text, "delay": delay_text, "mouse_button": str(saved["mouse_button"])}


def save_click_preferences(cps_text: str, delay_text: str, mouse_button: str) -> None:
    cps, delay = parse_settings(cps_text, delay_text)
    if mouse_button not in {"left", "right", "middle"}:
        raise ValueError("Неизвестная кнопка мыши.")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps({"cps": f"{cps:g}", "delay": f"{delay:g}", "mouse_button": mouse_button}, ensure_ascii=False),
        encoding="utf-8",
    )


def _emit_mouse_click(button: str) -> None:
    down, up = MOUSE_FLAGS[button]
    inputs = (INPUT * 2)(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dwFlags=down)), INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dwFlags=up)))
    user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


def send_mouse_click(button: str, position: tuple[int, int] | None) -> None:
    with MOUSE_LOCK:
        if position is not None:
            user32.SetCursorPos(*position)
        _emit_mouse_click(button)


def click_then_restore(button: str, target: tuple[int, int], restore: tuple[int, int]) -> None:
    """Click a transient target and leave the pointer on the main cookie."""
    with MOUSE_LOCK:
        user32.SetCursorPos(*target)
        try:
            _emit_mouse_click(button)
        finally:
            user32.SetCursorPos(*restore)


def click_golden_cookie(target: tuple[int, int], restore: tuple[int, int]) -> None:
    """Golden cookies always require a normal left click."""
    click_then_restore("left", target, restore)


class ClickEngine:
    def __init__(self, click_action: Callable[[str, tuple[int, int] | None], None]):
        self._click_action = click_action
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self, config: ClickConfig) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, args=(config,), daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=.35)

    def _run(self, config: ClickConfig) -> None:
        interval, next_click = 1 / config.cps, time.perf_counter()
        while not self._stop_event.is_set():
            self._click_action(config.mouse_button, config.fixed_position)
            next_click += interval
            now = time.perf_counter()
            if now - next_click > interval:
                next_click = now
            self._stop_event.wait(max(0, next_click - now))


class AutoClickerApp:
    def __init__(self, root: tk.Tk, *, enable_hotkeys: bool = True):
        self.root, self.engine = root, ClickEngine(send_mouse_click)
        self.fixed_position: tuple[int, int] | None = None
        self.game_region: ScreenRegion | None = None
        self.region_first_corner: tuple[int, int] | None = None
        self.golden_watcher: GoldenCookieWatcher | None = None
        self.golden_events: queue.SimpleQueue[tuple[int, str, object]] = queue.SimpleQueue()
        self._golden_session = 0
        self._golden_pending = False
        self.countdown_id: str | None = None
        self.key_state = {key: False for key in (VK_F6, VK_F7, VK_F8, VK_F9)}
        self.click_preferences = load_click_preferences()
        self.cps_var = tk.StringVar(value=self.click_preferences["cps"])
        self.delay_var = tk.StringVar(value=self.click_preferences["delay"])
        self.button_var = tk.StringVar(value=self.click_preferences["mouse_button"])
        self.target_var = tk.StringVar(value="cursor")
        self.golden_var = tk.BooleanVar(value=False)
        self.wrath_var = tk.BooleanVar(value=False)
        self.status_var, self.detail_var = tk.StringVar(value="ГОТОВ"), tk.StringVar(value="Наведите курсор на цель и нажмите F6")
        self.position_var = tk.StringVar(value="Точка ещё не выбрана")
        self.region_var = tk.StringVar(value="Игровая область ещё не выбрана")
        self._build()
        if enable_hotkeys:
            self.root.after(30, self._poll_hotkeys)
        self.root.after(100, self._poll_golden_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        self.root.title("Автокликер")
        self.root.resizable(True, True)
        shell = ttk.Frame(self.root, padding=16); shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Автокликер", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(shell, text="Для Cookie Clicker и других игр-кликеров").pack(anchor="w", pady=(0, 12))
        # Reserve the footer before allocating the scrollable settings area.
        # Start/Stop stay visible on small screens and at high Windows DPI.
        footer = ttk.Frame(shell); footer.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status_var, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        detail = ttk.Label(footer, textvariable=self.detail_var, wraplength=470)
        detail.pack(anchor="w", pady=(2, 8))
        row = ttk.Frame(footer); row.pack(fill="x")
        self.start_button = ttk.Button(row, text="Запустить  (F6)", command=self.toggle); self.start_button.pack(side="left", fill="x", expand=True)
        self.stop_button = ttk.Button(row, text="Стоп  (F8)", command=self.stop, state="disabled"); self.stop_button.pack(side="left", padx=(10, 0))
        shortcut = ttk.Label(footer, text="F6 — старт/пауза  •  F7 — точка  •  F8 — стоп  •  F9 — область", wraplength=470)
        shortcut.pack(anchor="w", pady=(8, 0))
        viewport = ttk.Frame(shell); viewport.pack(fill="both", expand=True)
        self.form_canvas = tk.Canvas(viewport, highlightthickness=0, borderwidth=0, background=self.root.cget("background"))
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.form_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.form_canvas.pack(side="left", fill="both", expand=True)
        self.form_canvas.configure(yscrollcommand=scrollbar.set)
        body = ttk.Frame(self.form_canvas, padding=(0, 0, 8, 0))
        form_id = self.form_canvas.create_window(0, 0, anchor="nw", window=body)
        body.bind("<Configure>", lambda event: self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")))
        settings = ttk.LabelFrame(body, text="Настройки", padding=12); settings.pack(fill="x")
        ttk.Label(settings, text="Кликов в секунду").grid(row=0, column=0, sticky="w")
        self.cps = ttk.Spinbox(settings, from_=1, to=100, textvariable=self.cps_var, width=8); self.cps.grid(row=0, column=1, padx=10)
        presets = ttk.Frame(settings); presets.grid(row=0, column=2, sticky="w")
        self.speed_buttons = []
        for value in (10, 20, 50, 100):
            button = ttk.Button(presets, text=str(value), width=4, command=lambda item=value: self.cps_var.set(str(item)))
            button.pack(side="left", padx=2)
            self.speed_buttons.append(button)
        ttk.Label(settings, text="Кнопка мыши").grid(row=1, column=0, sticky="w", pady=(12, 0))
        mouse = ttk.Frame(settings); mouse.grid(row=1, column=1, columnspan=4, sticky="w", pady=(12, 0))
        for label, value in (("Левая", "left"), ("Правая", "right"), ("Средняя", "middle")):
            ttk.Radiobutton(mouse, text=label, variable=self.button_var, value=value).pack(side="left", padx=(0, 10))
        ttk.Label(settings, text="Задержка, сек.").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.delay = ttk.Spinbox(settings, from_=0, to=10, increment=.5, textvariable=self.delay_var, width=8); self.delay.grid(row=2, column=1, padx=10, pady=(12, 0))
        target = ttk.LabelFrame(body, text="Куда кликать", padding=12); target.pack(fill="x", pady=12)
        ttk.Radiobutton(target, text="Под текущим курсором", variable=self.target_var, value="cursor").pack(anchor="w")
        ttk.Radiobutton(target, text="В сохранённую точку", variable=self.target_var, value="fixed").pack(anchor="w", pady=(4, 0))
        self.capture_button = ttk.Button(target, text="Запомнить положение курсора  (F7)", command=self.capture_position); self.capture_button.pack(anchor="w", pady=(8, 3))
        ttk.Label(target, textvariable=self.position_var).pack(anchor="w")
        golden = ttk.LabelFrame(body, text="Ловля печенек", padding=12); golden.pack(fill="x")
        self.golden_check = ttk.Checkbutton(
            golden,
            text="Искать и ловить золотые печеньки",
            variable=self.golden_var,
        ); self.golden_check.pack(anchor="w")
        self.wrath_check = ttk.Checkbutton(golden, text="Искать и ловить злые печеньки (красные)", variable=self.wrath_var)
        self.wrath_check.pack(anchor="w", pady=(4, 0))
        self.region_button = ttk.Button(golden, text="Выбрать игровую область  (F9)", command=self.capture_region); self.region_button.pack(anchor="w", pady=(8, 3))
        region_label = ttk.Label(golden, textvariable=self.region_var, wraplength=440); region_label.pack(anchor="w")
        hint = ttk.Label(golden, text="Выберите нужные виды печенек. Поиск запоминает видимые объекты при старте и ловит новые цели.", wraplength=440)
        hint.pack(anchor="w", pady=(5, 0))

        def resize_form(event: tk.Event) -> None:
            self.form_canvas.itemconfigure(form_id, width=event.width)
            for label in (region_label, hint):
                label.configure(wraplength=max(160, event.width - 40))

        self.form_canvas.bind("<Configure>", resize_form)
        footer.bind("<Configure>", lambda event: [label.configure(wraplength=max(160, event.width)) for label in (detail, shortcut)])

        def scroll_form(event: tk.Event) -> None:
            if not isinstance(event.widget, ttk.Spinbox) and body.winfo_height() > self.form_canvas.winfo_height():
                self.form_canvas.yview_scroll(-int(event.delta / 120), "units")

        self.root.bind("<MouseWheel>", scroll_form)
        self.root.update_idletasks()
        width = max(520, body.winfo_reqwidth() + scrollbar.winfo_reqwidth() + 32)
        height = body.winfo_reqheight() + footer.winfo_reqheight() + 125
        width = min(width, self.root.winfo_screenwidth() - 80)
        height = min(height, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, min(height, footer.winfo_reqheight() + golden.winfo_reqheight() + 145))

    def _poll_hotkeys(self) -> None:
        for key, action in ((VK_F6, self.toggle), (VK_F7, self.capture_position), (VK_F8, self.stop), (VK_F9, self.capture_region)):
            pressed = bool(user32.GetAsyncKeyState(key) & 0x8000)
            if pressed and not self.key_state[key]:
                action()
            self.key_state[key] = pressed
        self.root.after(30, self._poll_hotkeys)

    def capture_position(self) -> None:
        if self.engine.running or self.countdown_id: return
        point = POINT()
        if user32.GetCursorPos(ctypes.byref(point)):
            self.fixed_position = (point.x, point.y); self.target_var.set("fixed")
            self.position_var.set(f"Сохранено: X {point.x}, Y {point.y}")

    def capture_region(self) -> None:
        if self.engine.running or self.countdown_id:
            return
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return
        corner = (point.x, point.y)
        if self.region_first_corner is None:
            self.region_first_corner = corner
            self.region_var.set(f"Первый угол: X {corner[0]}, Y {corner[1]}. Переместите курсор в противоположный угол и нажмите F9.")
            self.detail_var.set("Выберите второй угол игровой области")
            return
        try:
            self.game_region = ScreenRegion.from_points(self.region_first_corner, corner)
        except ValueError as exc:
            messagebox.showwarning("Слишком маленькая область", str(exc), parent=self.root)
            return
        self.region_first_corner = None
        region = self.game_region
        self.region_var.set(f"Область: X {region.left}–{region.left + region.width}, Y {region.top}–{region.top + region.height}")
        if not self.golden_var.get() and not self.wrath_var.get():
            self.golden_var.set(True)
        self.detail_var.set("Область сохранена. Запомните основное печенье F7 и запускайте F6")

    def toggle(self) -> None:
        self.stop() if self.engine.running or self.countdown_id else self.start()

    def start(self) -> None:
        try: cps, delay = parse_settings(self.cps_var.get(), self.delay_var.get())
        except ValueError as exc: messagebox.showerror("Проверьте настройки", str(exc), parent=self.root); return
        golden_enabled = self.golden_var.get() or self.wrath_var.get()
        if golden_enabled:
            dependency_error = missing_dependencies()
            if dependency_error:
                messagebox.showerror("Не готов поиск", dependency_error, parent=self.root)
                return
            if self.game_region is None:
                messagebox.showwarning("Не выбрана область", "Наведите курсор на первый угол игры и дважды нажмите F9: для первого и противоположного угла.", parent=self.root)
                return
            if self.fixed_position is None:
                messagebox.showwarning("Не выбрано основное печенье", "Наведите курсор на основное печенье и нажмите F7. После ловли курсор вернётся в эту точку.", parent=self.root)
                return
            self.target_var.set("fixed")
        position = self.fixed_position if self.target_var.get() == "fixed" else None
        if self.target_var.get() == "fixed" and position is None:
            messagebox.showwarning("Не выбрана точка", "Сначала сохраните точку кнопкой F7.", parent=self.root); return
        try: save_click_preferences(self.cps_var.get(), self.delay_var.get(), self.button_var.get())
        except OSError: pass
        self._golden_pending = golden_enabled
        self._set_controls(False); self.stop_button.configure(state="normal")
        config = ClickConfig(cps, self.button_var.get(), position)
        if delay: self._countdown(config, delay)
        else: self._begin(config)

    def _countdown(self, config: ClickConfig, remaining: float) -> None:
        if remaining <= 0: self.countdown_id = None; self._begin(config); return
        self.status_var.set("СТАРТ ЧЕРЕЗ…"); self.detail_var.set(f"{remaining:g} сек. — наведите курсор на цель")
        step = min(.1, remaining); self.countdown_id = self.root.after(int(step * 1000), lambda: self._countdown(config, round(remaining - step, 4)))

    def _begin(self, config: ClickConfig) -> None:
        if self.engine.start(config):
            self.status_var.set("РАБОТАЕТ")
            self.detail_var.set(f"{config.cps:g} кликов/с. F8 — стоп")
            self.start_button.configure(text="Пауза  (F6)")
            if self._golden_pending:
                self._start_golden_watcher(config)

    def _start_golden_watcher(self, config: ClickConfig) -> None:
        if self.game_region is None or config.fixed_position is None:
            return

        def catch(point: tuple[int, int]) -> None:
            click_golden_cookie(point, config.fixed_position)

        self._golden_session += 1
        self.golden_watcher = GoldenCookieWatcher(
            self.game_region,
            catch,
            self.golden_events,
            session_id=self._golden_session,
            finder=GoldenCookieFinder(include_golden=self.golden_var.get(), include_wrath=self.wrath_var.get()),
        )
        if self.golden_watcher.start():
            self.detail_var.set(f"{config.cps:g} кликов/с. Поиск печенек калибруется…")

    def _poll_golden_events(self) -> None:
        while True:
            try:
                session_id, name, payload = self.golden_events.get_nowait()
            except queue.Empty:
                break
            if session_id != self._golden_session:
                continue
            if name in ("golden-caught", "wrath-caught"):
                x, y = payload
                label = "Злая" if name == "wrath-caught" else "Золотая"
                self.detail_var.set(f"{label} печенька поймана: X {x}, Y {y}. Обычные клики продолжаются.")
            elif name == "golden-error":
                self.golden_watcher = None
                if self.engine.running:
                    self.status_var.set("РАБОТАЕТ")
                    self.detail_var.set(f"Обычные клики продолжаются. {payload}")
                else:
                    self.status_var.set("ГОТОВ")
                    self.detail_var.set(str(payload))
        self.root.after(100, self._poll_golden_events)

    def stop(self) -> None:
        if self.countdown_id: self.root.after_cancel(self.countdown_id); self.countdown_id = None
        self._golden_session += 1
        watcher, self.golden_watcher = self.golden_watcher, None
        if watcher:
            watcher.stop()
        self._golden_pending = False
        self.engine.stop(); self._set_controls(True); self.stop_button.configure(state="disabled"); self.start_button.configure(text="Запустить  (F6)")
        self.status_var.set("ГОТОВ"); self.detail_var.set("Наведите курсор на цель и нажмите F6")

    def _set_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.cps.configure(state=state); self.delay.configure(state=state); self.capture_button.configure(state=state)
        self.golden_check.configure(state=state); self.wrath_check.configure(state=state); self.region_button.configure(state=state)

    def close(self) -> None:
        self.stop()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    args = set(sys.argv[1:] if argv is None else argv)
    if "--check-golden-detector" in args:
        error = detector_self_check(check_capture_backend=True)
        report_path = os.environ.get("AUTOCLICKER_SELF_CHECK_REPORT")
        if report_path:
            Path(report_path).write_text(error or "ok", encoding="utf-8")
        return 1 if error else 0

    smoke_test = "--smoke-test" in args
    root = tk.Tk()
    app = AutoClickerApp(root, enable_hotkeys=not smoke_test)
    if smoke_test:
        root.after(500, app.close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
