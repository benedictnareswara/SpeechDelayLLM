"""
DFPlayer Audio Sink

Maps a TherapyResponse to a pre-rendered track on the DFPlayer's SD card and
plays it, blocking until the BUSY line clears.

The mapping is by `(bank_phoneme, bank_variant)` — the router reports exactly
which template variant it chose — not by matching the response text. Text
matching would break as soon as two phrases in different pools shared wording.

Responses with no bank position (Gemini-generated text) raise
UnspeakableResponse: this device has no runtime text-to-speech, and silently
playing an unrelated phrase would be worse than telling the caller to retry
with a template.
"""

from __future__ import annotations

import logging
import time

from speechllm_core.bank.manifest import BankManifest
from speechllm_core.bank.numbering import BANK_FOLDER, UI_FOLDER, UiSound
from speechllm_core.routing.router import TherapyResponse

from speechllm_device.hardware.dfplayer import DFPlayer
from speechllm_device.hardware.gpio import BusyPin
from speechllm_device.output.base import UnspeakableResponse

logger = logging.getLogger(__name__)

# The module takes a moment to pull BUSY low after the play command. Without
# this grace period, is_busy() reads "idle" immediately and we would treat a
# track that is about to start as already finished.
BUSY_ASSERT_TIMEOUT_S = 0.6
BUSY_POLL_INTERVAL_S = 0.02


class DFPlayerSink:
    """Plays pre-rendered phrases through a DFPlayer Mini."""

    def __init__(
        self,
        player: DFPlayer,
        manifest: BankManifest,
        busy_pin: BusyPin,
        *,
        playback_timeout_s: float = 15.0,
    ):
        self._player = player
        self._manifest = manifest
        self._busy = busy_pin
        self._timeout = playback_timeout_s

    # ── Playback ─────────────────────────────────────────────

    def speak(self, response: TherapyResponse) -> float:
        if response.bank_phoneme is None or response.bank_variant is None:
            raise UnspeakableResponse(
                f"Response from {response.source!r} has no pre-rendered track: {response.text!r}"
            )

        try:
            track = self._manifest.track_number(response.bank_phoneme, response.bank_variant)
        except KeyError as e:
            raise UnspeakableResponse(str(e)) from e

        start = time.monotonic()
        logger.info(
            "🔊 %02d/%03d  [%s] %s",
            BANK_FOLDER, track, response.phoneme, response.text,
        )
        self._player.play(BANK_FOLDER, track)
        self._wait_for_playback(expected_ms=self._expected_duration_ms(response))
        return time.monotonic() - start

    def play_ui(self, sound: UiSound) -> None:
        track = self._manifest.ui_tracks.get(sound.name.lower(), int(sound))
        logger.debug("🔔 ui %s → %02d/%03d", sound.name.lower(), UI_FOLDER, track)
        self._player.play(UI_FOLDER, track)
        # Deliberately not waited on: the thinking chime must overlap with
        # transcription, which is the whole point of playing it.

    def close(self) -> None:
        self._player.close()
        self._busy.close()

    # ── BUSY handling ────────────────────────────────────────

    def _expected_duration_ms(self, response: TherapyResponse) -> int | None:
        if response.bank_phoneme is None or response.bank_variant is None:
            return None
        for t in self._manifest.tracks:
            if t.phoneme == response.bank_phoneme and t.variant == response.bank_variant:
                return t.duration_ms
        return None

    def _wait_for_playback(self, expected_ms: int | None) -> None:
        """Block until BUSY clears, or fall back to the manifest duration."""
        # 1. Wait for BUSY to assert, confirming the track actually started.
        deadline = time.monotonic() + BUSY_ASSERT_TIMEOUT_S
        started = False
        while time.monotonic() < deadline:
            if self._busy.is_busy():
                started = True
                break
            time.sleep(BUSY_POLL_INTERVAL_S)

        if not started:
            # Either the pin is mocked/miswired, or the track is missing from
            # the card. Sleep the known duration so the mic stays gated either
            # way — a wrong gate is worse than a slightly long one.
            fallback_s = (expected_ms or 2000) / 1000.0
            logger.debug("BUSY never asserted; sleeping %.2fs from manifest", fallback_s)
            time.sleep(fallback_s)
            return

        # 2. Wait for it to clear.
        deadline = time.monotonic() + self._timeout
        while self._busy.is_busy():
            if time.monotonic() > deadline:
                logger.warning(
                    "BUSY still asserted after %.0fs — module may have hung; continuing",
                    self._timeout,
                )
                return
            time.sleep(BUSY_POLL_INTERVAL_S)
