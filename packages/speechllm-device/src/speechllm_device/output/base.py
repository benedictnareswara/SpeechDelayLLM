"""
Audio Sink — Protocol

A sink turns a TherapyResponse into sound. Implementations must block until
playback finishes (or give up), because the caller keeps the microphone gated
for the entire duration of the call — that gate is what stops the device from
transcribing its own voice.
"""

from __future__ import annotations

from typing import Protocol

from speechllm_core.bank.numbering import UiSound
from speechllm_core.routing.router import TherapyResponse


class UnspeakableResponse(RuntimeError):
    """The sink has no audio for this response.

    Raised by the DFPlayer sink for runtime-generated text (Gemini), which has
    no pre-rendered track on the SD card. Callers should fall back to a
    template response rather than leaving the child with silence.
    """


class AudioSink(Protocol):
    """Plays therapy responses and UI sounds."""

    def speak(self, response: TherapyResponse) -> float:
        """Play a response, blocking until done. Returns seconds spent."""
        ...

    def play_ui(self, sound: UiSound) -> None:
        """Play a short feedback tone. Should not block on completion."""
        ...

    def close(self) -> None: ...
