"""
Utterance Segmenter

Turns a stream of per-frame VAD decisions into complete utterances. This is the
endpointing logic that `VAD_MIN_SPEECH_MS`, `VAD_MAX_SPEECH_MS` and
`VAD_SILENCE_MS` were always meant to drive.

State machine, one transition per 512-sample (32 ms) frame:

                    speech ≥ min_speech_ms
        ┌────────┐ ─────────────────────────► ┌──────────┐
        │ SILENT │                            │ SPEAKING │
        └────────┘ ◄───────────────────────── └──────────┘
                    silence ≥ silence_ms
                    or duration ≥ max_speech_ms

Two details that matter for toddlers specifically:

* **Pre-roll.** Frames from just *before* the trigger are kept in a ring buffer
  and prepended to the utterance. VAD needs a few frames to become confident,
  and without pre-roll the initial consonant — exactly the part that
  distinguishes "ma" from "a" — is clipped off.

* **Minimum speech duration.** A short burst has to persist for min_speech_ms
  before it counts, which rejects door clicks and cutlery without rejecting the
  genuinely brief sounds these children make.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)

# Frames of audio retained before the trigger point. 6 × 32 ms ≈ 192 ms, enough
# to recover a plosive onset without dragging in much room noise.
PREROLL_FRAMES = 6


class State(Enum):
    SILENT = "silent"
    SPEAKING = "speaking"


class EndReason(str, Enum):
    SILENCE = "silence"      # normal endpoint: the child stopped
    MAX_LENGTH = "max_length"  # hit the ceiling, forced cut
    FLUSHED = "flushed"      # stream ended mid-utterance


@dataclass(frozen=True)
class Utterance:
    """A completed speech segment, ready for transcription."""

    audio: np.ndarray          # int16 mono at the VAD sample rate
    duration_ms: float
    reason: EndReason
    peak_confidence: float     # highest VAD speech probability seen
    mean_confidence: float

    @property
    def sample_count(self) -> int:
        return int(self.audio.shape[0])


@dataclass
class Segmenter:
    """Accumulates VAD frames into utterances.

    Feed every captured frame to `push()`. It returns an Utterance on the frame
    that completes one, otherwise None.
    """

    sample_rate: int = 16000
    frame_size: int = 512
    min_speech_ms: int = 150
    max_speech_ms: int = 3000
    silence_ms: int = 500

    state: State = field(default=State.SILENT, init=False)
    _buffer: list[np.ndarray] = field(default_factory=list, init=False)
    _preroll: deque[np.ndarray] = field(init=False)
    _speech_ms: float = field(default=0.0, init=False)
    _silence_ms: float = field(default=0.0, init=False)
    _confidences: list[float] = field(default_factory=list, init=False)
    _candidate: list[np.ndarray] = field(default_factory=list, init=False)
    _candidate_ms: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._preroll = deque(maxlen=PREROLL_FRAMES)

    @property
    def frame_ms(self) -> float:
        return self.frame_size / self.sample_rate * 1000.0

    @property
    def is_speaking(self) -> bool:
        return self.state is State.SPEAKING

    # ── Main entry point ─────────────────────────────────────

    def push(self, frame: np.ndarray, is_speech: bool, confidence: float) -> Utterance | None:
        """Feed one VAD-classified frame. Returns an Utterance when one ends."""
        if self.state is State.SILENT:
            return self._push_silent(frame, is_speech, confidence)
        return self._push_speaking(frame, is_speech, confidence)

    def _push_silent(
        self, frame: np.ndarray, is_speech: bool, confidence: float
    ) -> Utterance | None:
        if not is_speech:
            # Reset a partial candidate: the burst was too short to qualify.
            if self._candidate:
                self._candidate.clear()
                self._candidate_ms = 0.0
            self._preroll.append(frame)
            return None

        # Speech frame — accumulate toward the min_speech_ms trigger.
        self._candidate.append(frame)
        self._candidate_ms += self.frame_ms
        self._confidences.append(confidence)

        if self._candidate_ms < self.min_speech_ms:
            return None

        # Triggered. Promote pre-roll + candidate into the live utterance.
        logger.debug("Speech start (%.0fms, conf=%.2f)", self._candidate_ms, confidence)
        self.state = State.SPEAKING
        self._buffer = list(self._preroll) + self._candidate
        self._speech_ms = self._candidate_ms
        self._silence_ms = 0.0
        self._candidate = []
        self._candidate_ms = 0.0
        self._preroll.clear()
        return None

    def _push_speaking(
        self, frame: np.ndarray, is_speech: bool, confidence: float
    ) -> Utterance | None:
        self._buffer.append(frame)
        self._speech_ms += self.frame_ms

        if is_speech:
            self._silence_ms = 0.0
            self._confidences.append(confidence)
        else:
            self._silence_ms += self.frame_ms

        if self._silence_ms >= self.silence_ms:
            return self._finish(EndReason.SILENCE)

        if self._speech_ms >= self.max_speech_ms:
            logger.debug("Max utterance length reached, cutting at %.0fms", self._speech_ms)
            return self._finish(EndReason.MAX_LENGTH)

        return None

    # ── Completion ───────────────────────────────────────────

    def _finish(self, reason: EndReason) -> Utterance:
        audio = (
            np.concatenate(self._buffer)
            if self._buffer
            else np.zeros(0, dtype=np.int16)
        )
        confidences = self._confidences or [0.0]
        utterance = Utterance(
            audio=audio,
            duration_ms=audio.shape[0] / self.sample_rate * 1000.0,
            reason=reason,
            peak_confidence=float(max(confidences)),
            mean_confidence=float(sum(confidences) / len(confidences)),
        )
        logger.debug(
            "Utterance complete: %.0fms, reason=%s, peak=%.2f",
            utterance.duration_ms, reason.value, utterance.peak_confidence,
        )
        self.reset()
        return utterance

    def flush(self) -> Utterance | None:
        """Force-complete an in-progress utterance (stream shutdown)."""
        if self.state is State.SPEAKING and self._buffer:
            return self._finish(EndReason.FLUSHED)
        self.reset()
        return None

    def reset(self) -> None:
        """Drop all state. Call after playback, alongside SileroVAD.reset()."""
        self.state = State.SILENT
        self._buffer = []
        self._candidate = []
        self._candidate_ms = 0.0
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._confidences = []
        self._preroll.clear()
