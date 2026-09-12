"""Windows interface for the Cookie Clicker Autoclicker."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable


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
VK_F6, VK_F7, VK_F8 = 0x75, 0x76, 0x77
MOUSE_LOCK = threading.Lock()
user32 = ctypes.windll.user32
user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)


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


def _emit_mouse_click(button: str) -> None:
    down, up = MOUSE_FLAGS[button]
    inputs = (INPUT * 2)(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dwFlags=down)), INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dwFlags=up)))
    user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


def send_mouse_click(button: str, position: tuple[int, int] | None) -> None:
    with MOUSE_LOCK:
        if position is not None:
            user32.SetCursorPos(*position)
        _emit_mouse_click(button)


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
    def __init__(self, root: tk.Tk):
        self.root, self.engine = root, ClickEngine(send_mouse_click)
        self.fixed_position: tuple[int, int] | None = None
        self.countdown_id: str | None = None
        self.key_state = {key: False for key in (VK_F6, VK_F7, VK_F8)}
        self.cps_var, self.delay_var = tk.StringVar(value="20"), tk.StringVar(value="2")
        self.button_var, self.target_var = tk.StringVar(value="left"), tk.StringVar(value="cursor")
        self.status_var, self.detail_var = tk.StringVar(value="ГОТОВ"), tk.StringVar(value="Наведите курсор на цель и нажмите F6")
        self.position_var = tk.StringVar(value="Точка ещё не выбрана")
        self._build()
        self.root.after(30, self._poll_hotkeys)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        self.root.title("Автокликер")
        self.root.geometry("500x460")
        self.root.resizable(False, False)
        body = ttk.Frame(self.root, padding=20); body.pack(fill="both", expand=True)
        ttk.Label(body, text="Автокликер", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(body, text="Для Cookie Clicker и других игр-кликеров").pack(anchor="w", pady=(0, 16))
        settings = ttk.LabelFrame(body, text="Настройки", padding=12); settings.pack(fill="x")
        ttk.Label(settings, text="Кликов в секунду").grid(row=0, column=0, sticky="w")
        self.cps = ttk.Spinbox(settings, from_=1, to=100, textvariable=self.cps_var, width=8); self.cps.grid(row=0, column=1, padx=10)
        for index, value in enumerate((10, 20, 50)):
            ttk.Button(settings, text=str(value), command=lambda item=value: self.cps_var.set(str(item))).grid(row=0, column=index + 2, padx=2)
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
        ttk.Label(body, textvariable=self.status_var, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(4, 0))
        ttk.Label(body, textvariable=self.detail_var).pack(anchor="w", pady=(2, 8))
        row = ttk.Frame(body); row.pack(fill="x")
        self.start_button = ttk.Button(row, text="Запустить  (F6)", command=self.toggle); self.start_button.pack(side="left", fill="x", expand=True)
        self.stop_button = ttk.Button(row, text="Стоп  (F8)", command=self.stop, state="disabled"); self.stop_button.pack(side="left", padx=(10, 0))
        ttk.Label(body, text="F6 — старт/пауза  •  F7 — точка  •  F8 — стоп").pack(anchor="w", pady=(12, 0))

    def _poll_hotkeys(self) -> None:
        for key, action in ((VK_F6, self.toggle), (VK_F7, self.capture_position), (VK_F8, self.stop)):
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

    def toggle(self) -> None:
        self.stop() if self.engine.running or self.countdown_id else self.start()

    def start(self) -> None:
        try: cps, delay = parse_settings(self.cps_var.get(), self.delay_var.get())
        except ValueError as exc: messagebox.showerror("Проверьте настройки", str(exc), parent=self.root); return
        position = self.fixed_position if self.target_var.get() == "fixed" else None
        if self.target_var.get() == "fixed" and position is None:
            messagebox.showwarning("Не выбрана точка", "Сначала сохраните точку кнопкой F7.", parent=self.root); return
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
            self.status_var.set("РАБОТАЕТ"); self.detail_var.set(f"{config.cps:g} кликов/с. F8 — стоп"); self.start_button.configure(text="Пауза  (F6)")

    def stop(self) -> None:
        if self.countdown_id: self.root.after_cancel(self.countdown_id); self.countdown_id = None
        self.engine.stop(); self._set_controls(True); self.stop_button.configure(state="disabled"); self.start_button.configure(text="Запустить  (F6)")
        self.status_var.set("ГОТОВ"); self.detail_var.set("Наведите курсор на цель и нажмите F6")

    def _set_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.cps.configure(state=state); self.delay.configure(state=state); self.capture_button.configure(state=state)

    def close(self) -> None:
        self.stop(); self.root.destroy()


def main() -> None:
    root = tk.Tk(); AutoClickerApp(root); root.mainloop()


if __name__ == "__main__":
    main()
