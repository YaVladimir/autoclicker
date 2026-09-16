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


class SettingsView(AppKit.NSView):
    def isFlipped(self):
        return True


class SelectionWindow(AppKit.NSWindow):
    def canBecomeKeyWindow(self):
        return True


class PointSelectionView(AppKit.NSView):
    def acceptsFirstResponder(self):
        return True

    def acceptsFirstMouse_(self, _event):
        return True

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), AppKit.NSCursor.crosshairCursor())

    def drawRect_(self, _rect):
        AppKit.NSColor.colorWithCalibratedWhite_alpha_(0, 0.18).setFill()
        AppKit.NSRectFill(self.bounds())

    def mouseDown_(self, _event):
        # Consume both halves of the selection click; never forward it to the game.
        pass

    def mouseUp_(self, event):
        point = self.window().convertPointToScreen_(event.locationInWindow())
        primary_height = AppKit.NSScreen.screens()[0].frame().size.height
        self.controller._finish_point_selection(core.cocoa_to_quartz(point.x, point.y, primary_height))

    def keyDown_(self, event):
        if event.keyCode() in (53, self.controller.hotkeys["stop"]):
            self.controller._cancel_point_selection()


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
        self.click_preferences = core.load_click_preferences()
        self.appearance = core.load_appearance()
        self.fixed_position: tuple[float, float] | None = None
        self.countdown_timer = None
        self.countdown_deadline = 0.0
        self.countdown_config = None
        self.active_config = None
        self.paused_config = None
        self.selection_windows = []
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
            | AppKit.NSWindowStyleMaskResizable
        )
        self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 600, 650), style, AppKit.NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Автокликер для macOS")
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self)
        self.window.setContentMinSize_((580, 360))
        visible = AppKit.NSScreen.mainScreen().visibleFrame()
        self.window.setContentSize_((min(600, visible.size.width), min(650, visible.size.height - 40)))
        self.window.center()
        root = self.window.contentView()
        self.scroll_view = AppKit.NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 150, 600, 500))
        self.scroll_view.setHasVerticalScroller_(True)
        self.scroll_view.setAutohidesScrollers_(True)
        self.scroll_view.setHasHorizontalScroller_(False)
        self.scroll_view.setDrawsBackground_(False)
        root.addSubview_(self.scroll_view)
        self.content = SettingsView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 500))
        self.scroll_view.setDocumentView_(self.content)

        self._label("Автокликер", 26, 18, 500, 32, size=26, bold=True)
        self._label("Для Cookie Clicker и других игр-кликеров", 27, 55, 500, 20, size=12)
        self._label("Настройки клика", 26, 100, 500, 22, size=15, bold=True)
        self._label("Кликов в секунду", 27, 138, 170, 22)
        self.cps_field = self._text_field(self.click_preferences["cps"], 208, 135, 80, 26)
        self.cps_field.setDelegate_(self)
        self.speed_slider = AppKit.NSSlider.alloc().initWithFrame_(NSMakeRect(27, 174, 530, 26))
        self.speed_slider.setMinValue_(1)
        self.speed_slider.setMaxValue_(100)
        self.speed_slider.setDoubleValue_(float(self.click_preferences["cps"]))
        self.speed_slider.setContinuous_(True)
        self.speed_slider.setTarget_(self)
        self.speed_slider.setAction_("slideSpeed:")
        self.speed_slider.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        self.speed_slider.setAccessibilityLabel_("Кликов в секунду")
        self.content.addSubview_(self.speed_slider)
        self.speed_presets = []
        for index, value in enumerate((10, 20, 50, 100)):
            button = self._button(str(value), 304 + index * 62, 135, 56, 26, "setSpeed:")
            button.setTag_(value)
            self.speed_presets.append(button)

        self._label("Кнопка мыши", 27, 218, 170, 22)
        self.button_popup = self._segments(["Левая", "Правая", "Средняя"], 208, 215, 340, "changeMouseButton:")
        self.button_popup.setSelectedSegment_(("left", "right", "middle").index(self.click_preferences["mouse_button"]))
        self._label("Задержка старта, сек.", 27, 263, 175, 22)
        self.delay_field = self._text_field(self.click_preferences["delay"], 208, 260, 80, 26)
        self._label("0–10 секунд", 304, 264, 200, 20, size=11)

        self._label("Куда кликать", 26, 314, 500, 22, size=15, bold=True)
        self.target_popup = self._segments(["Под курсором", "В точку"], 27, 351, 300, "changeTarget:")
        self.capture_button = self._button("Выбрать точку", 348, 351, 200, 28, "capturePosition:")
        self.position_label = self._label("Точка ещё не выбрана", 27, 390, 500, 22, size=11)
        self.topmost_check = self._checkbox("Поверх других окон", 27, 443, 205, "toggleTopmost:")
        self.hotkeys_button = self._button("Горячие клавиши…", 244, 441, 180, 26, "configureHotkeys:")
        self.appearance_button = self._button("Вид…", 438, 441, 110, 26, "configureAppearance:")

        form = self.content
        self.footer = AppKit.NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 150))
        root.addSubview_(self.footer)
        self.content = self.footer
        self.status_title_label = self._label("ГОТОВ", 27, 111, 160, 24, size=13, bold=True)
        self.status_detail_label = self._label(
            f"Наведите курсор на цель и нажмите {self._hotkey('toggle')}",
            27, 84, 540, 22,
            size=11,
        )
        self.status_detail_label.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        self.start_button = self._button("Запустить", 27, 43, 375, 34, "toggleClicking:")
        self.start_button.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        self.start_button.setKeyEquivalent_("\r")
        self.stop_button = self._button("Стоп", 414, 43, 152, 34, "stopClicking:")
        self.stop_button.setAutoresizingMask_(AppKit.NSViewMinXMargin)
        self.stop_button.setEnabled_(False)
        self.hotkey_summary_label = self._label(
            self._hotkey_summary(), 27, 13, 530, 18, size=11,
        )
        self.content = form
        self.setting_controls = [
            self.cps_field,
            self.delay_field,
            self.button_popup,
            self.target_popup,
            self.capture_button,
            self.hotkeys_button,
            self.appearance_button,
            self.topmost_check,
            self.speed_slider,
        ] + self.speed_presets
        self._layout()
        self._apply_appearance()

    @objc.python_method
    def _layout(self):
        bounds = self.window.contentView().bounds()
        self.footer.setFrame_(NSMakeRect(0, 0, bounds.size.width, 150))
        self.scroll_view.setFrame_(NSMakeRect(0, 150, bounds.size.width, max(1, bounds.size.height - 150)))
        self.content.setFrameSize_((self.scroll_view.contentSize().width, 500))

    def windowDidResize_(self, _notification):
        if hasattr(self, "footer"):
            self._layout()

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
    def _segments(self, values, x, y, width, action):
        control = AppKit.NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(x, y, width, 28))
        control.setSegmentCount_(len(values))
        control.setTrackingMode_(AppKit.NSSegmentSwitchTrackingSelectOne)
        for index, title in enumerate(values):
            control.setLabel_forSegment_(title, index)
            control.setWidth_forSegment_(width / len(values) - 4, index)
        control.setSelectedSegment_(0)
        control.setTarget_(self)
        control.setAction_(action)
        self.content.addSubview_(control)
        return control

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

    @objc.python_method
    def _hotkey_summary(self) -> str:
        return (
            f"{self._hotkey('toggle')} — старт  •  "
            f"{self._hotkey('capture')} — точка  •  "
            f"{self._hotkey('stop')} — стоп"
        )

    def show(self) -> None:
        self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApp().activateIgnoringOtherApps_(True)

    @objc.python_method
    def _hotkey(self, action: str) -> str:
        return core.hotkey_name(self.hotkeys[action])

    def setSpeed_(self, sender: object) -> None:
        self.cps_field.setStringValue_(str(sender.tag()))
        self.speed_slider.setDoubleValue_(sender.tag())

    def slideSpeed_(self, sender):
        self.cps_field.setStringValue_(str(round(sender.doubleValue())))

    def controlTextDidChange_(self, notification):
        if notification.object() == self.cps_field:
            try:
                cps, _ = core.parse_settings(self.cps_field.stringValue(), "0")
            except ValueError:
                return
            self.speed_slider.setDoubleValue_(cps)

    def changeMouseButton_(self, _sender):
        pass

    def changeTarget_(self, _sender):
        if self.target_popup.selectedSegment() == 1 and self.fixed_position is None:
            self._set_status("ВЫБЕРИТЕ ТОЧКУ", "Нажмите «Выбрать точку» и щёлкните по цели. Esc — отмена.")

    @objc.python_method
    def _apply_appearance(self):
        names = {"Светлая": AppKit.NSAppearanceNameAqua, "Тёмная": AppKit.NSAppearanceNameDarkAqua}
        name = names.get(self.appearance["theme"])
        self.window.setAppearance_(AppKit.NSAppearance.appearanceNamed_(name) if name else None)
        colors = {
            "Синий": AppKit.NSColor.systemBlueColor(),
            "Фиолетовый": AppKit.NSColor.systemPurpleColor(),
            "Зелёный": AppKit.NSColor.systemGreenColor(),
        }
        color = colors[self.appearance["accent"]]
        self.start_button.setContentTintColor_(color)
        self.capture_button.setContentTintColor_(color)
        self.status_title_label.setTextColor_(color)

    def configureAppearance_(self, _sender):
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Оформление")
        alert.addButtonWithTitle_("Сохранить")
        alert.addButtonWithTitle_("Отмена")
        accessory = AppKit.NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, 80))
        selectors = {}
        for index, (key, title, values) in enumerate((("theme", "Тема", core.THEMES), ("accent", "Акцент", core.ACCENTS))):
            label = AppKit.NSTextField.labelWithString_(title)
            label.setFrame_(NSMakeRect(0, 48 - index * 36, 100, 22))
            accessory.addSubview_(label)
            popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(110, 46 - index * 36, 220, 26), False)
            popup.addItemsWithTitles_(values)
            popup.selectItemWithTitle_(self.appearance[key])
            accessory.addSubview_(popup)
            selectors[key] = popup
        alert.setAccessoryView_(accessory)
        if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
            return
        selected = {key: popup.titleOfSelectedItem() for key, popup in selectors.items()}
        try:
            core.save_appearance(selected["theme"], selected["accent"])
        except OSError as exc:
            self._show_alert("Не удалось сохранить оформление", str(exc))
            return
        self.appearance = selected
        self._apply_appearance()

    def toggleTopmost_(self, _sender: object) -> None:
        level = AppKit.NSFloatingWindowLevel if self.topmost_check.state() else AppKit.NSNormalWindowLevel
        self.window.setLevel_(level)

    def configureHotkeys_(self, _sender: object) -> None:
        if self.engine.running or self.countdown_timer is not None:
            return

        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Горячие клавиши")
        alert.setInformativeText_("Выберите отдельную F-клавишу для каждого действия.")
        alert.addButtonWithTitle_("Сохранить")
        alert.addButtonWithTitle_("Отмена")

        accessory = AppKit.NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 96))
        selectors: dict[str, object] = {}
        function_keys = tuple(code for code, name in core.KEY_NAMES.items() if name.startswith("F"))
        for index, (action, title) in enumerate(core.HOTKEY_ACTIONS):
            label = AppKit.NSTextField.labelWithString_(title)
            label.setFrame_(NSMakeRect(0, 68 - index * 32, 145, 20))
            accessory.addSubview_(label)
            popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(155, 65 - index * 32, 105, 26), False
            )
            for key_code in function_keys:
                popup.addItemWithTitle_(core.hotkey_name(key_code))
                popup.lastItem().setTag_(key_code)
            popup.selectItemWithTag_(self.hotkeys[action])
            accessory.addSubview_(popup)
            selectors[action] = popup
        alert.setAccessoryView_(accessory)

        if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
            return
        selected = {action: popup.selectedItem().tag() for action, popup in selectors.items()}
        if len(set(selected.values())) != len(selected):
            self._show_alert("Клавиши повторяются", "Для каждого действия выберите отдельную клавишу.")
            return
        try:
            core.save_hotkeys(selected)
        except OSError as exc:
            self._show_alert("Не удалось сохранить", str(exc))
            return
        self.hotkeys = selected
        self.hotkey_summary_label.setStringValue_(self._hotkey_summary())
        self._set_status("ГОТОВ", "Горячие клавиши сохранены")

    def capturePosition_(self, _sender: object) -> None:
        if self.engine.running or self.countdown_timer is not None or self.paused_config is not None or self.selection_windows:
            return
        self.window.orderOut_(None)
        try:
            for screen in AppKit.NSScreen.screens():
                frame = screen.frame()
                overlay = SelectionWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    frame, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False
                )
                self.selection_windows.append(overlay)
                overlay.setReleasedWhenClosed_(False)
                overlay.setOpaque_(False)
                overlay.setBackgroundColor_(AppKit.NSColor.clearColor())
                overlay.setLevel_(AppKit.NSStatusWindowLevel + 1)
                overlay.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
                view = PointSelectionView.alloc().initWithFrame_(NSMakeRect(0, 0, frame.size.width, frame.size.height))
                view.controller = self
                overlay.setContentView_(view)
                hint = AppKit.NSTextField.labelWithString_("Щёлкните по цели • Esc — отмена")
                hint.setFrame_(NSMakeRect(30, frame.size.height - 90, min(500, frame.size.width - 60), 36))
                hint.setFont_(AppKit.NSFont.boldSystemFontOfSize_(18))
                hint.setTextColor_(AppKit.NSColor.whiteColor())
                hint.setDrawsBackground_(True)
                hint.setBackgroundColor_(AppKit.NSColor.blackColor())
                view.addSubview_(hint)
                overlay.makeKeyAndOrderFront_(None)
                overlay.makeFirstResponder_(view)
            AppKit.NSApp().activateIgnoringOtherApps_(True)
        except Exception as exc:
            self._close_selection()
            self._show_alert("Не удалось открыть выбор точки", str(exc))

    @objc.python_method
    def _close_selection(self):
        windows, self.selection_windows = self.selection_windows, []
        for window in windows:
            window.contentView().controller = None
            window.close()
        if not self._closed:
            self.show()

    @objc.python_method
    def _cancel_point_selection(self):
        self._close_selection()
        self._set_status("ГОТОВ", "Выбор отменён. Предыдущая точка сохранена.")

    @objc.python_method
    def _finish_point_selection(self, point):
        if not self.selection_windows:
            return
        x, y = point
        self.fixed_position = (x, y)
        self.target_popup.setSelectedSegment_(1)
        self.position_label.setStringValue_(f"Сохранено: X {x:.0f}, Y {y:.0f}")
        self._close_selection()
        self._set_status("ГОТОВ", f"Точка сохранена. Нажмите {self._hotkey('toggle')} для запуска")

    def toggleClicking_(self, _sender: object) -> None:
        if self.selection_windows:
            return
        if self.engine.running:
            self._pause()
        elif self.countdown_timer is not None:
            self._stop_all()
        elif self.paused_config is not None:
            delay = 3 if _sender is not None and self.paused_config.fixed_position is None else 0
            self._schedule_start(self.paused_config, delay)
        else:
            self._start(from_button=_sender is not None)

    @objc.python_method
    def _start(self, *, from_button: bool = False) -> None:
        if self.selection_windows:
            return
        try:
            cps, delay = core.parse_settings(self.cps_field.stringValue(), self.delay_field.stringValue())
        except ValueError as exc:
            self._show_alert("Проверьте настройки", str(exc))
            return
        fixed = self.target_popup.selectedSegment() == 1
        if fixed and self.fixed_position is None:
            self._show_alert("Не выбрана точка", f"Нажмите {self._hotkey('capture')} и щёлкните по цели. Esc отменяет выбор.")
            return
        button_names = ("left", "right", "middle")
        config = core.ClickConfig(cps, button_names[self.button_popup.selectedSegment()], self.fixed_position if fixed else None)
        try:
            core.save_click_preferences(self.cps_field.stringValue(), self.delay_field.stringValue(), config.mouse_button)
        except OSError:
            pass
        effective_delay = delay or (3 if from_button and not fixed else 0)
        self._schedule_start(config, effective_delay)

    @objc.python_method
    def _schedule_start(self, config, delay):
        self._set_controls_enabled(False)
        self.stop_button.setEnabled_(True)
        self.active_config = config
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
        if self.countdown_timer is None or self._closed:
            return
        remaining = max(0, self.countdown_deadline - time.monotonic())
        if remaining <= 0:
            self.countdown_timer.invalidate()
            self.countdown_timer = None
            config, self.countdown_config = self.countdown_config, None
            self._begin_clicking(config)
            return
        self._set_status("СТАРТ ЧЕРЕЗ…", f"{remaining:.1f} сек. — наведите курсор на цель")
        self.start_button.setTitle_("Отменить запуск")

    @objc.python_method
    def _begin_clicking(self, config: core.ClickConfig) -> None:
        if self.engine.start(config):
            self.active_config = config
            self.paused_config = None
            destination = "в сохранённую точку" if config.fixed_position else "под курсором"
            self._set_status("РАБОТАЕТ", f"{config.cps:g} кликов/с, {destination}. {self._hotkey('stop')} — стоп")
            self.start_button.setTitle_("Пауза")

    @objc.python_method
    def _pause(self) -> None:
        if not self.engine.running or self.active_config is None:
            return
        self.engine.stop()
        self.paused_config = self.active_config
        self._set_status("НА ПАУЗЕ", f"Клики остановлены. {self._hotkey('toggle')} — продолжить")
        self.start_button.setTitle_("Продолжить")

    def stopClicking_(self, _sender: object) -> None:
        self._stop_all()

    @objc.python_method
    def _stop_all(self) -> None:
        if self.selection_windows:
            self._close_selection()
        if self.countdown_timer is not None:
            self.countdown_timer.invalidate()
            self.countdown_timer = None
        self.countdown_config = None
        self.engine.stop()
        self.active_config = None
        self.paused_config = None
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
                if self.selection_windows:
                    if payload in (53, self.hotkeys["stop"]):
                        self._cancel_point_selection()
                    continue
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
