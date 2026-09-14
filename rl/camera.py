"""Pinhole camera, positioned in physical units relative to a native table anchor."""
from dataclasses import dataclass
import math

import numpy as np

MM_PER_VPU = 25.4 * 1.0625 / 50  # VPX's native unit convention; no table rescaling.


@dataclass(frozen=True)
class Camera:
    fx: float = 1141.5
    fy: float = 1141.5
    cx: float = 672.0
    cy: float = 380.0
    calibration_width: int = 1344
    calibration_height: int = 760
    height_mm: float = 16 * 25.4
    tilt_degrees: float = 45.0  # Down from the playfield plane, 90 = straight down.
    roll_degrees: float = 90.0  # Clockwise physical roll, viewed from behind the camera toward the scene.
    anchor: str = "flipper_end"  # Centered left/right, at the flipper-end playfield edge.
    x_mm: float = 0.0  # Rightward offset from the anchor.
    y_mm: float = 0.0  # Offset toward the player from the anchor (negative moves into table).
    near_mm: float = 1.0
    far_mm: float = 10000.0

    def matrices(self, width, height):
        if self.anchor not in ("center", "flipper_end"):
            raise ValueError("Camera anchor must be center or flipper_end")
        values = (self.fx, self.fy, self.cx, self.cy, self.height_mm, self.tilt_degrees,
                  self.roll_degrees, self.x_mm, self.y_mm, self.near_mm, self.far_mm)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Camera parameters must be finite")
        if (self.fx <= 0 or self.fy <= 0 or self.height_mm <= 0
                or not 0 < self.tilt_degrees <= 90 or not 0 < self.near_mm < self.far_mm):
            raise ValueError("Invalid focal length, height, tilt or clipping range")
        if any(type(v) is not int or v <= 0 for v in
               (width, height, self.calibration_width, self.calibration_height)):
            raise ValueError("Camera image dimensions must be positive integers")
        angle = math.radians(self.tilt_degrees)
        s, c = math.sin(angle), math.cos(angle)
        # VPX uses row-vector matrices. View axes: right, up, forward (+Z).
        # Native table axes: +X right, +Y toward flippers, +Z above playfield.
        view = np.eye(4)
        view[:3, :3] = np.array([[1, 0, 0], [0, -s, -c], [0, c, -s]])
        roll = math.radians(self.roll_degrees)
        sr, cr = math.sin(roll), math.cos(roll)
        # Physical clockwise roll makes the scene turn counterclockwise on the sensor.
        view[:3, :3] = view[:3, :3] @ np.array([[cr, sr, 0], [-sr, cr, 0], [0, 0, 1]])
        eye = np.array([self.x_mm, self.y_mm, self.height_mm]) / MM_PER_VPU
        view[3, :3] = -eye @ view[:3, :3]
        # Scale K when rendering at a different resolution, without fitting the scene.
        fx, cx = self.fx * width / self.calibration_width, self.cx * width / self.calibration_width
        fy, cy = self.fy * height / self.calibration_height, self.cy * height / self.calibration_height
        near, far = self.near_mm / MM_PER_VPU, self.far_mm / MM_PER_VPU
        proj = np.zeros((4, 4))
        proj[0, 0], proj[1, 1] = 2 * fx / width, 2 * fy / height
        proj[2] = (2 * cx / width - 1, 1 - 2 * cy / height, far / (far - near), 1)
        proj[3, 2] = -far * near / (far - near)
        return view, proj

    def serialize(self, width, height):
        return " ".join(format(v, ".17g") for matrix in self.matrices(width, height)
                        for v in matrix.flat)
