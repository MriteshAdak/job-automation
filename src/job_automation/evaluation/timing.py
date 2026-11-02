"""High-resolution monotonic execution timing utilities (EVAL-01-S04).

Enforces:
- Monotonic wall-clock timing using time.perf_counter().
- Preservation of stage-level latencies (extraction, retrieval, packing, inference, total).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator


class StageTimer:
    """Tracks elapsed wall-clock milliseconds across pipeline stages."""

    def __init__(self) -> None:
        self.timings_ms: dict[str, float] = {}

    @contextmanager
    def time_stage(self, stage_name: str) -> Generator[None, None, None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start) * 1000.0
            self.timings_ms[stage_name] = round(elapsed, 2)

