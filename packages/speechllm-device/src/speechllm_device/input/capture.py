"""
Audio Capture

Real-time microphone capture, yielding fixed-size int16 frames at the rate
Silero VAD requires (512 samples @ 16 kHz).

Two device realities this has to absorb:

* **USB microphones often refuse 16 kHz.** Most cheap capsules advertise only
  44.1/48 kHz. Set `AUDIO_CAPTURE_RATE=48000` and frames are captured at that
  rate and resampled down here, so everything downstream still sees clean
  16 kHz. Resampling with soxr costs well under a millisecond per frame.

* **Card ordering is not stable across boots.** `AUDIO_INPUT_DEVICE` accepts a
  substring of the device name (e.g. "USB") rather than an index, so a
  re-enumerated card doesn't silently switch the system to the wrong input.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Iterator

import numpy as np
from speechllm_core.settings import settings

logger = logging.getLogger(__name__)


class AudioDeviceError(RuntimeError):
    """No usable capture device."""


def find_input_device(name_hint: str = "") -> int | None:
    """Resolve a device-name substring to a sounddevice index.

    Returns None for the system default when no hint is given.
    """
    import sounddevice as sd

    if not name_hint:
        return None

    devices = sd.query_devices()
    matches = [
        i
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0 and name_hint.lower() in d["name"].lower()
    ]
    if not matches:
        available = [d["name"] for d in devices if d["max_input_channels"] > 0]
        raise AudioDeviceError(
            f"No input device matching {name_hint!r}. Available: {available}"
        )
    if len(matches) > 1:
        logger.warning(
            "Multiple inputs match %r, using index %d (%s)",
            name_hint, matches[0], sd.query_devices()[matches[0]]["name"],
        )
    return matches[0]


def list_input_devices() -> list[tuple[int, str, int]]:
    """(index, name, default_samplerate) for every capture device."""
    import sounddevice as sd

    return [
        (i, d["name"], int(d["default_samplerate"]))
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


class AudioCapture:
    """Blocking frame iterator over the microphone.

    Usage:
        with AudioCapture() as capture:
            for frame in capture.frames():
                ...  # frame: int16 ndarray, shape (512,) at 16 kHz
    """

    def __init__(
        self,
        sample_rate: int | None = None,
        block_size: int | None = None,
        channels: int | None = None,
        device: str | int | None = None,
        capture_rate: int | None = None,
    ):
        self._sample_rate = sample_rate or settings.audio_sample_rate
        self._block_size = block_size or settings.audio_block_size
        self._channels = channels or settings.audio_channels

        hint = settings.audio_input_device if device is None else device
        self._device = hint if isinstance(hint, int) else find_input_device(hint or "")

        rate = settings.audio_capture_rate if capture_rate is None else capture_rate
        self._capture_rate = rate or self._sample_rate
        self._needs_resample = self._capture_rate != self._sample_rate

        if self._needs_resample:
            ratio = self._capture_rate / self._sample_rate
            if not float(ratio).is_integer():
                logger.warning(
                    "Capture rate %d is not an integer multiple of %d; resampling still "
                    "works but costs more CPU.", self._capture_rate, self._sample_rate,
                )
            self._capture_block = int(round(self._block_size * ratio))
            logger.info(
                "Capturing at %d Hz → resampling to %d Hz (%d → %d samples/frame)",
                self._capture_rate, self._sample_rate, self._capture_block, self._block_size,
            )
        else:
            self._capture_block = self._block_size

        # Bounded so a stalled consumer drops old audio instead of growing without
        # limit — stale frames are worthless for a live conversation anyway.
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)
        self._stream = None
        self._running = threading.Event()
        self._overflows = 0

    # ── Lifecycle ────────────────────────────────────────────

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            logger.debug("Audio status: %s", status)
        chunk = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            self._overflows += 1
            if self._overflows % 50 == 1:
                logger.warning("Audio queue full — dropping frames (%d so far)", self._overflows)

    def start(self) -> None:
        import sounddevice as sd

        logger.info(
            "Starting capture: device=%s rate=%dHz block=%d ch=%d",
            self._device if self._device is not None else "default",
            self._capture_rate, self._capture_block, self._channels,
        )
        self._stream = sd.InputStream(
            samplerate=self._capture_rate,
            blocksize=self._capture_block,
            channels=self._channels,
            dtype=settings.audio_dtype,
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()
        self._running.set()

    def stop(self) -> None:
        self._running.clear()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("Capture stopped (%d dropped frames)", self._overflows)

    def __enter__(self) -> AudioCapture:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # ── Frames ───────────────────────────────────────────────

    def _resample(self, chunk: np.ndarray) -> np.ndarray:
        import soxr

        out = soxr.resample(
            chunk.astype(np.float32) / 32768.0, self._capture_rate, self._sample_rate
        )
        # soxr can return one sample either side of the target; pad or trim so
        # Silero always receives exactly frame_size samples.
        if out.shape[0] < self._block_size:
            out = np.pad(out, (0, self._block_size - out.shape[0]))
        elif out.shape[0] > self._block_size:
            out = out[: self._block_size]
        return np.clip(out * 32768.0, -32768, 32767).astype(np.int16)

    def frames(self, timeout: float = 1.0) -> Iterator[np.ndarray]:
        """Yield int16 frames of exactly `block_size` samples at `sample_rate`."""
        while self._running.is_set():
            try:
                chunk = self._queue.get(timeout=timeout)
            except queue.Empty:
                continue
            yield self._resample(chunk) if self._needs_resample else chunk

    def drain(self) -> int:
        """Discard queued audio.

        Called after playback: audio captured while the device was speaking is
        exactly what must never reach the VAD.
        """
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
                dropped += 1
            except queue.Empty:
                return dropped
