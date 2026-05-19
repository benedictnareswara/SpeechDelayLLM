"""
Audio Capture Module

Provides a real-time microphone audio stream for the processing pipeline.
Uses sounddevice for cross-platform compatibility (macOS, Linux/RPi).
"""

import asyncio
import logging
import queue
from typing import AsyncGenerator

import numpy as np
import sounddevice as sd

import config

logger = logging.getLogger(__name__)


class AudioCapture:
    """
    Real-time microphone audio capture with async generator interface.

    Usage:
        capture = AudioCapture()
        async for chunk in capture.stream():
            # chunk is np.ndarray of int16, shape (BLOCK_SIZE,)
            process(chunk)
    """

    def __init__(
        self,
        sample_rate: int = config.AUDIO_SAMPLE_RATE,
        block_size: int = config.AUDIO_BLOCK_SIZE,
        channels: int = config.AUDIO_CHANNELS,
    ):
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._channels = channels
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._running = False

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice for each audio block."""
        if status:
            logger.warning("Audio status: %s", status)
        # Copy to avoid buffer reuse issues
        self._queue.put(indata[:, 0].copy() if self._channels == 1 else indata.copy())

    async def stream(self) -> AsyncGenerator[np.ndarray, None]:
        """
        Async generator yielding audio chunks from the microphone.

        Yields:
            np.ndarray of int16 samples, shape (block_size,).
        """
        self._running = True
        logger.info(
            "Starting audio capture: rate=%dHz, block=%d samples, dtype=%s",
            self._sample_rate, self._block_size, config.AUDIO_DTYPE,
        )

        stream = sd.InputStream(
            samplerate=self._sample_rate,
            blocksize=self._block_size,
            channels=self._channels,
            dtype=config.AUDIO_DTYPE,
            callback=self._audio_callback,
        )

        with stream:
            while self._running:
                try:
                    # Non-blocking check with small sleep for async cooperation
                    chunk = self._queue.get_nowait()
                    yield chunk
                except queue.Empty:
                    await asyncio.sleep(0.01)  # 10ms poll interval

    def stop(self):
        """Stop the audio capture stream."""
        self._running = False
        logger.info("Audio capture stopped")
