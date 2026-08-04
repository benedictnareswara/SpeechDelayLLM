"""
Speech Recognizer (faster-whisper)

Offline Indonesian speech-to-text using the faster-whisper tiny model, and the
dominant cost in the latency budget — expect 0.8–2.5 s per short utterance on
the Orange Pi Zero 3's Cortex-A53 cores. Measure it with tools/bench_device.py
before tuning anything else.

Why faster-whisper instead of Vosk:
- Vosk's Indonesian model (vosk-model-small-id) has been removed from
  alphacephei.com and is no longer available for download.
- faster-whisper tiny has usable Indonesian support out of the box.
- CTranslate2 int8 runs several times faster than reference Whisper on ARM.

Offline note: the model is fetched from HuggingFace on first use. The device
image pre-stages it and sets HF_HUB_OFFLINE=1, so a unit with no network never
blocks on a download that cannot succeed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import numpy as np
from speechllm_core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class RecognitionResult:
    """Raw output from speech recognition."""
    text: str
    confidence: float
    is_partial: bool

    @property
    def is_empty(self) -> bool:
        return not self.text or self.text.strip() == ""


class WhisperRecognizer:
    """
    Wraps faster-whisper for short-utterance Indonesian speech recognition.

    The model auto-downloads from HuggingFace to ~/.cache/huggingface/
    on first run. Subsequent runs use the cached model.

    Usage:
        recognizer = WhisperRecognizer()
        result = recognizer.transcribe(audio_chunk_float32)
    """

    # Whisper expects 30s audio at 16kHz = 480000 samples
    # For short utterances, we pad to at least 1 second
    MIN_SAMPLES = 16000  # 1 second at 16kHz

    def __init__(
        self,
        model_size: str | None = None,
        *,
        compute_type: str | None = None,
        threads: int | None = None,
        language: str | None = None,
    ):
        model_size = model_size or settings.stt_model_size
        compute_type = compute_type or settings.stt_compute_type
        threads = threads or settings.stt_threads
        self._language = language or settings.stt_language

        logger.info(
            "Loading faster-whisper '%s' (%s, %d threads)...", model_size, compute_type, threads
        )
        if os.getenv("HF_HUB_OFFLINE") == "1":
            logger.info("HF_HUB_OFFLINE=1 — using the pre-staged model only")

        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            model_size,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=threads,
        )

        logger.info("✅ Whisper '%s' ready (CPU/%s)", model_size, compute_type)

    def transcribe(self, audio_chunk: np.ndarray) -> RecognitionResult:
        """
        Transcribe a short audio chunk to Indonesian text.

        Args:
            audio_chunk: float32 numpy array at 16kHz sample rate.
                         Values should be in [-1.0, 1.0].

        Returns:
            RecognitionResult with Indonesian transcription.
        """
        # Ensure float32
        if audio_chunk.dtype != np.float32:
            audio_chunk = audio_chunk.astype(np.float32) / 32768.0

        # Pad to minimum 1 second (Whisper works poorly on very short clips)
        if len(audio_chunk) < self.MIN_SAMPLES:
            pad = np.zeros(self.MIN_SAMPLES - len(audio_chunk), dtype=np.float32)
            audio_chunk = np.concatenate([audio_chunk, pad])

        try:
            segments, info = self._model.transcribe(
                audio_chunk,
                language=self._language,
                beam_size=1,                 # fastest beam search
                best_of=1,                   # single candidate
                temperature=0.0,             # deterministic
                no_speech_threshold=0.6,     # reject non-speech
                condition_on_previous_text=False,  # no context memory
                word_timestamps=False,       # not needed here
            )

            # Collect text from all segments
            text = " ".join(seg.text.strip() for seg in segments).strip().lower()

            # Use avg_logprob from info as confidence proxy
            # info.language_probability is the language detection confidence
            confidence = float(info.language_probability) if text else 0.0

            logger.debug("Whisper: '%s' (lang_conf=%.2f)", text, confidence)
            return RecognitionResult(text=text, confidence=confidence, is_partial=False)

        except Exception as e:
            logger.error("Whisper transcription error: %s", e)
            return RecognitionResult(text="", confidence=0.0, is_partial=False)

