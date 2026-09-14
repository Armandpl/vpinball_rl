"""Pinhole calibration with a world-to-camera transform in millimeters."""
from dataclasses import dataclass

import numpy as np

MM_PER_VPU = 25.4 * 1.0625 / 50


@dataclass(frozen=True)
class Camera:
    intrinsics: np.ndarray  # 3x3 K for calibration_size.
    extrinsics: np.ndarray  # 4x4 column-vector world-to-camera; X right, Y down, Z forward.
    calibration_size: tuple[int, int] = (1344, 760)
    anchor: str = "flipper_end"  # World origin centered at the flipper-end edge.
    near_mm: float = 1.0
    far_mm: float = 10000.0

    def matrices(self, width, height):
        k = np.asarray(self.intrinsics, dtype=float)
        e = np.asarray(self.extrinsics, dtype=float)
        if k.shape != (3, 3) or e.shape != (4, 4):
            raise ValueError("Expected 3x3 intrinsics and 4x4 extrinsics")
        if not np.isfinite(k).all() or not np.isfinite(e).all():
            raise ValueError("Camera matrices must be finite")
        if (not np.allclose(k[2], [0, 0, 1]) or k[1, 0] != 0
                or k[0, 0] <= 0 or k[1, 1] <= 0):
            raise ValueError("Invalid pinhole intrinsics")
        if (not np.allclose(e[3], [0, 0, 0, 1])
                or not np.allclose(e[:3, :3] @ e[:3, :3].T, np.eye(3))
                or not np.isclose(abs(np.linalg.det(e[:3, :3])), 1)):
            raise ValueError("Extrinsics must have orthonormal axes and a homogeneous last row")
        if self.anchor not in ("center", "flipper_end"):
            raise ValueError("Unknown camera anchor")
        if not 0 < self.near_mm < self.far_mm < float("inf"):
            raise ValueError("Invalid clipping range")
        if any(type(v) is not int or v <= 0 for v in (*self.calibration_size, width, height)):
            raise ValueError("Image dimensions must be positive integers")
        # Native renderer uses row vectors and camera Y up, with VPU distances.
        view = e.copy()
        view[:3, 3] /= MM_PER_VPU
        view[1] *= -1
        view = view.T
        k = np.diag([width / self.calibration_size[0], height / self.calibration_size[1], 1]) @ k
        near, far = self.near_mm / MM_PER_VPU, self.far_mm / MM_PER_VPU
        proj = np.zeros((4, 4))
        proj[0, 0], proj[1, 1] = 2 * k[0, 0] / width, 2 * k[1, 1] / height
        proj[1, 0] = -2 * k[0, 1] / width
        proj[2] = (2 * k[0, 2] / width - 1, 1 - 2 * k[1, 2] / height, far / (far - near), 1)
        proj[3, 2] = -far * near / (far - near)
        return view, proj

    def serialize(self, width, height):
        return " ".join(format(v, ".17g") for matrix in self.matrices(width, height)
                        for v in matrix.flat)
