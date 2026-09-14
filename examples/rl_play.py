# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.26", "raylib>=6.0.1.0"]
# ///
"""Generate the table with `uv run vprl/build_table.py`, then run this script."""
from pathlib import Path
import sys

import numpy as np
import pyray as ray

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vprl import Action, Camera, Pinball

WIDTH, HEIGHT = 1344, 760
INTRINSICS = np.array([[1141.5, 0, 672], [0, 1141.5, 380], [0, 0, 1]])
# Column-vector world-to-camera, millimeters; camera axes right/down/forward.
# World: X right, Y toward player, Z up; origin at flipper-end edge center.
# 16 inches above origin, 45 degrees down toward bumpers, 90-degree clockwise roll.
EXTRINSICS = np.array([
    [0, 2**-0.5, -2**-0.5, 406.4 * 2**-0.5],
    [-1, 0, 0, 0],
    [0, -2**-0.5, -2**-0.5, 406.4 * 2**-0.5],
    [0, 0, 0, 1],
])


def main():
    ray.init_window(HEIGHT, WIDTH, "VPX RL")
    ray.set_target_fps(60)
    texture = None
    try:
        with Pinball(width=WIDTH, height=HEIGHT,
                     camera=Camera(INTRINSICS, EXTRINSICS)) as pinball:
            obs = pinball.step(physics_ticks=0)
            # Only the display rotates; API frames retain raw sensor orientation.
            displayed = np.ascontiguousarray(np.rot90(obs.frame, -1))
            image = ray.Image(ray.ffi.from_buffer(displayed), HEIGHT, WIDTH,
                              1, ray.PIXELFORMAT_UNCOMPRESSED_R8G8B8)
            texture = ray.load_texture_from_image(image)
            if not texture.id:
                raise RuntimeError("Could not create frame texture")
            # Image borrows NumPy memory; do not call unload_image.
            print("Left: left Shift; right: right Shift; quit: Esc")
            previous = ray.get_time()
            remainder = 0.0
            while not ray.window_should_close():
                now = ray.get_time()
                remainder += min(now - previous, 0.25) * 1000
                previous = now
                ticks = int(remainder)
                remainder -= ticks
                action = Action(
                    bool(ray.is_key_down(ray.KEY_LEFT_SHIFT)),
                    bool(ray.is_key_down(ray.KEY_RIGHT_SHIFT)),
                )
                obs = pinball.step(action, physics_ticks=ticks)
                if obs.game_over:
                    print(f"reset (game over, score={obs.score})", flush=True)
                    obs = pinball.reset()
                    previous, remainder = ray.get_time(), 0.0
                displayed = np.ascontiguousarray(np.rot90(obs.frame, -1))
                ray.update_texture(texture, ray.ffi.cast("void *", ray.ffi.from_buffer(displayed)))
                ray.set_window_title(f"VPX RL | {ray.get_fps()} FPS | score {obs.score}")
                ray.begin_drawing()
                ray.clear_background(ray.BLACK)
                ray.draw_texture(texture, 0, 0, ray.WHITE)
                ray.end_drawing()
    finally:
        if texture is not None:
            ray.unload_texture(texture)
        ray.close_window()


if __name__ == "__main__":
    main()
