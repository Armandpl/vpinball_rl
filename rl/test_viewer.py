"""Pure pacing tests: uv run --with numpy python -m unittest rl.test_viewer -v"""
import unittest

from rl.viewer import ViewerClock


class ViewerClockTests(unittest.TestCase):
    def test_sixty_hz_display_does_not_slow_simulation(self):
        clock = ViewerClock(16, 0)
        self.assertEqual(clock.ticks_due(0), 16)
        ticks = [clock.ticks_due(frame / 60) for frame in range(1, 61)]
        self.assertEqual(sum(ticks), 1000)  # Old fixed 16ms/frame pacing yielded 960.
        self.assertEqual(set(ticks), {16, 17})

    def test_slow_capture_catches_up_without_changing_tick_duration(self):
        clock = ViewerClock(16, 0)
        clock.ticks_due(0)
        self.assertEqual(sum(clock.ticks_due(frame / 25) for frame in range(1, 26)), 1000)

    def test_deadlines_do_not_accumulate_sleep_overshoot(self):
        clock = ViewerClock(16, 0)
        self.assertAlmostEqual(clock.sleep_seconds(.008), .008)
        # Sleep overshot by 1ms; the following frame still targets 32ms, not 33ms.
        self.assertAlmostEqual(clock.sleep_seconds(.025), .007)

    def test_long_stall_is_bounded_and_does_not_leave_backlog(self):
        clock = ViewerClock(16, 0)
        clock.ticks_due(0)
        self.assertEqual(clock.ticks_due(5), 250)
        self.assertEqual(clock.ticks_due(5.016), 16)
        self.assertEqual(clock.sleep_seconds(5.030), 0)

    def test_new_clock_after_reset_has_no_startup_debt(self):
        clock = ViewerClock(16, 100)
        self.assertEqual(clock.ticks_due(100), 16)
        self.assertAlmostEqual(clock.sleep_seconds(100.008), .008)


if __name__ == '__main__':
    unittest.main()
