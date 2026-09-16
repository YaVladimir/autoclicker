"""Portable checks for the conservative detector gate."""

from __future__ import annotations

import queue
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from golden_cookie_detector import (
    CandidateGate,
    GoldenCandidate,
    GoldenCookieFinder,
    GoldenCookieWatcher,
    ScreenRegion,
    detector_self_check,
)


FIXTURES = Path(__file__).parent / "fixtures" / "cookie_clicker"


def overlapping_ui_frames() -> tuple[object, object]:
    frame = cv2.imread(str(FIXTURES / "scene_overlapping_ui.png"))
    if frame is None:
        raise AssertionError("missing overlapping-UI screenshot")
    baseline = frame.copy()
    # Replace the cookie by adjacent buildings, border and spell icons.
    baseline[220:342, 1570:1690] = frame[220:342, 1390:1510]
    return baseline, frame


def wrath_red_background_frames() -> tuple[object, object]:
    frame = cv2.imread(str(FIXTURES / "scene_wrath_red_background.png"))
    if frame is None:
        raise AssertionError("missing wrath/red-background screenshot")
    baseline = frame.copy()
    baseline[652:788, 1470:1605] = frame[652:788, 958:1093]
    return baseline, frame


class ScreenRegionTests(unittest.TestCase):
    def test_normalises_corners(self) -> None:
        self.assertEqual(ScreenRegion.from_points((500, 420), (120, 100)), ScreenRegion(120, 100, 380, 320))

    def test_rejects_a_tiny_region(self) -> None:
        with self.assertRaises(ValueError):
            ScreenRegion.from_points((10, 10), (70, 70))


class CandidateGateTests(unittest.TestCase):
    def test_new_wrath_cookie_is_not_hidden_by_a_known_golden_object(self) -> None:
        gate = CandidateGate(required_frames=1)
        gate.learn([GoldenCandidate(100, 100, 30, .9)])
        wrath = GoldenCandidate(100, 100, 30, .9, "wrath")
        self.assertEqual(gate.choose([wrath]), wrath)

    def test_ignores_a_candidate_seen_during_calibration(self) -> None:
        icon = GoldenCandidate(100, 100, 40, .9)
        gate = CandidateGate()
        gate.learn([icon])
        self.assertIsNone(gate.choose([icon]))
        self.assertIsNone(gate.choose([icon]))

    def test_requires_two_frames_for_a_new_candidate(self) -> None:
        gate = CandidateGate(required_frames=2)
        cookie = GoldenCandidate(300, 200, 45, .95)
        confirmed = GoldenCandidate(303, 201, 45, .92)
        self.assertIsNone(gate.choose([cookie]))
        self.assertEqual(gate.choose([confirmed]), confirmed)

    def test_does_not_click_the_same_visible_candidate_twice(self) -> None:
        gate = CandidateGate(required_frames=2)
        cookie = GoldenCandidate(300, 200, 45, .95)
        gate.choose([cookie])
        self.assertEqual(gate.choose([cookie]), cookie)
        gate.mark_handled(cookie)
        self.assertIsNone(gate.choose([cookie]))
        self.assertIsNone(gate.choose([cookie]))

    def test_allows_a_new_cookie_at_the_old_position_after_it_disappears(self) -> None:
        gate = CandidateGate(required_frames=1)
        cookie = GoldenCandidate(300, 200, 45, .95)
        self.assertEqual(gate.choose([cookie]), cookie)
        gate.mark_handled(cookie)
        self.assertIsNone(gate.choose([]))
        self.assertEqual(gate.choose([cookie]), cookie)


class RealImageDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.finder = GoldenCookieFinder()
        self.baseline = cv2.imread(str(FIXTURES / "scene_baseline.jpg"))
        self.golden = cv2.imread(str(FIXTURES / "scene_golden.jpg"))
        self.assertIsNotNone(self.baseline)
        self.assertIsNotNone(self.golden)

    def test_real_game_scene_selects_new_golden_cookie(self) -> None:
        baseline_candidates = self.finder.find(self.baseline)
        golden_candidates = self.finder.find(self.golden)
        self.assertTrue(baseline_candidates, "the normal cookie is a realistic static false target")

        gate = CandidateGate(required_frames=2)
        gate.learn(baseline_candidates)
        self.assertIsNone(gate.choose(golden_candidates))
        target = gate.choose(golden_candidates)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertAlmostEqual(target.x, 688, delta=5)
        self.assertAlmostEqual(target.y, 348, delta=5)

    def test_real_game_scene_at_common_display_scales(self) -> None:
        for scale in (0.5, 0.75, 1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                baseline = cv2.resize(self.baseline, None, fx=scale, fy=scale, interpolation=interpolation)
                golden = cv2.resize(self.golden, None, fx=scale, fy=scale, interpolation=interpolation)
                gate = CandidateGate(required_frames=2)
                gate.learn(self.finder.find(baseline))
                candidates = self.finder.find(golden)
                self.assertIsNone(gate.choose(candidates))
                target = gate.choose(candidates)
                self.assertIsNotNone(target)
                assert target is not None
                self.assertAlmostEqual(target.x, 688 * scale, delta=6)
                self.assertAlmostEqual(target.y, 348 * scale, delta=6)

    def test_real_wrath_cookie_is_not_a_golden_candidate(self) -> None:
        sprite = cv2.imread(str(FIXTURES / "wrath_cookie.png"), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(sprite)
        for scale in (0.5, 0.75, 1.0, 1.5):
            with self.subTest(scale=scale):
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                resized = cv2.resize(sprite, None, fx=scale, fy=scale, interpolation=interpolation)
                frame = np.full((600, 800, 3), (58, 52, 45), dtype=np.uint8)
                height, width = resized.shape[:2]
                alpha = resized[:, :, 3:4] / 255.0
                background = frame[220:220 + height, 300:300 + width]
                background[:] = (resized[:, :, :3] * alpha + background * (1 - alpha)).astype(np.uint8)
                self.assertEqual(self.finder.find(frame), [])

    def test_wrath_sprite_is_detected_only_when_enabled(self) -> None:
        sprite = cv2.imread(str(FIXTURES / "wrath_cookie.png"), cv2.IMREAD_UNCHANGED)
        finder = GoldenCookieFinder(include_golden=False, include_wrath=True)
        for scale in (0.4, 0.5, 0.75, 1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                resized = cv2.resize(sprite, None, fx=scale, fy=scale)
                frame = np.full((600, 800, 3), (58, 52, 45), dtype=np.uint8)
                height, width = resized.shape[:2]
                alpha = resized[:, :, 3:4] / 255.0
                background = frame[220:220 + height, 300:300 + width]
                background[:] = (resized[:, :, :3] * alpha + background * (1 - alpha)).astype(np.uint8)
                candidates = finder.find(frame)
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0].kind, "wrath")
                self.assertAlmostEqual(candidates[0].x, 300 + width / 2, delta=5)
                self.assertAlmostEqual(candidates[0].y, 220 + height / 2, delta=5)

    def test_real_wrath_scene_with_and_without_target_at_common_scales(self) -> None:
        frame = cv2.imread(str(FIXTURES / "scene_wrath.png"))
        self.assertIsNotNone(frame)
        baseline = frame.copy()
        baseline[615:748, 1655:1790] = frame[615:748, 1143:1278]
        for scale in (0.5, 0.75, 1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                before = cv2.resize(baseline, None, fx=scale, fy=scale, interpolation=interpolation)
                after = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=interpolation)
                finder = GoldenCookieFinder(include_golden=False, include_wrath=True)
                self.assertEqual(finder.find(before), [], "red grandma artwork must not be clicked")
                candidates = finder.find(after)
                self.assertEqual(len(candidates), 1)
                target = candidates[0]
                self.assertEqual(target.kind, "wrath")
                self.assertAlmostEqual(target.x, 1726 * scale, delta=5)
                self.assertAlmostEqual(target.y, 682 * scale, delta=5)
                self.assertFalse(any(item.kind == "wrath" for item in self.finder.find(after)))

    def test_wrath_only_mode_ignores_a_golden_cookie(self) -> None:
        candidates = GoldenCookieFinder(include_golden=False, include_wrath=True).find(self.golden)
        self.assertEqual(candidates, [])

    def test_wrath_on_red_background_without_clicking_chocolate_or_decoration(self) -> None:
        baseline, frame = wrath_red_background_frames()
        finder = GoldenCookieFinder(include_wrath=True)
        for scale in (0.5, 0.75, 1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                before = cv2.resize(baseline, None, fx=scale, fy=scale, interpolation=interpolation)
                after = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=interpolation)
                known = finder.find(before)
                self.assertFalse(any(item.kind == "wrath" for item in known))
                gate = CandidateGate()
                gate.learn(known)
                self.assertIsNone(gate.choose(known))
                self.assertIsNone(gate.choose(known))
                candidates = finder.find(after)
                self.assertEqual(sum(item.kind == "wrath" for item in candidates), 1)
                self.assertIsNone(gate.choose(candidates))
                target = gate.choose(candidates)
                self.assertIsNotNone(target)
                assert target is not None
                self.assertEqual(target.kind, "wrath")
                self.assertAlmostEqual(target.x, 1538 * scale, delta=5)
                self.assertAlmostEqual(target.y, 719 * scale, delta=5)
                gate.mark_handled(target)
                self.assertIsNone(gate.choose(candidates))

    def test_wrath_at_other_positions_sizes_and_rotations_on_red_background(self) -> None:
        baseline, _ = wrath_red_background_frames()
        sprite = cv2.imread(str(FIXTURES / "wrath_cookie.png"), cv2.IMREAD_UNCHANGED)
        finder = GoldenCookieFinder(include_golden=False, include_wrath=True)
        for x, y, size, angle in ((1000, 560, 72, 20), (1750, 900, 96, 70), (1100, 1080, 144, 135)):
            with self.subTest(size=size, angle=angle):
                frame = baseline.copy()
                transform = cv2.getRotationMatrix2D((47.5, 47.5), angle, 1)
                rotated = cv2.warpAffine(sprite, transform, (96, 96))
                resized = cv2.resize(rotated, (size, size))
                alpha = resized[:, :, 3:4] / 255.0
                background = frame[y:y+size, x:x+size]
                background[:] = (resized[:, :, :3] * alpha + background * (1 - alpha)).astype(np.uint8)
                candidates = finder.find(frame)
                self.assertEqual(len(candidates), 1)
                self.assertAlmostEqual(candidates[0].x, x + size / 2, delta=5)
                self.assertAlmostEqual(candidates[0].y, y + size / 2, delta=5)

    def test_cookie_on_bright_yellow_milk_at_common_display_scales(self) -> None:
        frame = cv2.imread(str(FIXTURES / "scene_yellow_milk.png"))
        self.assertIsNotNone(frame)
        # Build a no-cookie frame using adjacent milk at the same height.
        # Preserve the rest of the full-resolution UI for calibration.
        baseline = frame.copy()
        baseline[915:1025, 170:290] = frame[915:1025, 330:450]
        for scale in (0.5, 0.75, 1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                before = cv2.resize(baseline, None, fx=scale, fy=scale, interpolation=interpolation)
                after = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=interpolation)
                gate = CandidateGate(required_frames=2)
                known = self.finder.find(before)
                gate.learn(known)
                self.assertIsNone(gate.choose(known))
                self.assertIsNone(gate.choose(known))

                candidates = self.finder.find(after)
                self.assertIsNone(gate.choose(candidates))
                target = gate.choose(candidates)
                self.assertIsNotNone(target, "cookie must stay distinct from yellow milk")
                assert target is not None
                self.assertAlmostEqual(target.x, 228 * scale, delta=5)
                self.assertAlmostEqual(target.y, 968 * scale, delta=5)
                gate.mark_handled(target)
                self.assertIsNone(gate.choose(candidates))

    def test_official_golden_sprite_at_common_scales(self) -> None:
        sprite = cv2.imread(str(FIXTURES / "gold_cookie.png"), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(sprite)
        for scale in (0.4, 0.5, 0.75, 1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                resized = cv2.resize(sprite, None, fx=scale, fy=scale, interpolation=interpolation)
                frame = np.full((600, 800, 3), (58, 52, 45), dtype=np.uint8)
                height, width = resized.shape[:2]
                alpha = resized[:, :, 3:4] / 255.0
                background = frame[220:220 + height, 300:300 + width]
                background[:] = (resized[:, :, :3] * alpha + background * (1 - alpha)).astype(np.uint8)
                candidates = self.finder.find(frame)
                self.assertEqual(len(candidates), 1)
                self.assertAlmostEqual(candidates[0].x, 300 + width / 2, delta=4)
                self.assertAlmostEqual(candidates[0].y, 220 + height / 2, delta=4)

    def test_cookie_on_cookie_background_at_common_display_scales(self) -> None:
        frame = cv2.imread(str(FIXTURES / "scene_cookie_background.png"))
        self.assertIsNotNone(frame)
        baseline = frame.copy()
        # The decorative background repeats vertically every 512 pixels.
        baseline[78:157, 90:174] = frame[590:669, 90:174]
        for scale in (0.5, 0.75, 1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                before = cv2.resize(baseline, None, fx=scale, fy=scale, interpolation=interpolation)
                after = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=interpolation)
                # The bright decorative cookies and white buildings must not
                # become candidates, even before learning a static baseline.
                self.assertEqual(self.finder.find(before), [])
                candidates = self.finder.find(after)
                self.assertEqual(len(candidates), 1)
                gate = CandidateGate()
                gate.learn(self.finder.find(before))
                self.assertIsNone(gate.choose(candidates))
                target = gate.choose(candidates)
                self.assertIsNotNone(target)
                assert target is not None
                self.assertAlmostEqual(target.x, 130 * scale, delta=5)
                self.assertAlmostEqual(target.y, 117 * scale, delta=5)
                gate.mark_handled(target)
                self.assertIsNone(gate.choose(candidates))

    def test_artwork_matcher_rejects_plain_bright_gold_and_white_discs(self) -> None:
        for colour in ((0, 205, 255), (255, 255, 255)):
            with self.subTest(colour=colour):
                frame = np.zeros((160, 160, 3), dtype=np.uint8)
                cv2.circle(frame, (80, 80), 32, colour, thickness=-1)
                self.assertIsNone(self.finder._verify_artwork(frame, GoldenCandidate(80, 80, 32, .9)))

    def test_cookie_over_buildings_border_and_icons_at_common_scales(self) -> None:
        baseline, frame = overlapping_ui_frames()
        for scale in (0.5, 0.75, 1.0, 1.25, 1.5):
            with self.subTest(scale=scale):
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                before = cv2.resize(baseline, None, fx=scale, fy=scale, interpolation=interpolation)
                after = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=interpolation)
                gate = CandidateGate()
                known = self.finder.find(before)
                gate.learn(known)
                self.assertIsNone(gate.choose(known))
                self.assertIsNone(gate.choose(known))
                candidates = self.finder.find(after)
                self.assertIsNone(gate.choose(candidates))
                target = gate.choose(candidates)
                self.assertIsNotNone(target)
                assert target is not None
                self.assertAlmostEqual(target.x, 1630 * scale, delta=5)
                self.assertAlmostEqual(target.y, 281 * scale, delta=5)
                gate.mark_handled(target)
                self.assertIsNone(gate.choose(candidates))

    def test_packaged_dependency_self_check(self) -> None:
        self.assertIsNone(detector_self_check())

    def test_overlapping_cookie_without_cpu_optimizations(self) -> None:
        # The generic OpenCV backend reproduces the macOS ARM failure at
        # 150% scale even on Windows. Restore global state for later tests.
        optimized = cv2.useOptimized()
        self.addCleanup(cv2.setUseOptimized, optimized)
        cv2.setUseOptimized(False)
        self.test_cookie_over_buildings_border_and_icons_at_common_scales()


class WatcherIntegrationTests(unittest.TestCase):
    def test_slow_first_frame_is_still_calibrated(self) -> None:
        candidate = GoldenCandidate(40, 40, 20, .9)
        watcher = GoldenCookieWatcher(ScreenRegion(0, 0, 160, 160), lambda point: self.fail("clicked baseline"), queue.SimpleQueue())

        class Finder:
            calls = 0

            def find(self, frame: object) -> list[GoldenCandidate]:
                self.calls += 1
                if self.calls == 3:
                    watcher._stop_event.set()
                return [candidate]

        with patch("golden_cookie_detector.time.monotonic", side_effect=(0, 2, 3)):
            watcher._watch(self._capture_frame, Finder())

    def test_wrath_candidate_emits_wrath_event_and_clicks_once(self) -> None:
        candidate = GoldenCandidate(40, 50, 25, .9, "wrath")
        clicked = []
        events = queue.SimpleQueue()
        watcher = GoldenCookieWatcher(ScreenRegion(-100, 200, 400, 300), clicked.append, events, warmup_seconds=0, frames_per_second=200)

        class Finder:
            calls = 0

            def find(self, frame: object) -> list[GoldenCandidate]:
                self.calls += 1
                if self.calls == 4:
                    watcher._stop_event.set()
                return [candidate]

        watcher._watch(self._capture_frame, Finder())
        self.assertEqual(clicked, [(-60, 250)])
        self.assertEqual(events.get_nowait(), (0, "wrath-caught", (-60, 250)))
        self.assertTrue(events.empty())

    @staticmethod
    def _capture_frame() -> object:
        return object()

    def test_real_overlapping_cookie_reaches_click_callback_with_screen_offset(self) -> None:
        baseline, golden = overlapping_ui_frames()
        frames = iter((baseline, golden, golden, golden, golden))
        captured = 0
        clicked: list[tuple[int, int]] = []
        events: queue.SimpleQueue[tuple[int, str, object]] = queue.SimpleQueue()

        def capture() -> object:
            nonlocal captured
            captured += 1
            if captured == 5:
                watcher._stop_event.set()
            return next(frames)

        watcher = GoldenCookieWatcher(
            ScreenRegion(-300, 50, golden.shape[1], golden.shape[0]),
            clicked.append, events, session_id=43, frames_per_second=200,
        )
        # Calibrate only the first frame; subsequent frames use the real finder
        # and watcher, including confirmation and duplicate-click prevention.
        with patch("golden_cookie_detector.time.monotonic", side_effect=(0, 0, 1, 1, 1)):
            watcher._watch(capture, GoldenCookieFinder())
        self.assertEqual(len(clicked), 1)
        self.assertAlmostEqual(clicked[0][0], 1330, delta=5)
        self.assertAlmostEqual(clicked[0][1], 331, delta=5)
        self.assertEqual(events.get_nowait(), (43, "golden-caught", clicked[0]))
        self.assertTrue(events.empty())

    def test_clicks_a_confirmed_candidate_once_and_tags_events(self) -> None:
        candidate = GoldenCandidate(25, 35, 20, .95)

        class Finder:
            def find(self, frame: object) -> list[GoldenCandidate]:
                return [candidate]

        clicked: list[tuple[int, int]] = []
        clicked_event = threading.Event()

        def click(point: tuple[int, int]) -> None:
            clicked.append(point)
            clicked_event.set()

        events: queue.SimpleQueue[tuple[int, str, object]] = queue.SimpleQueue()
        watcher = GoldenCookieWatcher(
            ScreenRegion(100, 200, 400, 300),
            click,
            events,
            session_id=42,
            frames_per_second=200,
            warmup_seconds=0,
            capture_frame=self._capture_frame,
            finder=Finder(),  # type: ignore[arg-type]
        )
        self.assertTrue(watcher.start())
        self.assertTrue(clicked_event.wait(1))
        self.assertTrue(watcher.stop())
        self.assertEqual(clicked, [(125, 235)])

        queued = []
        while not events.empty():
            queued.append(events.get_nowait())
        self.assertIn((42, "golden-caught", (125, 235)), queued)
        self.assertIn((42, "golden-stopped", None), queued)

    def test_stop_prevents_a_candidate_detected_in_flight_from_clicking(self) -> None:
        candidate = GoldenCandidate(25, 35, 20, .95)
        second_detection_started = threading.Event()
        release_detection = threading.Event()

        class BlockingFinder:
            def __init__(self) -> None:
                self.calls = 0

            def find(self, frame: object) -> list[GoldenCandidate]:
                self.calls += 1
                if self.calls == 2:
                    second_detection_started.set()
                    release_detection.wait(1)
                return [candidate]

        clicked: list[tuple[int, int]] = []
        events: queue.SimpleQueue[tuple[int, str, object]] = queue.SimpleQueue()
        watcher = GoldenCookieWatcher(
            ScreenRegion(100, 200, 400, 300),
            clicked.append,
            events,
            frames_per_second=200,
            warmup_seconds=0,
            capture_frame=self._capture_frame,
            finder=BlockingFinder(),  # type: ignore[arg-type]
        )
        self.assertTrue(watcher.start())
        self.assertTrue(second_detection_started.wait(1))

        stop_result: list[bool] = []
        stopper = threading.Thread(target=lambda: stop_result.append(watcher.stop()))
        stopper.start()
        deadline = time.monotonic() + 1
        while not watcher._stop_event.is_set() and time.monotonic() < deadline:
            time.sleep(.001)
        release_detection.set()
        stopper.join(1)

        self.assertEqual(stop_result, [True])
        self.assertEqual(clicked, [])
