"""
SpeechLLM Device — Entry Point

    python -m speechllm_device                 # normal run (systemd uses this)
    python -m speechllm_device --dry-run       # no DFPlayer; log responses only
    python -m speechllm_device --list-devices  # show input devices and exit

Startup order matters. Models load before the DFPlayer is opened so a missing
ONNX file fails fast, and the phrase bank is validated against templates.py
before the first sound plays — a stale SD card means the child hears the wrong
response to their sound, which is worse than refusing to start.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from types import FrameType

from speechllm_core.bank.manifest import BankManifest, BankMismatchError
from speechllm_core.routing.router import SemanticRouter
from speechllm_core.settings import settings

logger = logging.getLogger("speechllm")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s │ %(name)-28s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # These are noisy at DEBUG and drown out the pipeline's own logs.
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)


def _build_sink(dry_run: bool, manifest: BankManifest):
    from speechllm_device.output.null_sink import NullSink

    if dry_run or settings.audio_sink == "null":
        logger.info("Audio sink: null (dry run — nothing will be played)")
        return NullSink(simulate_duration=True)

    from speechllm_device.hardware.dfplayer import DFPlayer
    from speechllm_device.hardware.gpio import open_busy_pin
    from speechllm_device.output.dfplayer_sink import DFPlayerSink

    player = DFPlayer(settings.dfplayer_port, settings.dfplayer_baud)
    player.open()
    player.set_volume(settings.dfplayer_volume)

    busy = open_busy_pin(settings.dfplayer_gpiochip, settings.dfplayer_busy_gpio)
    logger.info(
        "Audio sink: DFPlayer on %s, volume %d/30", settings.dfplayer_port, settings.dfplayer_volume
    )
    return DFPlayerSink(player, manifest, busy, playback_timeout_s=settings.playback_timeout_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speechllm-device")
    parser.add_argument("--dry-run", action="store_true", help="log responses instead of playing")
    parser.add_argument("--list-devices", action="store_true", help="list audio inputs and exit")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    if args.list_devices:
        from speechllm_device.input.capture import list_input_devices

        print(f"{'idx':>4}  {'default Hz':>10}  name")
        for index, name, rate in list_input_devices():
            print(f"{index:>4}  {rate:>10}  {name}")
        return 0

    logger.info("═" * 62)
    logger.info("  SpeechLLM Device — Terapi Wicara")
    logger.info("═" * 62)

    # ── Phrase bank ──────────────────────────────────────────
    try:
        manifest = BankManifest.load(settings.bank_manifest)
        manifest.require_valid()
        logger.info(
            "✅ Phrase bank: %d tracks, voice=%s, rendered %s",
            len(manifest.tracks), manifest.voice, manifest.rendered_at or "unknown",
        )
    except FileNotFoundError:
        logger.error(
            "No phrase bank at %s. Run: python tools/render_bank.py", settings.bank_manifest
        )
        return 2
    except BankMismatchError as e:
        logger.error("%s", e)
        return 2

    # ── Models ───────────────────────────────────────────────
    from speechllm_device.input.stt import WhisperRecognizer
    from speechllm_device.input.vad import SileroVAD

    warm_start = time.monotonic()
    try:
        vad = SileroVAD(str(settings.vad_model_path))
        logger.info("✅ Silero VAD loaded")
    except Exception as e:  # noqa: BLE001
        logger.error("Could not load Silero VAD from %s: %s", settings.vad_model_path, e)
        logger.error("Run: python setup_models.py")
        return 2

    recognizer = WhisperRecognizer()
    logger.info("✅ Models warm in %.1fs", time.monotonic() - warm_start)

    # ── Audio out ────────────────────────────────────────────
    try:
        sink = _build_sink(args.dry_run, manifest)
    except Exception as e:  # noqa: BLE001
        logger.error("Could not open the audio sink: %s", e)
        logger.error("Check the DFPlayer wiring, that %s exists, and that you are "
                     "in the 'dialout' group.", settings.dfplayer_port)
        return 2

    # ── Capture + run ────────────────────────────────────────
    from speechllm_device.input.capture import AudioCapture, AudioDeviceError
    from speechllm_device.pipeline.orchestrator import Orchestrator

    router = SemanticRouter(gemini_client=None)  # offline: templates only

    try:
        capture = AudioCapture()
    except AudioDeviceError as e:
        logger.error("%s", e)
        logger.error("Run with --list-devices, then set AUDIO_INPUT_DEVICE.")
        sink.close()
        return 2

    orchestrator = Orchestrator(capture, vad, recognizer, router, sink)

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info("Signal %d — shutting down", signum)
        orchestrator.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        with capture:
            orchestrator.run()
    finally:
        sink.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
