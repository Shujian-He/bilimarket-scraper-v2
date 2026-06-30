"""Interruptible delay policy for polite scraping.

This module keeps timing behavior separate from HTTP and storage code. It
provides short randomized waits before requests and longer pauses after a
configured number of pages, both with optional cancellation through
``threading.Event``.

Components:
    SleepFn, UniformFn: Callable type aliases for injectable timing helpers.
    DelayPolicy: Mutable page-delay state used by ``ScraperRunner``.
    wait_interruptibly: Shared helper that sleeps or waits on a stop event.

Example:
    ``DelayPolicy(min_seconds=0, max_seconds=0).before_request()`` returns
    ``False`` immediately, which is useful for tests.
"""

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
    """Timing policy for short request delays and periodic long pauses.

    Args:
        min_seconds: ``float`` lower bound for the randomized pre-request delay.
        max_seconds: ``float`` upper bound for the randomized pre-request delay.
        long_pause_every: ``int`` number of pages between long pauses. ``0``
            disables long pauses.
        long_pause_seconds: ``float`` duration of each long pause.
        sleep: ``Callable[[float], None]`` sleep function, injectable for tests.
        uniform: ``Callable[[float, float], float]`` random number provider.
        pages_since_pause: ``int`` internal counter, initialized to ``0``.

    Example:
        ``DelayPolicy(long_pause_every=2, long_pause_seconds=10).after_page()``
        triggers a long pause every second completed page.
    """

    min_seconds: float = 1.2
    max_seconds: float = 2.8
    long_pause_every: int = 50
    long_pause_seconds: float = 45.0
    sleep: SleepFn = time.sleep
    uniform: UniformFn = random.uniform
    pages_since_pause: int = field(default=0, init=False)

    def before_request(self, stop_event: Event | None = None) -> bool:
        """Wait for the randomized short delay before an API request.

        Args:
            stop_event: ``Event | None`` cancellation signal. When set during
                the wait, the wait ends early.

        Returns:
            bool: ``True`` when ``stop_event`` stopped the wait, otherwise
            ``False``.

        Example:
            With ``max_seconds <= 0``, ``before_request()`` returns ``False``
            without calling ``sleep``.
        """
        if self.max_seconds <= 0:
            return False
        delay = self.uniform(self.min_seconds, self.max_seconds)
        return wait_interruptibly(delay, stop_event=stop_event, sleep=self.sleep)

    def after_page(self, stop_event: Event | None = None) -> bool:
        """Maybe wait for the configured long pause after a completed page.

        Args:
            stop_event: ``Event | None`` cancellation signal. When set during
                the pause, the pause ends early.

        Returns:
            bool: ``True`` when ``stop_event`` interrupted the long pause,
            otherwise ``False``.

        Example:
            If ``long_pause_every`` is ``50``, the first 49 calls return
            ``False`` and the 50th call performs the long pause.
        """
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
    """Sleep for a duration while optionally honoring a stop event.

    Args:
        seconds: ``float`` requested wait duration in seconds.
        stop_event: ``Event | None`` cancellation signal.
        sleep: ``Callable[[float], None]`` fallback sleep function used when no
            event is supplied.

    Returns:
        bool: ``True`` when ``stop_event.wait`` returned because the event was
        set; ``False`` when the full wait elapsed or no wait was needed.

    Example:
        ``wait_interruptibly(0)`` returns ``False`` immediately.
    """
    if seconds <= 0:
        return False
    if stop_event is not None:
        return stop_event.wait(seconds)

    sleep(seconds)
    return False
