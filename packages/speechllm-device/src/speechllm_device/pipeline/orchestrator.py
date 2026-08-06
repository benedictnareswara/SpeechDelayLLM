"""
Pipeline Orchestrator

The main loop. This is the wiring that did not exist before: capture → VAD →
segmenter → STT → phoneme → router → sink.

    LISTENING ──frame──► VAD ──► Segmenter
                                    │ utterance
                                    ▼
                              (thinking chime)
                                    │
                              Whisper transcribe
                                    │
                              extract_phoneme
                                    │
                              SemanticRouter.route
                                    │
       ┌── mic gated ──────────► sink.speak ──► cooldown ──► drain ──► reset
       └──────────────────────────────────────────────────────────────┘

**Mic gating.** Everything between `sink.speak()` and `capture.drain()` exists
because the speaker sits inches from the microphone. Without it the device
transcribes its own voice, routes that as if it were the child, replies to
itself, and never stops. The gate has three parts: the sink blocks until the
DFPlayer's BUSY line clears, a cooldown covers the acoustic tail, and the
capture queue is drained so buffered audio from the speaking window is
discarded rather than processed late.

The loop is deliberately synchronous: a single-threaded loop with explicit
blocking is far easier to reason about on hardware than an event loop juggling
a blocking ONNX call and a blocking serial write.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from speechllm_core.bank.numbering import UiSound
from speechllm_core.detection.phonemes import extract_phoneme
from speechllm_core.routing.router import SemanticRouter, TherapyResponse
from speechllm_core.settings import settings

from speechllm_device.output.base import AudioSink, UnspeakableResponse
from speechllm_device.pipeline.segmenter import Segmenter, Utterance

if TYPE_CHECKING:
    # Type-only. Importing these eagerly would drag onnxruntime and
    # faster-whisper into every consumer of this module — including the tests,
    # which drive the loop with fakes and need neither.
    from speechllm_device.input.capture import AudioCapture
    from speechllm_device.input.stt import WhisperRecognizer
    from speechllm_device.input.vad import SileroVAD

logger = logging.getLogger(__name__)


@dataclass
class Stats:
    """Rolling counters, logged on shutdown."""

    utterances: int = 0
    responses: int = 0
    noise_rejects: int = 0
    stt_failures: int = 0
    unspeakable: int = 0
    stt_ms: list[float] = field(default_factory=list)
    total_ms: list[float] = field(default_factory=list)

    def summary(self) -> str:
        def stat(xs: list[float]) -> str:
            if not xs:
                return "n/a"
            ordered = sorted(xs)
            p50 = ordered[len(ordered) // 2]
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            return f"p50={p50:.0f}ms p95={p95:.0f}ms max={ordered[-1]:.0f}ms"

        return (
            f"utterances={self.utterances} responses={self.responses} "
            f"noise={self.noise_rejects} stt_fail={self.stt_failures} "
            f"unspeakable={self.unspeakable}\n"
            f"  STT   {stat(self.stt_ms)}\n"
            f"  TOTAL {stat(self.total_ms)}"
        )


class Orchestrator:
    """Runs the listen → respond loop until stopped."""

    def __init__(
        self,
        capture: AudioCapture,
        vad: SileroVAD,
        recognizer: WhisperRecognizer,
        router: SemanticRouter,
        sink: AudioSink,
        segmenter: Segmenter | None = None,
        *,
        log_path: Path | None = None,
        cooldown_ms: int | None = None,
        thinking_gap_ms: int | None = None,
    ):
        self._capture = capture
        self._vad = vad
        self._stt = recognizer
        self._router = router
        self._sink = sink
        self._segmenter = segmenter or Segmenter(
            sample_rate=settings.audio_sample_rate,
            frame_size=settings.audio_block_size,
            min_speech_ms=settings.vad_min_speech_ms,
            max_speech_ms=settings.vad_max_speech_ms,
            silence_ms=settings.vad_silence_ms,
        )
        self._log_path = log_path if log_path is not None else settings.interaction_log
        self._cooldown_ms = (
            settings.speak_cooldown_ms if cooldown_ms is None else cooldown_ms
        )
        self._thinking_gap_ms = (
            settings.thinking_chime_min_gap_ms if thinking_gap_ms is None else thinking_gap_ms
        )
        # Far enough in the past that the first utterance of a session always
        # gets its chime.
        self._last_reply_end = float("-inf")
        self._running = False
        self.stats = Stats()

    # ── Main loop ────────────────────────────────────────────

    def run(self) -> None:
        """Block, processing microphone audio until stop() or KeyboardInterrupt."""
        self._running = True
        self._sink.play_ui(UiSound.READY)
        logger.info("👂 Listening")

        try:
            for frame in self._capture.frames():
                if not self._running:
                    break
                is_speech, confidence = self._vad.detect(frame)
                utterance = self._segmenter.push(frame, is_speech, confidence)
                if utterance is not None:
                    self._handle(utterance)
        except KeyboardInterrupt:
            logger.info("Interrupted")
        finally:
            self._running = False
            logger.info("Session stats:\n%s", self.stats.summary())

    def stop(self) -> None:
        self._running = False

    # ── One interaction ──────────────────────────────────────

    def _handle(self, utterance: Utterance) -> None:
        started = time.monotonic()
        self.stats.utterances += 1
        logger.info(
            "🎤 utterance %.0fms (%s, peak=%.2f)",
            utterance.duration_ms, utterance.reason.value, utterance.peak_confidence,
        )

        # Feedback that we heard them, covering the seconds of STT latency.
        #
        # Suppressed during a rapid back-and-forth: chiming after every single
        # utterance lands under a second behind the previous reply and reads as
        # interruption rather than acknowledgement. It earns its place when the
        # child has been quiet and is starting something new.
        quiet_ms = (time.monotonic() - self._last_reply_end) * 1000
        if quiet_ms >= self._thinking_gap_ms:
            self._sink.play_ui(UiSound.THINKING)
        else:
            logger.debug(
                "Thinking chime suppressed (%.0fms since last reply < %dms)",
                quiet_ms, self._thinking_gap_ms,
            )

        # ── Transcribe ───────────────────────────────────────
        stt_start = time.monotonic()
        try:
            recognition = self._stt.transcribe(utterance.audio)
        except Exception:
            logger.exception("Transcription failed")
            self.stats.stt_failures += 1
            self._sink.play_ui(UiSound.ERROR)
            self._recover()
            return
        stt_ms = (time.monotonic() - stt_start) * 1000
        self.stats.stt_ms.append(stt_ms)
        logger.info("📝 %.0fms → %r", stt_ms, recognition.text)

        # ── Route ────────────────────────────────────────────
        # Whisper's language_probability is a poor confidence proxy for babble,
        # so the VAD's acoustic confidence is used when it is the lower of the
        # two — better to route a real sound as NOISE than to act on a
        # hallucinated word.
        confidence = min(recognition.confidence, utterance.peak_confidence)
        phoneme_result = extract_phoneme(recognition.text, confidence)
        response = self._router.route(phoneme_result)

        if response.source == "fallback":
            self.stats.noise_rejects += 1

        # ── Speak (mic gated for the whole call) ─────────────
        try:
            self._sink.speak(response)
            self.stats.responses += 1
        except UnspeakableResponse as e:
            # Should be unreachable: every response now carries a bank position.
            # Kept so a stale manifest fails loudly instead of playing silence.
            logger.error("Cannot speak response: %s", e)
            self.stats.unspeakable += 1
            self._sink.play_ui(UiSound.ERROR)

        # Timed from when the reply stopped sounding, not when the utterance
        # arrived — the gap the child experiences is silence after the speaker.
        self._last_reply_end = time.monotonic()

        total_ms = (time.monotonic() - started) * 1000
        self.stats.total_ms.append(total_ms)
        logger.info("✅ %.0fms end-to-end\n", total_ms)

        self._log_interaction(utterance, recognition.text, response, stt_ms, total_ms)
        self._recover()

    def _recover(self) -> None:
        """Close the mic gate cleanly and return to a listening state."""
        if self._cooldown_ms:
            time.sleep(self._cooldown_ms / 1000.0)
        dropped = self._capture.drain()
        if dropped:
            logger.debug("Dropped %d frames captured while speaking", dropped)
        # Silero carries LSTM state between calls; without a reset it treats the
        # device's own speech as leading context for the child's next sound.
        self._vad.reset()
        self._segmenter.reset()

    # ── Logging ──────────────────────────────────────────────

    def _log_interaction(
        self,
        utterance: Utterance,
        text: str,
        response: TherapyResponse,
        stt_ms: float,
        total_ms: float,
    ) -> None:
        """Append one JSONL record for later therapy review.

        Local file only — nothing leaves the device.
        """
        if self._log_path is None:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "utterance_ms": round(utterance.duration_ms),
            "end_reason": utterance.reason.value,
            "vad_peak": round(utterance.peak_confidence, 3),
            "transcript": text,
            "phoneme": response.phoneme,
            "intent": response.intent_category,
            "technique": response.technique,
            "source": response.source,
            "response": response.text,
            "bank": (
                f"{response.bank_phoneme}[{response.bank_variant}]"
                if response.bank_phoneme is not None
                else None
            ),
            "stt_ms": round(stt_ms),
            "total_ms": round(total_ms),
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            # A full or read-only filesystem must not end the session.
            logger.warning("Could not write interaction log: %s", e)
