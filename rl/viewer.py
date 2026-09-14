"""Wall-clock pacing for human play; never used by Pinball.step or training."""


class ViewerClock:
    def __init__(self, ticks_per_frame: int, now: float):
        self.period = ticks_per_frame / 1000
        self.previous = now
        self.deadline = now
        self.pending_ms = float(ticks_per_frame)  # Advance the first frame normally.
        self.max_catchup_ms = max(250, ticks_per_frame)

    def ticks_due(self, now: float) -> int:
        elapsed_ms = max(0.0, now - self.previous) * 1000
        self.previous = now
        # Carry sub-ms fractions rather than rounding every frame. A debugger or
        # long OS stall should not make a human player skip several seconds.
        self.pending_ms = min(self.pending_ms + elapsed_ms, self.max_catchup_ms)
        ticks = int(self.pending_ms + 1e-9)
        self.pending_ms = max(0.0, self.pending_ms - ticks)
        return ticks

    def sleep_seconds(self, now: float) -> float:
        # Absolute deadlines avoid accumulating sleep overshoot on every frame.
        self.deadline += self.period
        if self.deadline < now:
            self.deadline = now
        return max(0.0, self.deadline - now)
