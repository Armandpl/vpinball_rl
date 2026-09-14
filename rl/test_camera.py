"""uv run --with numpy python -m unittest rl.test_camera -v"""
import unittest

import numpy as np

from rl import Camera, Pinball
from rl.camera import MM_PER_VPU


class CameraMathTests(unittest.TestCase):
    def test_pose_and_intrinsics(self):
        camera = Camera(cx=610, cy=345, x_mm=30, y_mm=70)
        view, proj = camera.matrices(1344, 760)
        eye = np.array([30, 70, 406.4, 1])
        eye[:3] /= MM_PER_VPU
        np.testing.assert_allclose((eye @ view)[:3], 0, atol=1e-10)
        np.testing.assert_allclose(view[:3, :3].T @ view[:3, :3], np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(view[:3, :3]), 1)
        # Pinhole projection: camera +Y points upward, pixel +Y downward.
        point = np.array([20, 30, 100, 1])
        clip = point @ proj
        ndc = clip[:2] / clip[3]
        pixel = np.array([(ndc[0] + 1) * 1344 / 2, (1 - ndc[1]) * 760 / 2])
        np.testing.assert_allclose(pixel, [camera.fx * .2 + camera.cx, camera.cy - camera.fy * .3])
        # At half resolution K scales, preserving the same frustum.
        np.testing.assert_allclose(proj, camera.matrices(672, 380)[1])
        self.assertEqual(len(camera.serialize(1344, 760).split()), 32)

    def test_optical_axis_hits_plane_sixteen_inches_from_anchor_toward_bumpers(self):
        camera = Camera()
        view, _ = camera.matrices(1344, 760)
        target = np.array([0, -406.4 / MM_PER_VPU, 0, 1])
        at = target @ view
        np.testing.assert_allclose(at[:2], 0, atol=1e-10)
        self.assertGreater(at[2], 0)

    def test_clockwise_physical_roll_preserves_sensor_intrinsics(self):
        base, proj = Camera(roll_degrees=0, cx=610, cy=345).matrices(1344, 760)
        rolled, rolled_proj = Camera(roll_degrees=90, cx=610, cy=345).matrices(1344, 760)
        np.testing.assert_allclose(rolled_proj, proj)
        # A point right of the unrolled optical axis moves upward in the raw image.
        point = np.array([100, 0, 1000, 1]) @ np.linalg.inv(base)
        np.testing.assert_allclose(point @ rolled, [0, 100, 1000, 1], atol=1e-10)
        clip = point @ rolled @ rolled_proj
        self.assertAlmostEqual((clip[0] / clip[3] + 1) * 1344 / 2, 610)
        self.assertLess((1 - clip[1] / clip[3]) * 760 / 2, 345)
        np.testing.assert_allclose(base[:3, 2], rolled[:3, 2])  # Aim did not change.

    def test_validation(self):
        for camera in (Camera(fx=0), Camera(height_mm=-1), Camera(tilt_degrees=0),
                       Camera(near_mm=20, far_mm=10), Camera(cx=float("nan")),
                       Camera(calibration_width=0), Camera(roll_degrees=float("inf")), Camera(anchor="invalid")):
            with self.assertRaises(ValueError):
                camera.matrices(1344, 760)


class CameraEngineTests(unittest.TestCase):
    def test_camera_render_and_reset(self):
        with Pinball(width=336, height=190, camera=Camera()) as game:
            initial = game.step(physics_ticks=0)
            self.assertEqual(initial.frame.shape, (190, 336, 3))
            self.assertGreater(initial.frame.std(), 10)
            reset = game.reset()
            self.assertEqual(reset.ticks, 0)
            # Game reset retains the calibrated view, but unlike a cold restart
            # it need not reproduce initial lighting/animation transients exactly.
            self.assertEqual(reset.frame.shape, initial.frame.shape)
            self.assertLess(np.abs(initial.frame.astype(float) - reset.frame).mean(), 10)
        with Pinball(width=336, height=190, camera=Camera(anchor="center")) as game:
            centered = game.step(physics_ticks=0)
            self.assertGreater(np.abs(initial.frame.astype(float) - centered.frame).mean(), 10)


if __name__ == "__main__":
    unittest.main()
