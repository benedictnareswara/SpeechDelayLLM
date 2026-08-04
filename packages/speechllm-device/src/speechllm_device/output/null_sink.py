"""
Null Audio Sink

Logs what would have been spoken. Used for laptop development and for the
`--dry-run` device mode, so the whole pipeline can be exercised without a
DFPlayer attached.
"""

from __future__ import annotations

import logging
import time

from speechllm_core.bank.numbering import UiSound, track_for
from speechllm_core.routing.router import TherapyResponse

logger = logging.getLogger(__name__)


class NullSink:
    """Prints responses instead of playing them."""

    def __init__(self, *, simulate_duration: bool = False):
        # When set, sleeps a plausible speaking duration so latency measurements
        # and mic-gating behaviour resemble the real device.
        self._simulate = simulate_duration

    def speak(self, response: TherapyResponse) -> float:
        start = time.monotonic()
        track = "—"
        if response.bank_phoneme is not None and response.bank_variant is not None:
            try:
                track = f"01/{track_for(response.bank_phoneme, response.bank_variant):03d}"
            except (KeyError, IndexError):
                track = "unmapped"
        logger.info("🔊 [%s track %s] %s", response.source, track, response.text)

        if self._simulate:
            # ~150 wpm child-directed speech, floored so short phrases still register.
            words = max(len(response.text.split()), 2)
            time.sleep(max(0.8, words / 2.5))
        return time.monotonic() - start

    def play_ui(self, sound: UiSound) -> None:
        logger.info("🔔 ui: %s", sound.name.lower())

    def close(self) -> None:
        pass
