"""Integration tests: uv run --with numpy python -m unittest rl.test_client -v"""
import time
import unittest
from unittest.mock import patch

import numpy as np

from rl import Action, Pinball


class EngineTests(unittest.TestCase):
    def test_steps_frames_controls_episode_and_reset(self):
        with Pinball(width=320, height=240) as game:
            print("\nRenderer:", game.engine_info, flush=True)
            first = game.step(physics_ticks=0)
            self.assertEqual(first.ticks, 0)
            self.assertEqual(first.score, 0)
            self.assertFalse(first.started)
            self.assertFalse(first.game_over)
            self.assertEqual(first.frame.shape, (240, 320, 3))
            self.assertEqual(first.frame.dtype, np.uint8)
            self.assertGreater(first.frame.std(), 10)
            saved_first = first.frame.copy()
            time.sleep(0.2)
            paused = game.step(physics_ticks=0)
            self.assertEqual(paused.ticks, 0)
            self.assertEqual(paused.score, 0)
            # Temporal dithering can vary pixels even with a frozen simulation.
            self.assertLess(np.abs(first.frame.astype(float) - paused.frame).mean(), 3)

            left = game.step(Action(left=True), physics_ticks=200)
            right = game.step(Action(right=True), physics_ticks=200)
            self.assertEqual(right.ticks, 400)
            self.assertFalse(np.array_equal(left.frame, right.frame))
            # Holding an action does not retrigger start/launch every step.
            launched = game.step(Action(start=True), physics_ticks=999)
            self.assertTrue(launched.started)
            self.assertTrue(launched.launch_pending)
            released = game.step(Action(start=True), physics_ticks=1)
            self.assertEqual(released.ticks, 1400)
            self.assertFalse(released.launch_pending)
            held = game.step(Action(start=True), physics_ticks=1)
            self.assertFalse(held.launch_pending)
            # Frames are owned by observations, not overwritten by later steps.
            np.testing.assert_array_equal(first.frame, saved_first)

            # Exercise an entire episode using only valid robot actions.
            score = 0
            for i in range(300):
                obs = game.step(Action(start=i % 2 == 0), physics_ticks=1000)
                self.assertGreaterEqual(obs.score, score)
                score = obs.score
                if obs.game_over:
                    break
            self.assertTrue(obs.game_over, "No terminal state within 300 simulated seconds")
            self.assertEqual(obs.balls_left, 0)
            self.assertGreater(obs.score, 0)
            terminal = game.step(Action(start=True), physics_ticks=1000)
            self.assertTrue(terminal.game_over)
            self.assertEqual(terminal.score, obs.score)
            process, display, directory = game._proc, game._xvfb, game.log_path.parent
            reset = game.reset()
            self.assertIs(game._proc, process)
            self.assertIs(game._xvfb, display)
            self.assertEqual(game.log_path.parent, directory)
            self.assertEqual(reset.ticks, 0)
            self.assertEqual(reset.score, 0)
            self.assertEqual(reset.balls_left, 1)
            self.assertFalse(reset.started)
            self.assertFalse(reset.game_over)
        self.assertIsNotNone(process.poll())
        self.assertIsNotNone(display.poll())
        self.assertFalse(directory.exists())
        game.close()  # idempotent
        with self.assertRaisesRegex(RuntimeError, "closed"):
            game.reset()

    def test_midgame_reset_keeps_process_and_clears_launch_and_button_state(self):
        with Pinball(width=320, height=240) as game:
            process, display, sock = game._proc, game._xvfb, game._sock
            with patch.object(game, "_launch", side_effect=AssertionError("reset must never relaunch")):
                for _ in range(12):
                    game.step(Action(left=True, right=True, start=True), physics_ticks=100)
                    obs = game.reset()
                    self.assertEqual((obs.ticks, obs.score, obs.active_target, obs.balls_left), (0, 0, 1, 1))
                    self.assertFalse(obs.started or obs.game_over or obs.launch_pending)
                    self.assertIs(game._proc, process)
                    self.assertIs(game._xvfb, display)
                    self.assertIs(game._sock, sock)
                    # A held start from the previous episode must be a fresh edge now.
                    obs = game.step(Action(start=True), physics_ticks=999)
                    self.assertTrue(obs.started and obs.launch_pending)
                    self.assertFalse(game.step(Action(start=True), physics_ticks=1).launch_pending)

    def test_validation_and_protocol_recovery(self):
        with Pinball(width=320, height=240) as game:
            for ticks in (-1, 10001, 1.5, True):
                with self.assertRaises(ValueError):
                    game.step(physics_ticks=ticks)
            with self.assertRaises(ValueError):
                game.step(Action(left=1))
            game._sock.sendall(b"step 0 0 0 10001\n")
            with self.assertRaisesRegex(RuntimeError, "Expected step"):
                game._header()
            self.assertEqual(game.step(physics_ticks=3).ticks, 3)


if __name__ == "__main__":
    unittest.main()
