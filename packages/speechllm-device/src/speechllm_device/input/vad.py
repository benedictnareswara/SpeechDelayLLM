"""
Silero Voice Activity Detection (VAD)

Determines whether an audio chunk contains human speech.
Runs entirely locally via ONNX Runtime (~2MB model).
Designed for low-latency operation on laptop and Raspberry Pi.
"""

from pathlib import Path

import numpy as np
import onnxruntime as ort
from speechllm_core.settings import settings


class SileroVAD:
    """
    Wraps the Silero VAD ONNX model for real-time voice activity detection.

    Usage:
        vad = SileroVAD()
        is_speech, confidence = vad.detect(audio_chunk_int16)
        vad.reset()  # call between utterances
    """

    # Silero VAD expects 512-sample windows at 16kHz
    WINDOW_SIZE = 512

    def __init__(self, model_path: str | None = None):
        if model_path is None:
            model_path = str(Path(__file__).parent.parent / "models" / "silero_vad.onnx")

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1

        self._session = ort.InferenceSession(model_path, sess_options=opts)
        self._threshold = settings.vad_threshold
        self._sample_rate = settings.audio_sample_rate

        # Internal state tensors (required by Silero VAD)
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def detect(self, audio_chunk: np.ndarray) -> tuple[bool, float]:
        """
        Detect speech in an audio chunk.

        Args:
            audio_chunk: int16 numpy array of WINDOW_SIZE samples.

        Returns:
            (is_speech, confidence) where confidence is 0.0–1.0.
        """
        # Normalize int16 → float32 in [-1, 1]
        audio_float = audio_chunk.astype(np.float32) / 32768.0

        # Ensure correct shape: (1, WINDOW_SIZE)
        if audio_float.ndim == 1:
            audio_float = audio_float[np.newaxis, :]

        # Run inference
        inputs = {
            "input": audio_float,
            "h": self._h,
            "c": self._c,
            "sr": np.array([self._sample_rate], dtype=np.int64),
        }

        output, self._h, self._c = self._session.run(None, inputs)
        confidence = float(output[0][0])

        return confidence >= self._threshold, confidence

    def reset(self):
        """Reset internal state between utterances."""
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)
