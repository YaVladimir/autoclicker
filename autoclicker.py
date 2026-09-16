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
from tkinter import messagebox

import customtkinter as ctk
from windows_ui import WindowsInterface
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
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
DEFAULT_CLICK_PREFERENCES = {"cps": "100", "delay": "0", "mouse_button": "left"}
SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Autoclicker" / "settings.json"
MOUSE_LOCK = threading.Lock()
user32 = ctypes.windll.user32
user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetSystemMetrics.argtypes = (ctypes.c_int,)


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


def resource_path(relative_path: str) -> Path:
    """Resolve bundled assets as well as files next to the source tree."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative_path


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


class AutoClickerApp(WindowsInterface):
    def __init__(self, root: tk.Tk, *, enable_hotkeys: bool = True):
        self.root, self.engine = root, ClickEngine(send_mouse_click)
        self.fixed_position: tuple[int, int] | None = None
        self.game_region: ScreenRegion | None = None
        self.golden_watcher: GoldenCookieWatcher | None = None
        self.golden_events: queue.SimpleQueue[tuple[int, str, object]] = queue.SimpleQueue()
        self._golden_session = 0
        self._golden_pending = False
        self.countdown_id: str | None = None
        self.active_config: ClickConfig | None = None
        self.paused_config: ClickConfig | None = None
        self.selection_overlay: tk.Toplevel | None = None
        self.selection_canvas: tk.Canvas | None = None
        self.selection_mode: str | None = None
        self.selection_start: tuple[int, int] | None = None
        self.selection_rect: int | None = None
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
        self.appearance_path = SETTINGS_PATH.with_name("appearance.json")
        super()._build()

        def set_icon() -> None:
            try:
                self.root.iconbitmap(resource_path("assets/autoclicker-icon.ico"))
            except tk.TclError:
                pass

        set_icon()
        # CTk installs its own default icon shortly after creating the root.
        self.root.after(300, set_icon)

    def _poll_hotkeys(self) -> None:
        for key, action in ((VK_F6, self.toggle), (VK_F7, self.capture_position), (VK_F8, self.stop), (VK_F9, self.capture_region)):
            pressed = bool(user32.GetAsyncKeyState(key) & 0x8000)
            if pressed and not self.key_state[key]:
                action()
            self.key_state[key] = pressed
        self.root.after(30, self._poll_hotkeys)

    def capture_position(self) -> None:
        if self.engine.running or self.countdown_id or self.selection_overlay:
            return
        self._begin_selection("point")

    def capture_region(self) -> None:
        if self.engine.running or self.countdown_id or self.selection_overlay:
            return
        self._begin_selection("region")

    def _begin_selection(self, mode: str) -> None:
        """Use a full-screen capture layer so a toolbar click cannot become the target."""
        left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        self.selection_mode = mode
        self.selection_start = None
        self.selection_rect = None
        self.root.withdraw()
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.geometry(f"{width}x{height}{left:+d}{top:+d}")
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.22)
        canvas = tk.Canvas(overlay, background="#101828", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        prompt = "Щёлкните по цели для кликов. Esc — отмена" if mode == "point" else "Потяните рамку вокруг игровой области. Esc — отмена"
        canvas.create_text(24, 24, anchor="nw", text=prompt, fill="white", font=("Segoe UI", 14, "bold"))
        canvas.bind("<Button-1>", self._selection_press)
        canvas.bind("<B1-Motion>", self._selection_drag)
        canvas.bind("<ButtonRelease-1>", self._selection_release)
        overlay.bind("<Escape>", self._cancel_selection)
        self.selection_overlay, self.selection_canvas = overlay, canvas
        overlay.after(80, overlay.focus_force)

    def _cursor_position(self) -> tuple[int, int] | None:
        point = POINT()
        if user32.GetCursorPos(ctypes.byref(point)):
            return point.x, point.y
        return None

    def _selection_press(self, _event: tk.Event) -> None:
        point = self._cursor_position()
        if point is None:
            self._finish_selection()
            return
        if self.selection_mode == "point":
            self.fixed_position = point
            self.target_var.set("fixed")
            self.position_var.set(f"Точка выбрана: X {point[0]}, Y {point[1]}")
            self.detail_var.set("Точка готова к запуску")
            self._finish_selection()
            return
        self.selection_start = point
        if self.selection_canvas:
            self.selection_rect = self.selection_canvas.create_rectangle(
                _event.x, _event.y, _event.x, _event.y, outline="#FFB547", width=3,
            )

    def _selection_drag(self, event: tk.Event) -> None:
        if self.selection_mode == "region" and self.selection_canvas and self.selection_rect is not None:
            start = self.selection_start
            if start:
                left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
                top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
                self.selection_canvas.coords(self.selection_rect, start[0] - left, start[1] - top, event.x, event.y)

    def _selection_release(self, _event: tk.Event) -> None:
        if self.selection_mode != "region" or self.selection_start is None:
            return
        end = self._cursor_position()
        if end is None:
            self._finish_selection()
            return
        try:
            self.game_region = ScreenRegion.from_points(self.selection_start, end)
        except ValueError as exc:
            self._finish_selection()
            messagebox.showwarning("Слишком маленькая область", str(exc), parent=self.root)
            return
        region = self.game_region
        self.region_var.set(f"Область: X {region.left}–{region.left + region.width}, Y {region.top}–{region.top + region.height}")
        if not self.golden_var.get() and not self.wrath_var.get():
            self.golden_var.set(True)
        self.detail_var.set("Область выбрана. Выберите основную точку и запускайте")
        self._finish_selection()

    def _cancel_selection(self, _event: tk.Event | None = None) -> None:
        self._finish_selection()
        self.detail_var.set("Выбор отменён")

    def _finish_selection(self) -> None:
        overlay, self.selection_overlay = self.selection_overlay, None
        self.selection_canvas = None
        self.selection_mode = None
        self.selection_start = None
        self.selection_rect = None
        if overlay:
            overlay.destroy()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def toggle(self, *, from_button: bool = False) -> None:
        if self.engine.running:
            self.pause()
        elif self.countdown_id:
            self.stop()
        elif self.paused_config:
            self._begin(self.paused_config)
        else:
            self.start(from_button=from_button)

    def start(self, *, from_button: bool = False) -> None:
        try: cps, delay = parse_settings(self.cps_var.get(), self.delay_var.get())
        except ValueError as exc: messagebox.showerror("Проверьте настройки", str(exc), parent=self.root); return
        golden_enabled = self.golden_var.get() or self.wrath_var.get()
        if golden_enabled:
            dependency_error = missing_dependencies()
            if dependency_error:
                messagebox.showerror("Не готов поиск", dependency_error, parent=self.root)
                return
            if self.game_region is None:
                messagebox.showwarning("Не выбрана область", "Нажмите F9 или «Выбрать игровую область» и обведите игровое поле мышью.", parent=self.root)
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
        self.active_config = config
        effective_delay = delay or (3 if from_button and position is None else 0)
        if effective_delay: self._countdown(config, effective_delay)
        else: self._begin(config)

    def _countdown(self, config: ClickConfig, remaining: float) -> None:
        if remaining <= 0: self.countdown_id = None; self._begin(config); return
        self.start_button.configure(text="Отменить запуск  (F6)")
        self.status_var.set("СТАРТ ЧЕРЕЗ…"); self.detail_var.set(f"{remaining:g} сек. — наведите курсор на цель")
        step = min(.1, remaining); self.countdown_id = self.root.after(int(step * 1000), lambda: self._countdown(config, round(remaining - step, 4)))

    def _begin(self, config: ClickConfig) -> None:
        if self.engine.start(config):
            self.active_config, self.paused_config = config, None
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

    def pause(self) -> None:
        if not self.engine.running or self.active_config is None:
            return
        self._stop_watcher()
        self.engine.stop()
        self.paused_config = self.active_config
        self.status_var.set("НА ПАУЗЕ")
        self.detail_var.set("Клики остановлены. F6 — продолжить, F8 — завершить")
        self.start_button.configure(text="Продолжить  (F6)")

    def _stop_watcher(self) -> None:
        self._golden_session += 1
        watcher, self.golden_watcher = self.golden_watcher, None
        if watcher:
            watcher.stop()

    def stop(self) -> None:
        if self.selection_overlay:
            self._cancel_selection()
        if self.countdown_id: self.root.after_cancel(self.countdown_id); self.countdown_id = None
        self._stop_watcher()
        self._golden_pending = False
        self.active_config = None
        self.paused_config = None
        self.engine.stop(); self._set_controls(True); self.stop_button.configure(state="disabled"); self.start_button.configure(text="Запустить  (F6)")
        self.status_var.set("ГОТОВ"); self.detail_var.set("Наведите курсор на цель и нажмите F6")

    def _set_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for control in self.setting_controls:
            control.configure(state=state)

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
    root = ctk.CTk()
    app = AutoClickerApp(root, enable_hotkeys=not smoke_test)
    if smoke_test:
        root.after(500, app.close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
