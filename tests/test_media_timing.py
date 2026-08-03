import unittest

from app.core.media_timing import FrameTimeMap


class FrameTimeMapTests(unittest.TestCase):
    def test_vfr_map_round_trips_actual_timestamps(self):
        timing = FrameTimeMap.from_timestamps([0, 66.667, 133.333, 1200, 2600])

        self.assertEqual(timing.timestamp_for_frame(4), 1200)
        self.assertEqual(timing.timestamp_for_frame(5), 2600)
        self.assertEqual(timing.frame_for_timestamp(1199), 3)
        self.assertEqual(timing.frame_for_timestamp(1200), 4)

    def test_fixed_fps_fallback_uses_one_based_frames(self):
        timing = FrameTimeMap.from_fps(90, 30.0)

        self.assertEqual(timing.timestamp_for_frame(1), 0)
        self.assertEqual(timing.timestamp_for_frame(19), 600)
        self.assertEqual(timing.frame_for_timestamp(600), 19)

    def test_values_are_clamped_and_monotonic(self):
        timing = FrameTimeMap.from_timestamps([-5, 20, 10])

        self.assertEqual(timing.timestamps_ms, (0, 20, 20))
        self.assertEqual(timing.timestamp_for_frame(99), 20)


if __name__ == "__main__":
    unittest.main()
