# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.26", "raylib>=6.0.1.0", "pillow>=10"]
# ///
"""uv run examples/rl_play.py [--no-viewer --steps 300 --output frame.png]"""
from pathlib import Path
import argparse
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rl import Action, Camera, Pinball
from rl.viewer import ViewerClock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--table", type=Path, help="Saved .vpx with embedded RL methods (default: rl/assets/rl_table.vpx)")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--camera", choices=["table", "physical"], default="table")
    parser.add_argument("--camera-anchor", choices=["center", "flipper_end"], default="flipper_end")
    parser.add_argument("--camera-height-inches", type=float, default=16)
    parser.add_argument("--camera-roll", type=float, default=90, help="Clockwise physical camera roll in degrees")
    parser.add_argument("--view-rotation", type=int, choices=[0, 90, 180, 270],
                        help="Clockwise display-only rotation; defaults to camera roll for quarter turns")
    parser.add_argument("--camera-tilt", type=float, default=45, help="Degrees down from the playfield plane")
    parser.add_argument("--camera-x-inches", type=float, default=0, help="Offset rightward from camera anchor")
    parser.add_argument("--camera-y-inches", type=float, default=0, help="Offset toward player from camera anchor (negative moves into table)")
    parser.add_argument("--ticks", type=int, default=16,
                        help="Target ms per viewer frame; exact physics ticks per step in --no-viewer/--fixed-step mode")
    parser.add_argument("--fixed-step", action="store_true",
                        help="Disable interactive wall-clock catch-up; advance exactly --ticks per frame")
    parser.add_argument("--backend", choices=["Vulkan", "OpenGL"], default="Vulkan")
    parser.add_argument("--no-viewer", action="store_true", help="Run an automatic three-button demo without a display")
    parser.add_argument("--steps", type=int, default=0, help="Stop after this many observations; 0 means unlimited")
    parser.add_argument("--output", type=Path, help="Save final RGB frame as an image")
    args = parser.parse_args()
    args.width = args.width if args.width is not None else (1344 if args.camera == "physical" else 640)
    args.height = args.height if args.height is not None else (760 if args.camera == "physical" else 480)
    if args.ticks < 1 or args.steps < 0:
        parser.error("--ticks must be positive and --steps nonnegative")

    rotation = args.view_rotation
    if rotation is None:
        roll = args.camera_roll % 360 if args.camera == "physical" else 0
        rotation = int(roll) if roll in (0, 90, 180, 270) else 0
    display_width, display_height = ((args.height, args.width) if rotation in (90, 270)
                                     else (args.width, args.height))

    def display_frame(frame):
        return np.ascontiguousarray(np.rot90(frame, k=-(rotation // 90))) if rotation else frame

    ray = None
    texture = None
    options = dict(width=args.width, height=args.height, physics_ticks=args.ticks, backend=args.backend)
    if args.engine:
        options["engine"] = args.engine
    if args.table:
        options["table"] = args.table
    if args.camera == "physical":
        options["camera"] = Camera(anchor=args.camera_anchor, height_mm=args.camera_height_inches * 25.4,
                                   tilt_degrees=args.camera_tilt, roll_degrees=args.camera_roll,
                                   x_mm=args.camera_x_inches * 25.4,
                                   y_mm=args.camera_y_inches * 25.4)
    try:
        if not args.no_viewer:
            import pyray as ray
            ray.init_window(display_width, display_height, "VPX RL - loading")
            if not ray.is_window_ready():
                raise RuntimeError("raylib could not open a desktop window; use --no-viewer on a server")
            print("Left: A/left arrow/left shift; right: D/right arrow/right shift; start/launch: space; reset: R; quit: Esc")
        with Pinball(**options) as pinball:
            print("Engine:", pinball.engine_info)
            if pinball.engine_info["gpu_vendor_id"] != 0x10DE:
                print("WARNING: renderer is not reporting an NVIDIA GPU", file=sys.stderr)
            obs = pinball.step(physics_ticks=0)
            if ray:
                # The Image borrows NumPy memory only during this GPU upload.
                # Do not unload_image: raylib does not own that CPU allocation.
                displayed = display_frame(obs.frame)
                pixels = ray.ffi.from_buffer(displayed)
                image = ray.Image(pixels, displayed.shape[1], displayed.shape[0],
                                  1, ray.PIXELFORMAT_UNCOMPRESSED_R8G8B8)
                texture = ray.load_texture_from_image(image)
                if texture.id == 0:
                    raise RuntimeError("raylib could not create the frame texture")
            steps = 0
            clock = ViewerClock(args.ticks, time.monotonic())
            stats_begin, stats_ticks = time.monotonic(), obs.ticks
            stats_frames, stats_step_seconds = 0, 0.0
            timing = ""
            while not args.steps or steps < args.steps:
                if ray:
                    if ray.window_should_close():  # Includes Escape.
                        break
                    if ray.is_key_pressed(ray.KEY_R):
                        obs = pinball.reset()
                        clock = ViewerClock(args.ticks, time.monotonic())
                        stats_begin, stats_ticks = time.monotonic(), obs.ticks
                        stats_frames, stats_step_seconds = 0, 0.0
                        timing = ""
                    action = Action(any(ray.is_key_down(key) for key in (ray.KEY_A, ray.KEY_LEFT, ray.KEY_LEFT_SHIFT)),
                                    any(ray.is_key_down(key) for key in (ray.KEY_D, ray.KEY_RIGHT, ray.KEY_RIGHT_SHIFT)),
                                    bool(ray.is_key_down(ray.KEY_SPACE)))
                else:
                    # Repeated fixed-force launches; no flippers. This is a demo, not an agent.
                    action = Action(start=(obs.ticks // 2000) % 2 == 0)
                step_begin = time.monotonic()
                count = clock.ticks_due(step_begin) if ray and not args.fixed_step else args.ticks
                obs = pinball.step(action, physics_ticks=count)
                stats_step_seconds += time.monotonic() - step_begin
                steps += 1
                stats_frames += 1
                if ray:
                    elapsed = time.monotonic() - stats_begin
                    if elapsed >= 0.5:
                        fps = stats_frames / elapsed
                        speed = (obs.ticks - stats_ticks) / (1000 * elapsed)
                        step_ms = stats_step_seconds * 1000 / stats_frames
                        timing = f"{fps:.0f} FPS | {speed:.2f}x realtime | step {step_ms:.1f} ms | "
                        stats_begin, stats_ticks = time.monotonic(), obs.ticks
                        stats_frames, stats_step_seconds = 0, 0.0
                    displayed = display_frame(obs.frame)
                    pixels = ray.ffi.from_buffer(displayed)
                    ray.update_texture(texture, ray.ffi.cast("void *", pixels))
                    ray.set_window_title(f"VPX RL | {timing}score {obs.score} | balls {obs.balls_left} | target {obs.active_target} | "
                                         + ("GAME OVER - R to reset" if obs.game_over else "space: start/launch"))
                    ray.begin_drawing()
                    ray.clear_background(ray.BLACK)
                    ray.draw_texture(texture, 0, 0, ray.WHITE)
                    ray.end_drawing()
                    # Pace only the viewer. Training still uses exact, unpaced steps.
                    time.sleep(clock.sleep_seconds(time.monotonic()))
                elif obs.game_over:
                    break
            if ray and timing:
                print("Viewer:", timing.rstrip(" |"))
            print(f"ticks={obs.ticks} score={obs.score} balls_left={obs.balls_left} game_over={obs.game_over}")
            if args.output:
                from PIL import Image
                Image.fromarray(obs.frame).save(args.output)
                print("Saved", args.output)
    finally:
        if ray and ray.is_window_ready():
            if texture is not None:
                ray.unload_texture(texture)
            ray.close_window()


if __name__ == "__main__":
    main()
