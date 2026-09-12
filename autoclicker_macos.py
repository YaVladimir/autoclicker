"""Core input and hotkey support for the macOS autoclicker."""

from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

try:
    import Quartz
except ImportError as exc:
    raise SystemExit(
        "Не установлен компонент macOS. Запустите install_macos.command, "
        "а затем снова откройте run_autoclicker_macos.command."
    ) from exc


KEY_NAMES = {
    0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X",
    8: "C", 9: "V", 11: "B", 12: "Q", 13: "W", 14: "E", 15: "R",
    16: "Y", 17: "T", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6",
    23: "5", 24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0",
    31: "O", 32: "U", 34: "I", 35: "P", 37: "L", 38: "J", 40: "K",
    45: "N", 46: "M", 49: "Пробел", 53: "Esc", 122: "F1", 120: "F2",
    99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8",
    101: "F9", 109: "F10", 103: "F11", 111: "F12",
}
HOTKEY_ACTIONS = (("toggle", "Старт / пауза"), ("capture", "Запомнить точку"), ("stop", "Остановить всё"))
DEFAULT_HOTKEYS = {"toggle": 97, "capture": 98, "stop": 100}
# The application bundle is read-only after installation, so settings belong in
# the user's standard Application Support directory rather than beside the code.
SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "Autoclicker" / "settings.json"
MOUSE_LOCK = threading.Lock()


def hotkey_name(key_code: int) -> str:
    return KEY_NAMES.get(key_code, f"Клавиша {key_code}")


def validate_hotkeys(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return DEFAULT_HOTKEYS.copy()
    result: dict[str, int] = {}
    for action, _ in HOTKEY_ACTIONS:
        key_code = value.get(action)
        if type(key_code) is not int or key_code not in KEY_NAMES:
            return DEFAULT_HOTKEYS.copy()
        result[action] = key_code
    return result if len(set(result.values())) == len(result) else DEFAULT_HOTKEYS.copy()


def load_hotkeys() -> dict[str, int]:
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_HOTKEYS.copy()
    return validate_hotkeys(saved.get("hotkeys") if isinstance(saved, dict) else None)


def save_hotkeys(hotkeys: dict[str, int]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps({"version": 1, "hotkeys": hotkeys}, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass(frozen=True)
class ClickConfig:
    cps: float
    mouse_button: str
    fixed_position: tuple[float, float] | None


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


def cursor_position() -> tuple[float, float]:
    event = Quartz.CGEventCreate(None)
    point = Quartz.CGEventGetLocation(event)
    return point.x, point.y


def _button_event(button: str, down: bool) -> tuple[int, int]:
    if button == "left":
        return (Quartz.kCGEventLeftMouseDown if down else Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft)
    if button == "right":
        return (Quartz.kCGEventRightMouseDown if down else Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight)
    return (Quartz.kCGEventOtherMouseDown if down else Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter)


def _emit_mouse_click(button: str, position: tuple[float, float]) -> None:
    point = Quartz.CGPointMake(*position)
    for down in (True, False):
        event_type, mouse_button = _button_event(button, down)
        event = Quartz.CGEventCreateMouseEvent(None, event_type, point, mouse_button)
        # Make rapid synthetic down/up pairs unambiguously complete clicks.
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, 1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def send_mouse_click(button: str, position: tuple[float, float] | None) -> None:
    """Send one native click without moving the pointer in cursor mode."""
    with MOUSE_LOCK:
        _emit_mouse_click(button, position if position is not None else cursor_position())


class ClickEngine:
    """Runs clicks on a worker thread and can be stopped immediately."""

    def __init__(self, click_action: Callable[[str, tuple[float, float] | None], None]):
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
            self._thread = threading.Thread(target=self._run, args=(config,), daemon=True, name="AutoClicker")
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=.35)

    def _run(self, config: ClickConfig) -> None:
        interval = 1 / config.cps
        next_click = time.perf_counter()
        while not self._stop_event.is_set():
            self._click_action(config.mouse_button, config.fixed_position)
            next_click += interval
            now = time.perf_counter()
            if now - next_click > interval:
                next_click = now
            self._stop_event.wait(max(0, next_click - now))


class HotkeyListener:
    """Global keyboard listener that observes input without consuming it."""

    def __init__(self, events: queue.SimpleQueue[tuple[str, object]]):
        self._events = events
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="HotkeyListener")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=.5)

    def _run(self) -> None:
        def callback(_proxy: object, event_type: int, event: object, _refcon: object) -> object:
            if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                Quartz.CGEventTapEnable(tap, True)
            elif event_type == Quartz.kCGEventKeyDown and not Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
                self._events.put(("key", Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)))
            return event

        mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        tap = Quartz.CGEventTapCreate(Quartz.kCGHIDEventTap, Quartz.kCGHeadInsertEventTap, Quartz.kCGEventTapOptionListenOnly, mask, callback, None)
        if tap is None:
            self._events.put(("hotkey-error", "Нет доступа к глобальным клавишам. Разрешите «Мониторинг ввода» и «Универсальный доступ»."))
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        run_loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(run_loop, source, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)
        while not self._stop_event.is_set():
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, .1, False)
        Quartz.CGEventTapEnable(tap, False)
        Quartz.CFRunLoopRemoveSource(run_loop, source, Quartz.kCFRunLoopDefaultMode)


def main() -> None:
    from macos_cocoa_ui import run
    run()


if __name__ == "__main__":
    main()
