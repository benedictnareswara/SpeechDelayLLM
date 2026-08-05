"""
Silero Voice Activity Detection (VAD)

Determines whether an audio chunk contains human speech.
Runs entirely locally via ONNX Runtime (~2MB model).

Two model generations are supported, detected at load time from the ONNX
input signature:

  * v5 and later — one combined `state` tensor, shape (2, 1, 128)
  * v4 and earlier — separate LSTM `h` and `c` tensors, each (2, 1, 64)

That detection is not gold-plating. `setup_models.py` fetches the model from
GitHub, and the upstream file changed generation in place: a device staged
before the switch and one staged after end up with genuinely different
interfaces. Pinning the URL alone would not help units already in the field.
Feeding v5 the v4 inputs fails with:

    ValueError: Required inputs (['state']) are missing from input feed
                (['input', 'h', 'c', 'sr'])
"""

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

    # State tensor shapes, per model generation.
    _STATE_SHAPE = (2, 1, 128)   # v5+: combined
    _HC_SHAPE = (2, 1, 64)       # v4-: separate h and c

    def __init__(self, model_path: str | None = None):
        if model_path is None:
            model_path = str(settings.vad_model_path)

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1

        self._session = ort.InferenceSession(model_path, sess_options=opts)
        self._threshold = settings.vad_threshold
        self._sample_rate = settings.audio_sample_rate

        input_names = {i.name for i in self._session.get_inputs()}
        self._combined_state = "state" in input_names
        if not self._combined_state and "h" not in input_names:
            raise RuntimeError(
                f"Unrecognized Silero VAD model at {model_path}: expected an "
                f"input named 'state' (v5+) or 'h' (v4), got {sorted(input_names)}"
            )

        self.reset()

    @property
    def model_generation(self) -> str:
        """'v5+' or 'v4', useful in logs when a device misbehaves."""
        return "v5+" if self._combined_state else "v4"

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

        sr = np.array([self._sample_rate], dtype=np.int64)

        if self._combined_state:
            output, self._state = self._session.run(
                None, {"input": audio_float, "state": self._state, "sr": sr}
            )
        else:
            output, self._h, self._c = self._session.run(
                None, {"input": audio_float, "h": self._h, "c": self._c, "sr": sr}
            )

        confidence = float(output[0][0])
        return confidence >= self._threshold, confidence

    def reset(self):
        """Reset internal state between utterances."""
        if self._combined_state:
            self._state = np.zeros(self._STATE_SHAPE, dtype=np.float32)
        else:
            self._h = np.zeros(self._HC_SHAPE, dtype=np.float32)
            self._c = np.zeros(self._HC_SHAPE, dtype=np.float32)
