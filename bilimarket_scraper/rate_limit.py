"""Interruptible delay policy for polite scraping."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event

SleepFn = Callable[[float], None]
UniformFn = Callable[[float, float], float]


@dataclass
class DelayPolicy:
    min_seconds: float = 1.2
    max_seconds: float = 2.8
    long_pause_every: int = 50
    long_pause_seconds: float = 45.0
    sleep: SleepFn = time.sleep
    uniform: UniformFn = random.uniform
    pages_since_pause: int = field(default=0, init=False)

    def before_request(self, stop_event: Event | None = None) -> bool:
        if self.max_seconds <= 0:
            return False
        delay = self.uniform(self.min_seconds, self.max_seconds)
        return wait_interruptibly(delay, stop_event=stop_event, sleep=self.sleep)

    def after_page(self, stop_event: Event | None = None) -> bool:
        if self.long_pause_every <= 0 or self.long_pause_seconds <= 0:
            return False

        self.pages_since_pause += 1
        if self.pages_since_pause < self.long_pause_every:
            return False

        self.pages_since_pause = 0
        return wait_interruptibly(
            self.long_pause_seconds,
            stop_event=stop_event,
            sleep=self.sleep,
        )


def wait_interruptibly(
    seconds: float,
    *,
    stop_event: Event | None = None,
    sleep: SleepFn = time.sleep,
) -> bool:
    if seconds <= 0:
        return False
    if stop_event is not None:
        return stop_event.wait(seconds)

    sleep(seconds)
    return False
