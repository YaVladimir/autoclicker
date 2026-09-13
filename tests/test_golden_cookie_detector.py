"""Portable checks for the conservative detector gate."""

from __future__ import annotations

import queue
import threading
import time
import unittest
from pathlib import Path

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


class ScreenRegionTests(unittest.TestCase):
    def test_normalises_corners(self) -> None:
        self.assertEqual(ScreenRegion.from_points((500, 420), (120, 100)), ScreenRegion(120, 100, 380, 320))

    def test_rejects_a_tiny_region(self) -> None:
        with self.assertRaises(ValueError):
            ScreenRegion.from_points((10, 10), (70, 70))


class CandidateGateTests(unittest.TestCase):
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

    def test_packaged_dependency_self_check(self) -> None:
        self.assertIsNone(detector_self_check())


class WatcherIntegrationTests(unittest.TestCase):
    @staticmethod
    def _capture_frame() -> object:
        return object()

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
