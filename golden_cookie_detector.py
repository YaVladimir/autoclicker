"""Fast, conservative golden-cookie detection for the Windows app.

The detector deliberately does not try to recognise every image in Cookie
Clicker.  It first learns the colourful, static controls already present in a
user-selected game area.  Afterwards it considers only newly appeared,
round, bright-gold objects that remain visible in two consecutive frames.
That makes it much less likely to click a similar-looking UI icon.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, pi
import queue
import threading
import time
from typing import Callable, Iterable

_opencv_import_error: str | None = None
try:
    import cv2
    import numpy as np
except ImportError as exc:  # The rest of the autoclicker should still start normally.
    _opencv_import_error = str(exc)
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ScreenRegion:
    """A physical-pixel rectangle on the virtual Windows desktop."""

    left: int
    top: int
    width: int
    height: int

    @classmethod
    def from_points(cls, first: tuple[int, int], second: tuple[int, int]) -> "ScreenRegion":
        left, right = sorted((first[0], second[0]))
        top, bottom = sorted((first[1], second[1]))
        if right - left < 80 or bottom - top < 80:
            raise ValueError("Игровая область должна быть не меньше 80 × 80 пикселей.")
        return cls(left, top, right - left, bottom - top)


@dataclass(frozen=True)
class GoldenCandidate:
    """One plausible cookie centre, relative to the captured game area."""

    x: float
    y: float
    radius: float
    score: float


def missing_dependencies() -> str | None:
    """Return an installation hint without making importing the GUI fail."""
    missing: list[str] = []
    if cv2 is None or np is None:
        missing.append("OpenCV")
    try:
        import mss  # noqa: F401
    except ImportError:
        missing.append("mss")
    if not missing:
        return None
    return "Не установлены компоненты поиска: " + ", ".join(missing) + ". Запустите install_windows.bat."


class GoldenCookieFinder:
    """Find round, saturated yellow objects in one BGR screenshot."""

    def find(self, bgr_frame: object) -> list[GoldenCandidate]:
        if cv2 is None or np is None:
            raise RuntimeError(missing_dependencies() or "OpenCV недоступен.")
        frame = bgr_frame
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Cookie Clicker's golden cookie is both warm/yellow and much brighter
        # than the regular brown cookie.  A morphology pass joins its textured
        # pieces into one blob before circularity is measured.
        saturated_gold = cv2.inRange(hsv, np.array((12, 90, 130)), np.array((43, 255, 255)))
        warm_highlight = cv2.inRange(hsv, np.array((8, 45, 210)), np.array((52, 255, 255)))
        saturated_red = cv2.bitwise_or(
            cv2.inRange(hsv, np.array((0, 90, 80)), np.array((11, 255, 255))),
            cv2.inRange(hsv, np.array((170, 90, 80)), np.array((179, 255, 255))),
        )
        mask = cv2.bitwise_or(saturated_gold, warm_highlight)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        shortest_side = min(height, width)
        min_diameter = max(34.0, shortest_side * 0.035)
        max_diameter = shortest_side * 0.55
        candidates: list[GoldenCandidate] = []
        for contour in contours:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            diameter = (box_width + box_height) / 2
            if not min_diameter <= diameter <= max_diameter:
                continue
            # Controls touching the crop's edge are generally browser chrome,
            # not a complete in-game golden cookie.
            if x <= 2 or y <= 2 or x + box_width >= width - 2 or y + box_height >= height - 2:
                continue
            aspect = min(box_width, box_height) / max(box_width, box_height)
            if aspect < 0.72:
                continue
            area = float(cv2.contourArea(contour))
            box_area = box_width * box_height
            fill = area / box_area
            if fill < 0.28:
                continue
            perimeter = float(cv2.arcLength(contour, True))
            circularity = (4 * pi * area / (perimeter * perimeter)) if perimeter else 0.0
            if circularity < 0.34:
                continue
            # A wrath cookie has warm highlights too, but most of its body is
            # saturated red. Reject it before those highlights can pass the
            # generic round-object score.
            red_fraction = float(saturated_red[y:y + box_height, x:x + box_width].mean()) / 255
            if red_fraction >= 0.22:
                continue
            gold_fraction = float(mask[y:y + box_height, x:x + box_width].mean()) / 255
            score = 0.35 * aspect + 0.25 * min(fill / 0.70, 1.0) + 0.25 * min(circularity / 0.80, 1.0) + 0.15 * gold_fraction
            if score >= 0.70:
                candidates.append(GoldenCandidate(x + box_width / 2, y + box_height / 2, diameter / 2, score))
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


def _matches(first: GoldenCandidate, second: GoldenCandidate) -> bool:
    """Whether two frame-local candidates describe the same on-screen object."""
    allowed_distance = max(14.0, min(first.radius, second.radius) * 0.85)
    return hypot(first.x - second.x, first.y - second.y) <= allowed_distance


class CandidateGate:
    """Reject known static objects and require a candidate in consecutive frames."""

    def __init__(self, required_frames: int = 2) -> None:
        self.required_frames = required_frames
        self._baseline: list[GoldenCandidate] = []
        self._handled: list[GoldenCandidate] = []
        self._streak_candidate: GoldenCandidate | None = None
        self._streak_count = 0

    def learn(self, candidates: Iterable[GoldenCandidate]) -> None:
        for candidate in candidates:
            if not any(_matches(candidate, saved) for saved in self._baseline):
                self._baseline.append(candidate)

    def choose(self, candidates: Iterable[GoldenCandidate]) -> GoldenCandidate | None:
        seen = list(candidates)
        # A handled transient is forgotten only after it disappears, allowing a
        # later cookie at the same coordinates to be caught.
        self._handled = [item for item in self._handled if any(_matches(item, current) for current in seen)]
        new_items = [
            item for item in seen
            if not any(_matches(item, saved) for saved in self._baseline)
            and not any(_matches(item, saved) for saved in self._handled)
        ]
        if not new_items:
            self._streak_candidate = None
            self._streak_count = 0
            return None
        candidate = max(new_items, key=lambda item: item.score)
        if self._streak_candidate is not None and _matches(candidate, self._streak_candidate):
            self._streak_count += 1
        else:
            self._streak_candidate = candidate
            self._streak_count = 1
        return candidate if self._streak_count >= self.required_frames else None

    def mark_handled(self, candidate: GoldenCandidate) -> None:
        self._handled.append(candidate)
        self._streak_candidate = None
        self._streak_count = 0


class GoldenCookieWatcher:
    """Capture a selected region, click confirmed cookies, and report events."""

    def __init__(
        self,
        region: ScreenRegion,
        click_action: Callable[[tuple[int, int]], None],
        events: queue.SimpleQueue[tuple[int, str, object]],
        *,
        session_id: int = 0,
        frames_per_second: float = 8,
        warmup_seconds: float = 0.75,
        capture_frame: Callable[[], object] | None = None,
        finder: GoldenCookieFinder | None = None,
    ) -> None:
        self.region = region
        self._click_action = click_action
        self._events = events
        self.session_id = session_id
        self._frames_per_second = frames_per_second
        self._warmup_seconds = warmup_seconds
        self._capture_frame = capture_frame
        self._finder = finder
        self._stop_event = threading.Event()
        self._action_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        if self.running:
            return False
        dependency_error = missing_dependencies()
        if dependency_error:
            self._emit("golden-error", dependency_error)
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="GoldenCookieWatcher")
        self._thread.start()
        return True

    def stop(self, timeout: float = 1.0) -> bool:
        """Stop detection and prevent a click action from starting afterwards."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            # Close the race between the last stop check and the callback.
            # An active callback finishes; a pending one observes the stop flag.
            with self._action_lock:
                pass
            thread.join(timeout=timeout)
        return not self.running

    def _emit(self, name: str, payload: object) -> None:
        self._events.put((self.session_id, name, payload))

    def _run(self) -> None:
        try:
            finder = self._finder or GoldenCookieFinder()
            if self._capture_frame is not None:
                self._watch(self._capture_frame, finder)
            else:
                import mss

                monitor = {
                    "left": self.region.left,
                    "top": self.region.top,
                    "width": self.region.width,
                    "height": self.region.height,
                }
                with mss.mss() as screen:
                    self._watch(lambda: np.asarray(screen.grab(monitor))[:, :, :3], finder)
        except Exception as exc:  # Keep normal clicking alive if detection fails.
            if not self._stop_event.is_set():
                self._emit("golden-error", f"Поиск золотых печенек остановлен: {exc}")
        finally:
            self._emit("golden-stopped", None)

    def _watch(self, capture_frame: Callable[[], object], finder: GoldenCookieFinder) -> None:
        gate = CandidateGate()
        learning_ends = time.monotonic() + self._warmup_seconds
        next_frame = time.perf_counter()
        while not self._stop_event.is_set():
            image = capture_frame()
            candidates = finder.find(image)
            if self._stop_event.is_set():
                break
            if time.monotonic() < learning_ends:
                gate.learn(candidates)
            else:
                target = gate.choose(candidates)
                if target is not None:
                    point = (round(self.region.left + target.x), round(self.region.top + target.y))
                    with self._action_lock:
                        if self._stop_event.is_set():
                            break
                        self._click_action(point)
                    gate.mark_handled(target)
                    self._emit("golden-caught", point)
            now = time.perf_counter()
            next_frame += 1 / self._frames_per_second
            if now - next_frame > 1 / self._frames_per_second:
                next_frame = now
            self._stop_event.wait(max(0, next_frame - now))


def detector_self_check(*, check_capture_backend: bool = False) -> str | None:
    """Exercise packaged detector components without capturing or clicking."""
    dependency_error = missing_dependencies()
    if dependency_error:
        if _opencv_import_error:
            return f"{dependency_error} Причина OpenCV: {_opencv_import_error}"
        return dependency_error
    if check_capture_backend:
        try:
            import mss

            with mss.mss() as screen:
                if not screen.monitors:
                    return "mss загружен, но не обнаружил ни одного экрана."
        except Exception as exc:
            return f"mss загружен, но не может открыть экран: {exc}"
    frame = np.zeros((160, 160, 3), dtype=np.uint8)
    cv2.circle(frame, (80, 80), 32, (0, 205, 255), thickness=-1)
    if not GoldenCookieFinder().find(frame):
        return "OpenCV загружен, но контрольная золотая цель не распознана."
    return None
