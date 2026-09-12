"""Portable checks for the conservative detector gate."""

from __future__ import annotations

import unittest

from golden_cookie_detector import CandidateGate, GoldenCandidate, ScreenRegion


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
