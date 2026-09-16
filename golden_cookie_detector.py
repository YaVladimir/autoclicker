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
from pathlib import Path
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
    kind: str = "golden"


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
    """Find gold contours and verify circular edges by cookie artwork."""

    def __init__(self, *, include_golden: bool = True, include_wrath: bool = False) -> None:
        self.include_golden = include_golden
        self.include_wrath = include_wrath
        self._templates: dict[str, list[tuple[object, object]]] = {}

    def _load_templates(self, kind: str = "golden") -> list[tuple[object, object]]:
        if kind not in self._templates:
            filename = "wrath_cookie.png" if kind == "wrath" else "gold_cookie.png"
            path = Path(__file__).parent / "golden_cookie_assets" / filename
            sprite = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            gray = cv2.cvtColor(sprite[:, :, :3], cv2.COLOR_BGR2GRAY)
            mask = np.uint8(sprite[:, :, 3] > 240) * 255
            height, width = gray.shape
            templates = []
            for angle in range(0, 360, 5 if kind == "wrath" else 15):
                transform = cv2.getRotationMatrix2D(((width - 1) / 2, (height - 1) / 2), angle, 1)
                rotated = cv2.warpAffine(gray, transform, (width, height))
                rotated_mask = cv2.warpAffine(mask, transform, (width, height))
                for size in range(34, 53, 2):
                    templates.append((
                        cv2.resize(rotated, (size, size), interpolation=cv2.INTER_AREA),
                        cv2.resize(rotated_mask, (size, size), interpolation=cv2.INTER_NEAREST),
                    ))
            self._templates[kind] = templates
        return self._templates[kind]

    def _verify_artwork(self, frame: object, candidate: GoldenCandidate) -> GoldenCandidate | None:
        # Search only a small neighbourhood around a colour/shape candidate.
        # Normalising its size bounds matching cost even on a large display.
        x, y, padding = round(candidate.x), round(candidate.y), round(candidate.radius * 1.65)
        height, width = frame.shape[:2]
        left, top = max(0, x - padding), max(0, y - padding)
        right, bottom = min(width, x + padding + 1), min(height, y + padding + 1)
        # Keep geometry uniform when the neighbourhood reaches a crop edge.
        roi = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
        roi = cv2.copyMakeBorder(roi, top - (y - padding), y + padding + 1 - bottom,
                                left - (x - padding), x + padding + 1 - right, cv2.BORDER_REPLICATE)
        roi = cv2.resize(roi, (66, 66), interpolation=cv2.INTER_AREA)
        best_score, best_target = 0.0, None
        ratio = (2 * padding + 1) / 66
        templates = self._load_templates(candidate.kind)
        best_index = 0

        def compare(indices: Iterable[int]) -> None:
            nonlocal best_score, best_target, best_index
            for index in indices:
                template, mask = templates[index]
                result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED, mask=mask)
                result[~np.isfinite(result)] = -1
                _, score, _, location = cv2.minMaxLoc(result)
                if score > best_score:
                    best_score, best_index = score, index
                    size = template.shape[0]
                    best_target = GoldenCandidate(
                        x - padding + (location[0] + size / 2) * ratio,
                        y - padding + (location[1] + size / 2) * ratio,
                        size / 2 * ratio, candidate.score, candidate.kind,
                    )

        if candidate.kind == "wrath":
            # Wrath's sharp highlights need a finer rotation match. Search
            # coarse angles first, then refine only near the strongest angle.
            compare(index for index in range(len(templates)) if (index // 10) % 3 == 0)
            if best_score >= 0.30:
                best_angle = best_index // 10
                compare(((best_angle + offset) % 72) * 10 + size
                        for offset in (-2, -1, 1, 2) for size in range(10))
        else:
            compare(range(len(templates)))
        return best_target if best_score >= 0.52 else None

    def find(self, bgr_frame: object) -> list[GoldenCandidate]:
        if cv2 is None or np is None:
            raise RuntimeError(missing_dependencies() or "OpenCV недоступен.")
        frame = bgr_frame
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Keep the cookie's warm gold, but exclude the lemon-yellow milk
        # background (OpenCV hue ~30). Including that background merges a
        # cookie into a screen-sized blob, which the shape checks reject.
        # A morphology pass joins the remaining textured gold pieces.
        saturated_gold = cv2.inRange(hsv, np.array((12, 90, 130)), np.array((27, 255, 255)))
        warm_highlight = cv2.inRange(hsv, np.array((8, 45, 210)), np.array((27, 255, 255)))
        saturated_red = cv2.bitwise_or(
            cv2.inRange(hsv, np.array((0, 90, 80)), np.array((11, 255, 255))),
            cv2.inRange(hsv, np.array((170, 90, 80)), np.array((179, 255, 255))),
        )
        # Brown chocolate also falls into the broad warm-red range. Wrath
        # cookies additionally contain vivid scarlet, which separates their
        # texture from chocolate chips on the main cookie.
        scarlet = cv2.bitwise_or(
            cv2.inRange(hsv, np.array((0, 120, 150)), np.array((3, 255, 255))),
            cv2.inRange(hsv, np.array((174, 120, 150)), np.array((179, 255, 255))),
        ) if self.include_wrath else None
        gold_mask = cv2.bitwise_or(saturated_gold, warm_highlight)
        candidates = self._contour_candidates(gold_mask, saturated_red) if self.include_golden else []
        # Colour blobs can join background cookies, borders or white buildings.
        # Circular edges remain useful even when the colours are connected.
        # Hough's ALT method requires strong circular support; every remaining
        # candidate must also match the reference artwork before it can click.
        highlights = cv2.inRange(hsv, np.array((0, 0, 235)), np.array((30, 70, 255)))
        seeds = self._contour_candidates(highlights, saturated_red, min_pixel_diameter=24)
        if self.include_wrath:
            # Red regions only propose locations; unlike the gold colour path,
            # every red candidate must pass the wrath artwork verification.
            seeds.extend(self._contour_candidates(
                cv2.bitwise_and(saturated_red, cv2.inRange(hsv[:, :, 2], 190, 255)),
                saturated_red, min_pixel_diameter=24, reject_red=False,
            ))
        seeds.extend(self._circle_candidates(frame))
        if self.include_wrath:
            seeds.extend(self._circle_candidates(frame, textured_red=True))
        for candidate in seeds:
            x, y, radius = round(candidate.x), round(candidate.y), round(candidate.radius)
            top, bottom = max(0, y-radius), y+radius+1
            left, right = max(0, x-radius), x+radius+1
            gold_fraction = float(gold_mask[top:bottom, left:right].mean()) / 255
            red_fraction = float(saturated_red[top:bottom, left:right].mean()) / 255
            if candidate.kind == "wrath" and red_fraction < 0.22:
                continue
            if red_fraction >= 0.22:
                if not self.include_wrath:
                    continue
                if float(scarlet[top:bottom, left:right].mean()) / 255 < 0.02:
                    continue
                patch = hsv[top:bottom, left:right]
                pale_fraction = float(((patch[:, :, 1] < 90) & (patch[:, :, 2] > 210)).mean())
                warm_fraction = float(((patch[:, :, 0] > 11) & (patch[:, :, 0] < 35) & (patch[:, :, 2] > 210)).mean())
                if pale_fraction < 0.025 or warm_fraction < 0.07:
                    continue
                candidate = GoldenCandidate(candidate.x, candidate.y, candidate.radius, candidate.score, "wrath")
            elif not self.include_golden or gold_fraction < 0.20:
                continue
            if any(_matches(candidate, existing) for existing in candidates):
                continue
            verified = self._verify_artwork(frame, candidate)
            if verified is not None and verified.kind == "wrath":
                # Matching searches a neighbourhood and can move the centre.
                # Recheck colour at that final position before accepting it.
                vx, vy, vr = round(verified.x), round(verified.y), round(verified.radius)
                if float(scarlet[max(0, vy-vr):vy+vr+1, max(0, vx-vr):vx+vr+1].mean()) / 255 < 0.02:
                    continue
            if verified is not None and not any(_matches(verified, existing) for existing in candidates):
                candidates.append(verified)
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)

    @staticmethod
    def _circle_candidates(frame: object, *, textured_red: bool = False) -> list[GoldenCandidate]:
        height, width = frame.shape[:2]
        scale = min(1.0, 1280 / max(height, width))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if scale < 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        candidates = []
        # A single smoothing scale can erase a cookie edge against textured
        # backgrounds, with results varying between OpenCV CPU backends.
        # Propose both fine and smoothed edges for golden and wrath cookies;
        # colour and artwork still decide whether a candidate can be clicked.
        for kernel_size in ((3, 5) if textured_red else (5, 3)):
            smoothed = cv2.GaussianBlur(gray, (kernel_size, kernel_size), 1)
            circles = cv2.HoughCircles(
                smoothed, cv2.HOUGH_GRADIENT_ALT, dp=1.5, minDist=15,
                param1=150, param2=0.7 if textured_red else 0.8, minRadius=10,
                maxRadius=max(11, min(100, round(min(gray.shape) * 0.45))),
            )
            if circles is None:
                continue
            for x, y, radius in circles[0] / scale:
                # Do not click incomplete targets cut by the selected game region.
                if x-radius <= 2 or y-radius <= 2 or x+radius >= width-2 or y+radius >= height-2:
                    continue
                if any(hypot(x - item.x, y - item.y) < min(radius, item.radius) * 0.20
                       and abs(radius - item.radius) < min(radius, item.radius) * 0.15
                       for item in candidates):
                    continue
                candidates.append(GoldenCandidate(float(x), float(y), float(radius), 0.9,
                                                  "wrath" if textured_red else "golden"))
        return candidates

    @staticmethod
    def _contour_candidates(mask: object, saturated_red: object, *, min_pixel_diameter: int = 34, reject_red: bool = True) -> list[GoldenCandidate]:
        height, width = mask.shape[:2]
        # Join texture gaps at high display scales as well as on smaller
        # captures. The kernel must have an odd size for a centred anchor.
        kernel_size = max(7, round(min(height, width) * 0.005)) | 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        shortest_side = min(height, width)
        min_diameter = max(float(min_pixel_diameter), shortest_side * 0.035)
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
            if reject_red and red_fraction >= 0.22:
                continue
            gold_fraction = float(mask[y:y + box_height, x:x + box_width].mean()) / 255
            score = 0.35 * aspect + 0.25 * min(fill / 0.70, 1.0) + 0.25 * min(circularity / 0.80, 1.0) + 0.15 * gold_fraction
            if score >= 0.70:
                candidates.append(GoldenCandidate(x + box_width / 2, y + box_height / 2, diameter / 2, score))
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


def _matches(first: GoldenCandidate, second: GoldenCandidate) -> bool:
    """Whether two frame-local candidates describe the same on-screen object."""
    allowed_distance = max(14.0, min(first.radius, second.radius) * 0.85)
    return first.kind == second.kind and hypot(first.x - second.x, first.y - second.y) <= allowed_distance


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
                self._emit("golden-error", f"Поиск печенек остановлен: {exc}")
        finally:
            self._emit("golden-stopped", None)

    def _watch(self, capture_frame: Callable[[], object], finder: GoldenCookieFinder) -> None:
        gate = CandidateGate()
        learning_ends = time.monotonic() + self._warmup_seconds
        learning_frames = 0
        next_frame = time.perf_counter()
        while not self._stop_event.is_set():
            image = capture_frame()
            candidates = finder.find(image)
            if self._stop_event.is_set():
                break
            if time.monotonic() < learning_ends or (learning_frames == 0 and self._warmup_seconds > 0):
                gate.learn(candidates)
                learning_frames += 1
            else:
                target = gate.choose(candidates)
                if target is not None:
                    point = (round(self.region.left + target.x), round(self.region.top + target.y))
                    with self._action_lock:
                        if self._stop_event.is_set():
                            break
                        self._click_action(point)
                    gate.mark_handled(target)
                    self._emit("wrath-caught" if target.kind == "wrath" else "golden-caught", point)
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
    finder = GoldenCookieFinder()
    if not finder.find(frame):
        return "OpenCV загружен, но контрольная золотая цель не распознана."
    try:
        # Exercise the bundled reference and masked matcher as well as the
        # colour path: a missing asset must fail the packaged self-check.
        for kind in ("golden", "wrath"):
            template, mask = finder._load_templates(kind)[0]
            size = template.shape[0]
            frame[:] = 0
            patch = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
            patch[mask == 0] = 0
            offset = 80 - size // 2
            frame[offset:offset + size, offset:offset + size] = patch
            if finder._verify_artwork(frame, GoldenCandidate(80, 80, size / 2, 1.0, kind)) is None:
                return "Образец загружен, но проверка рисунка золотой печеньки не пройдена."
    except Exception as exc:
        return f"Не удалось проверить образец золотой печеньки: {exc}"
    return None
