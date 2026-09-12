"""Native Cocoa interface for the macOS autoclicker.

Keeping the interface in AppKit avoids the Tk rendering failure that appears
with the system Python/Tk combination in macOS Dark Mode.
"""

from __future__ import annotations

import queue
import time
import os

import AppKit
import objc
from Foundation import NSObject, NSMakeRect, NSTimer

import autoclicker_macos as core


class CocoaAutoClickerApp(NSObject):
    """The native window and its bridge to the platform-independent workers."""

    def init(self):  # type: ignore[no-untyped-def]
        self = objc.super(CocoaAutoClickerApp, self).init()
        if self is None:
            return None
        self.events: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self.engine = core.ClickEngine(core.send_mouse_click)
        self.hotkey_listener = core.HotkeyListener(self.events)
        self.hotkeys = core.load_hotkeys()
        self.fixed_position: tuple[float, float] | None = None
        self.countdown_timer = None
        self.countdown_deadline = 0.0
        self.countdown_config = None
        self._closed = False
        self._build_window()
        # The UI smoke test creates a real native window but avoids a global
        # event tap and any permission requests.
        self._ui_smoke_mode = os.environ.get("AUTOCLICKER_UI_SMOKE") == "1"
        if not self._ui_smoke_mode:
            self.hotkey_listener.start()
        self.event_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.03, self, "pollEvents:", None, True
        )
        return self

    @objc.python_method
    def _build_window(self) -> None:
        style = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
        )
        self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 560, 540), style, AppKit.NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Автокликер для macOS")
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self)
        self.window.center()
        self.content = self.window.contentView()

        self._label("Автокликер", 26, 485, 500, 30, size=24, bold=True)
        self._label("Для Cookie Clicker и других игр-кликеров", 27, 460, 500, 18, size=12)

        self._label("Настройки клика", 26, 415, 500, 20, size=14, bold=True)
        self._label("Кликов в секунду", 27, 380, 135, 20)
        self.cps_field = self._text_field("20", 170, 377, 80, 24)
        for index, value in enumerate((10, 20, 50)):
            button = self._button(str(value), 260 + index * 58, 377, 52, 24, "setSpeed:")
            button.setTag_(value)

        self._label("Кнопка мыши", 27, 342, 135, 20)
        self.button_popup = self._popup(["Левая", "Правая", "Средняя"], 170, 339, 165, 26)
        self._label("Задержка старта, сек.", 27, 304, 135, 20)
        self.delay_field = self._text_field("2", 170, 301, 80, 24)

        self._label("Куда кликать", 26, 255, 500, 20, size=14, bold=True)
        self.target_popup = self._popup(["Под текущим курсором", "В сохранённую точку"], 27, 221, 265, 26)
        self.capture_button = self._button("Запомнить положение курсора", 306, 221, 220, 26, "capturePosition:")
        self.position_label = self._label("Точка ещё не выбрана", 27, 194, 500, 18, size=11)

        self.status_title_label = self._label("ГОТОВ", 27, 145, 115, 26, size=13, bold=True)
        self.status_detail_label = self._label(
            f"Наведите курсор на цель и нажмите {self._hotkey('toggle')}",
            145,
            145,
            380,
            26,
            size=11,
        )
        self.start_button = self._button("Запустить", 27, 91, 335, 34, "toggleClicking:")
        self.start_button.setKeyEquivalent_("\r")
        self.stop_button = self._button("Стоп", 374, 91, 152, 34, "stopClicking:")
        self.stop_button.setEnabled_(False)

        self.topmost_check = self._checkbox("Поверх других окон", 27, 45, 185, "toggleTopmost:")
        self._label(
            f"{self._hotkey('toggle')} — старт  •  {self._hotkey('capture')} — точка  •  {self._hotkey('stop')} — стоп",
            27,
            16,
            500,
            18,
            size=11,
        )
        self.setting_controls = [
            self.cps_field,
            self.delay_field,
            self.button_popup,
            self.target_popup,
            self.capture_button,
        ]

    @objc.python_method
    def _label(self, text: str, x: float, y: float, width: float, height: float, *, size: float = 13, bold: bool = False):  # type: ignore[no-untyped-def]
        label = AppKit.NSTextField.labelWithString_(text)
        label.setFrame_(NSMakeRect(x, y, width, height))
        label.setFont_(
            AppKit.NSFont.boldSystemFontOfSize_(size)
            if bold
            else AppKit.NSFont.systemFontOfSize_(size)
        )
        label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        self.content.addSubview_(label)
        return label

    @objc.python_method
    def _text_field(self, value: str, x: float, y: float, width: float, height: float):  # type: ignore[no-untyped-def]
        field = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        field.setStringValue_(value)
        self.content.addSubview_(field)
        return field

    @objc.python_method
    def _popup(self, values: list[str], x: float, y: float, width: float, height: float):  # type: ignore[no-untyped-def]
        popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(x, y, width, height), False)
        popup.addItemsWithTitles_(values)
        self.content.addSubview_(popup)
        return popup

    @objc.python_method
    def _button(self, title: str, x: float, y: float, width: float, height: float, action: str):  # type: ignore[no-untyped-def]
        button = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        button.setTitle_(title)
        button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        button.setTarget_(self)
        button.setAction_(action)
        self.content.addSubview_(button)
        return button

    @objc.python_method
    def _checkbox(self, title: str, x: float, y: float, width: float, action: str):  # type: ignore[no-untyped-def]
        checkbox = self._button(title, x, y, width, 22, action)
        checkbox.setButtonType_(AppKit.NSSwitchButton)
        checkbox.setState_(AppKit.NSControlStateValueOff)
        return checkbox

    def show(self) -> None:
        self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApp().activateIgnoringOtherApps_(True)

    @objc.python_method
    def _hotkey(self, action: str) -> str:
        return core.hotkey_name(self.hotkeys[action])

    def setSpeed_(self, sender: object) -> None:
        self.cps_field.setStringValue_(str(sender.tag()))

    def toggleTopmost_(self, _sender: object) -> None:
        level = AppKit.NSFloatingWindowLevel if self.topmost_check.state() else AppKit.NSNormalWindowLevel
        self.window.setLevel_(level)

    def capturePosition_(self, _sender: object) -> None:
        if self.engine.running or self.countdown_timer is not None:
            return
        x, y = core.cursor_position()
        self.fixed_position = (x, y)
        self.target_popup.selectItemAtIndex_(1)
        self.position_label.setStringValue_(f"Сохранено: X {x:.0f}, Y {y:.0f}")
        self._set_status("ГОТОВ", f"Точка сохранена. Нажмите {self._hotkey('toggle')} для запуска")

    def toggleClicking_(self, _sender: object) -> None:
        if self.engine.running or self.countdown_timer is not None:
            self._stop_all()
        else:
            self._start()

    @objc.python_method
    def _start(self) -> None:
        try:
            cps, delay = core.parse_settings(self.cps_field.stringValue(), self.delay_field.stringValue())
        except ValueError as exc:
            self._show_alert("Проверьте настройки", str(exc))
            return
        fixed = self.target_popup.indexOfSelectedItem() == 1
        if fixed and self.fixed_position is None:
            self._show_alert("Не выбрана точка", f"Наведите курсор на цель и нажмите {self._hotkey('capture')}.")
            return
        button_names = ("left", "right", "middle")
        config = core.ClickConfig(cps, button_names[self.button_popup.indexOfSelectedItem()], self.fixed_position if fixed else None)
        self._set_controls_enabled(False)
        self.stop_button.setEnabled_(True)
        if delay:
            self.countdown_config = config
            self.countdown_deadline = time.monotonic() + delay
            self.countdown_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.1, self, "countdownTick:", None, True
            )
            self._countdown_tick()
        else:
            self._begin_clicking(config)

    def countdownTick_(self, _timer: object) -> None:
        self._countdown_tick()

    @objc.python_method
    def _countdown_tick(self) -> None:
        remaining = max(0, self.countdown_deadline - time.monotonic())
        if remaining <= 0:
            self.countdown_timer.invalidate()
            self.countdown_timer = None
            self._begin_clicking(self.countdown_config)
            return
        self._set_status("СТАРТ ЧЕРЕЗ…", f"{remaining:.1f} сек. — наведите курсор на цель")
        self.start_button.setTitle_("Отменить запуск")

    @objc.python_method
    def _begin_clicking(self, config: core.ClickConfig) -> None:
        if self.engine.start(config):
            destination = "в сохранённую точку" if config.fixed_position else "под курсором"
            self._set_status("РАБОТАЕТ", f"{config.cps:g} кликов/с, {destination}. {self._hotkey('stop')} — стоп")
            self.start_button.setTitle_("Пауза")

    def stopClicking_(self, _sender: object) -> None:
        self._stop_all()

    @objc.python_method
    def _stop_all(self) -> None:
        if self.countdown_timer is not None:
            self.countdown_timer.invalidate()
            self.countdown_timer = None
        self.engine.stop()
        self._set_controls_enabled(True)
        self.stop_button.setEnabled_(False)
        self.start_button.setTitle_("Запустить")
        self._set_status("ГОТОВ", f"Наведите курсор на цель и нажмите {self._hotkey('toggle')}")

    def pollEvents_(self, _timer: object) -> None:
        while True:
            try:
                name, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if name == "key":
                action = next((item for item, code in self.hotkeys.items() if code == payload), None)
                if action == "toggle":
                    self.toggleClicking_(None)
                elif action == "capture":
                    self.capturePosition_(None)
                elif action == "stop":
                    self._stop_all()
            elif name == "hotkey-error":
                self._set_status("НУЖЕН ДОСТУП", str(payload))

    @objc.python_method
    def _set_controls_enabled(self, enabled: bool) -> None:
        for control in self.setting_controls:
            control.setEnabled_(enabled)

    @objc.python_method
    def _set_status(self, title: str, detail: str) -> None:
        self.status_title_label.setStringValue_(title)
        self.status_detail_label.setStringValue_(detail)

    @objc.python_method
    def _show_alert(self, title: str, detail: str) -> None:
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(detail)
        alert.addButtonWithTitle_("Понятно")
        alert.runModal()

    def windowWillClose_(self, _notification: object) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_all()
        if not self._ui_smoke_mode:
            self.hotkey_listener.stop()
        self.event_timer.invalidate()


class ApplicationDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _notification: object) -> None:
        self.controller = CocoaAutoClickerApp.alloc().init()
        self.controller.show()

    def applicationShouldTerminateAfterLastWindowClosed_(self, _sender: object) -> bool:
        return True


def run() -> None:
    application = AppKit.NSApplication.sharedApplication()
    application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    delegate = ApplicationDelegate.alloc().init()
    application.setDelegate_(delegate)
    application.activateIgnoringOtherApps_(True)
    application.run()
