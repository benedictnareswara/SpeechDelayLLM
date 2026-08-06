"""
SpeechLLM — Application Settings

Values come from environment variables, with defaults tuned for local
development on a laptop.

The device overrides these via `deploy/orangepi/device.env`, which systemd
loads into the service environment.

Access pattern mirrors the old module-level constants:

    from speechllm_core.settings import settings
    settings.vad_threshold
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repo root: packages/speechllm-core/src/speechllm_core/settings.py → up 5.
# Only correct for an editable/source checkout, so SPEECHLLM_ROOT overrides it.
# The device install sets that variable — a wheel in site-packages has no repo
# above it, and asset paths would silently resolve into /usr.
REPO_ROOT = Path(os.getenv("SPEECHLLM_ROOT") or Path(__file__).resolve().parents[4])


# systemd injects this via EnvironmentFile=, so under the service the loader
# below is a no-op. It exists for runs started by hand.
DEVICE_ENV_FILE = Path(os.getenv("SPEECHLLM_ENV_FILE", "/etc/speechllm/device.env"))


def _load_device_env() -> None:
    """Load /etc/speechllm/device.env when it wasn't already in the environment.

    Without this, a hand-started process silently takes the laptop defaults —
    null audio sink, default microphone, HF_HUB_OFFLINE unset — and *looks*
    like it is working while behaving nothing like the service. The giveaway
    is a run that logs "Audio sink: null" and plays no audio on a device whose
    device.env says AUDIO_SINK=dfplayer.

    Existing variables always win, so systemd's values and any explicit
    override on the command line are never clobbered. Parsed by hand rather
    than with python-dotenv to keep speechllm-core dependency-free.
    """
    try:
        text = DEVICE_ENV_FILE.read_text()
    except OSError:
        return  # not a device, or not readable — laptop defaults are correct
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_device_env()


def _env_str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_path(key: str, default: Path) -> Path:
    raw = os.getenv(key)
    return Path(raw).expanduser() if raw else default


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot, built once at import."""

    # ── Audio ────────────────────────────────────────────────
    # Silero VAD requires exactly 512-sample frames at 16 kHz.
    audio_sample_rate: int = field(default_factory=lambda: _env_int("AUDIO_SAMPLE_RATE", 16000))
    audio_channels: int = field(default_factory=lambda: _env_int("AUDIO_CHANNELS", 1))
    audio_block_size: int = 512
    audio_dtype: str = "int16"
    # Many USB microphones refuse 16 kHz and only offer 44.1/48 kHz. When set,
    # capture runs at this rate and resamples down to audio_sample_rate.
    audio_capture_rate: int = field(
        default_factory=lambda: _env_int("AUDIO_CAPTURE_RATE", 0)
    )
    audio_input_device: str = field(default_factory=lambda: _env_str("AUDIO_INPUT_DEVICE", ""))

    # ── Silero VAD ───────────────────────────────────────────
    vad_threshold: float = field(default_factory=lambda: _env_float("VAD_THRESHOLD", 0.5))
    vad_min_speech_ms: int = field(default_factory=lambda: _env_int("VAD_MIN_SPEECH_MS", 150))
    vad_max_speech_ms: int = field(default_factory=lambda: _env_int("VAD_MAX_SPEECH_MS", 3000))
    vad_silence_ms: int = field(default_factory=lambda: _env_int("VAD_SILENCE_MS", 500))
    vad_model_path: Path = field(
        default_factory=lambda: _env_path(
            "VAD_MODEL_PATH", REPO_ROOT / "models" / "silero_vad.onnx"
        )
    )

    # ── Speech recognition ───────────────────────────────────
    stt_model_size: str = field(default_factory=lambda: _env_str("STT_MODEL_SIZE", "tiny"))
    stt_language: str = field(default_factory=lambda: _env_str("STT_LANGUAGE", "id"))
    stt_compute_type: str = field(
        default_factory=lambda: _env_str("STT_COMPUTE_TYPE", "int8")
    )
    stt_threads: int = field(default_factory=lambda: _env_int("STT_THREADS", 4))
    # Hard ceiling on decoded tokens. Every expected utterance is one short
    # word ("ma", "susu", "makan"), so a handful of tokens is ample — and the
    # cap is what stops Whisper's repetition loop from decoding 448 tokens of
    # "mengengengen..." and turning a 3.5s transcription into a 14s one.
    stt_max_new_tokens: int = field(default_factory=lambda: _env_int("STT_MAX_NEW_TOKENS", 16))

    # ── Phoneme extraction ───────────────────────────────────
    phoneme_confidence_threshold: float = field(
        default_factory=lambda: _env_float("PHONEME_CONFIDENCE_THRESHOLD", 0.4)
    )
    phoneme_fuzzy_max_distance: int = field(
        default_factory=lambda: _env_int("PHONEME_FUZZY_MAX_DISTANCE", 1)
    )

    # ── Phrase bank ──────────────────────────────────────────
    bank_manifest: Path = field(
        default_factory=lambda: _env_path(
            "BANK_MANIFEST", REPO_ROOT / "assets" / "bank" / "manifest.json"
        )
    )

    # ── DFPlayer Mini ────────────────────────────────────────
    dfplayer_port: str = field(default_factory=lambda: _env_str("DFPLAYER_PORT", "/dev/ttyS5"))
    dfplayer_baud: int = 9600
    # 0-30
    dfplayer_volume: int = field(default_factory=lambda: _env_int("DFPLAYER_VOLUME", 22))
    # BUSY pin: PI0 on the 26-pin header, physical pin 11.
    # Allwinner BSP numbering is bank_index*32 + pin, banks A=0..I=8 → 8*32+0.
    dfplayer_busy_gpio: int = field(default_factory=lambda: _env_int("DFPLAYER_BUSY_GPIO", 256))
    dfplayer_gpiochip: str = field(
        default_factory=lambda: _env_str("DFPLAYER_GPIOCHIP", "gpiochip0")
    )

    # ── Pipeline ─────────────────────────────────────────────
    # Silence enforced after playback before the mic re-opens, so the device
    # never transcribes the tail of its own voice.
    speak_cooldown_ms: int = field(default_factory=lambda: _env_int("SPEAK_COOLDOWN_MS", 300))
    # The "thinking" chime covers STT latency so a child is not left in silence
    # for seconds. But firing it on *every* utterance turns a conversation into
    # constant chatter, and it can land under a second after the previous reply.
    # So it only plays when this much quiet has passed since the last reply
    # ended — i.e. when the child is starting something, not mid-exchange.
    #   0       always chime (the old behaviour)
    #   999999  never chime
    thinking_chime_min_gap_ms: int = field(
        default_factory=lambda: _env_int("THINKING_CHIME_MIN_GAP_MS", 5000)
    )
    # Hard ceiling on how long we wait for BUSY to clear, in case the pin is
    # miswired or the module resets mid-track.
    playback_timeout_s: float = field(
        default_factory=lambda: _env_float("PLAYBACK_TIMEOUT_S", 15.0)
    )
    # "null" | "dfplayer"
    audio_sink: str = field(default_factory=lambda: _env_str("AUDIO_SINK", "null"))
    interaction_log: Path = field(
        default_factory=lambda: _env_path(
            "INTERACTION_LOG", REPO_ROOT / "logs" / "interactions.jsonl"
        )
    )

    @property
    def frame_duration_ms(self) -> float:
        """Duration of one VAD frame in milliseconds."""
        return self.audio_block_size / self.audio_sample_rate * 1000.0


settings = Settings()
