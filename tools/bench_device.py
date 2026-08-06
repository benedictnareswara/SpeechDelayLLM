#!/usr/bin/env python3
"""
Benchmark the pipeline on real hardware. This is Milestone 0.

Run this on the Orange Pi BEFORE building anything else. Whisper dominates the
latency budget, and every later tuning decision (endpoint timing, whether the
thinking chime is needed, whether whisper.cpp is worth the work) depends on the
number this produces.

    python tools/bench_device.py                    # synthetic audio
    python tools/bench_device.py --wav-dir samples/ # real recordings (better)
    python tools/bench_device.py --record 10        # record 10 clips first

Reports per-stage p50/p95, plus RAM headroom. Judge the result against the
budget in the plan: under ~2 s total is comfortable, 2–3 s is workable with the
thinking chime, over 3 s means reach for whisper.cpp.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import wave
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "speechllm-core" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "speechllm-device" / "src"))

SAMPLE_RATE = 16000


def synthetic_clips(count: int, duration_s: float = 1.2) -> list[np.ndarray]:
    """Vowel-ish tones. A stand-in only — formants are not real speech, so
    Whisper will usually return nothing. Use --wav-dir for a real number."""
    rng = np.random.default_rng(0)
    clips = []
    for i in range(count):
        n = int(SAMPLE_RATE * duration_s)
        t = np.linspace(0, duration_s, n, endpoint=False)
        f0 = 180 + (i % 5) * 30
        wave_f = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3))
        wave_f += rng.normal(0, 0.02, n)
        envelope = np.minimum(1.0, np.minimum(t * 20, (duration_s - t) * 20))
        clips.append((wave_f * envelope * 8000).astype(np.int16))
    return clips


def load_wavs(directory: Path) -> list[np.ndarray]:
    clips = []
    for path in sorted(directory.glob("*.wav")):
        with wave.open(str(path), "rb") as wf:
            if wf.getframerate() != SAMPLE_RATE:
                print(f"  ! {path.name}: {wf.getframerate()} Hz, expected {SAMPLE_RATE} — skipped")
                continue
            data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
            if wf.getnchannels() > 1:
                data = data[:: wf.getnchannels()]
            clips.append(data)
    return clips


def record_clips(count: int, out_dir: Path, duration_s: float = 2.0) -> None:
    import sounddevice as sd

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Recording {count} clips of {duration_s}s into {out_dir}")
    for i in range(count):
        input(f"  [{i + 1}/{count}] press Enter, then make a sound...")
        audio = sd.rec(int(SAMPLE_RATE * duration_s), samplerate=SAMPLE_RATE,
                       channels=1, dtype="int16")
        sd.wait()
        path = out_dir / f"clip_{i:02d}.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        print(f"      saved {path.name}")


def report(name: str, timings: list[float], budget_ms: float | None = None) -> None:
    if not timings:
        print(f"  {name:<22} no data")
        return
    ordered = sorted(timings)
    p50 = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    verdict = ""
    if budget_ms is not None:
        verdict = "  ✅" if p95 <= budget_ms else f"  ⚠️  over {budget_ms:.0f}ms budget"
    print(f"  {name:<22} p50={p50:7.1f}ms  p95={p95:7.1f}ms  max={ordered[-1]:7.1f}ms{verdict}")


def memory_mb() -> float | None:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KB, macOS reports bytes.
        return usage / 1024 if sys.platform.startswith("linux") else usage / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark the SpeechLLM pipeline")
    parser.add_argument("--wav-dir", type=Path, default=None)
    parser.add_argument("--record", type=int, default=0, metavar="N")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=2)
    args = parser.parse_args(argv)

    if args.record:
        record_clips(args.record, args.wav_dir or REPO_ROOT / "samples")
        return 0

    if args.wav_dir:
        clips = load_wavs(args.wav_dir)
        if not clips:
            print(f"No usable 16 kHz WAVs in {args.wav_dir}")
            return 1
        print(f"Loaded {len(clips)} recorded clips from {args.wav_dir}")
    else:
        clips = synthetic_clips(args.count)
        print(f"Using {len(clips)} synthetic clips.")
        print("  Note: synthetic tones are not speech; Whisper will mostly return empty")
        print("  text. Timings are still representative — use --wav-dir for realism.\n")

    import platform

    print(f"Platform: {platform.machine()} · Python {platform.python_version()}")
    print(f"CPU count: {__import__('os').cpu_count()}\n")

    from speechllm_core.detection.phonemes import extract_phoneme
    from speechllm_core.routing.templates import pick_template_variant
    from speechllm_core.settings import settings

    # ── Load ─────────────────────────────────────────────────
    from speechllm_device.input.vad import SileroVAD

    t0 = time.monotonic()
    vad = SileroVAD(str(settings.vad_model_path))
    vad_load = (time.monotonic() - t0) * 1000

    from speechllm_device.input.stt import WhisperRecognizer

    t0 = time.monotonic()
    recognizer = WhisperRecognizer()
    stt_load = (time.monotonic() - t0) * 1000
    print(f"Model load: VAD {vad_load:.0f}ms, Whisper {stt_load:.0f}ms\n")

    # ── Warm up ──────────────────────────────────────────────
    for clip in clips[: args.warmup]:
        recognizer.transcribe(clip)

    # ── Measure ──────────────────────────────────────────────
    vad_ms: list[float] = []
    stt_ms: list[float] = []
    route_ms: list[float] = []
    total_ms: list[float] = []
    transcripts: list[str] = []

    block = settings.audio_block_size
    for clip in clips:
        started = time.monotonic()

        t0 = time.monotonic()
        for i in range(0, len(clip) - block, block):
            vad.detect(clip[i : i + block])
        frames = max(1, (len(clip) - block) // block)
        vad_ms.append((time.monotonic() - t0) * 1000 / frames)
        vad.reset()

        t0 = time.monotonic()
        result = recognizer.transcribe(clip)
        stt_ms.append((time.monotonic() - t0) * 1000)
        transcripts.append(result.text)

        t0 = time.monotonic()
        phoneme = extract_phoneme(result.text, result.confidence)
        pick_template_variant(phoneme.phoneme)
        route_ms.append((time.monotonic() - t0) * 1000)

        total_ms.append((time.monotonic() - started) * 1000)

    print(f"Results over {len(clips)} clips:")
    report("VAD (per frame)", vad_ms, budget_ms=10)
    report("Whisper transcribe", stt_ms, budget_ms=2500)
    report("phoneme + route", route_ms, budget_ms=5)
    report("pipeline total", total_ms)

    endpoint = settings.vad_silence_ms
    p95_total = sorted(total_ms)[min(len(total_ms) - 1, int(len(total_ms) * 0.95))]
    perceived = p95_total + endpoint
    print(f"\nPerceived latency (p95 + {endpoint}ms endpoint wait): {perceived:.0f}ms")
    if perceived < 2000:
        print("  ✅ Comfortable for a toddler.")
    elif perceived < 3000:
        print("  ⚠️  Workable, but keep the thinking chime and consider VAD_SILENCE_MS=350.")
    else:
        print("  ❌ Too slow.")
        print("     Note: shortening VAD_MAX_SPEECH_MS will NOT help. Whisper pads")
        print("     every clip to a 30s window, so a 0.4s 'ma' costs the same as a")
        print("     25s sentence — which is why p50/p95/max above are nearly equal.")
        print("     Check the CPU governor first (cheap):")
        print("       cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        print("     Then consider whisper.cpp tiny, or a keyword spotter — this")
        print("     vocabulary is 21 short labels, not open-ended speech.")

    rss = memory_mb()
    if rss:
        print(f"\nPeak RSS: {rss:.0f} MB")

    non_empty = [t for t in transcripts if t.strip()]
    print(f"Non-empty transcripts: {len(non_empty)}/{len(transcripts)}")
    for t in non_empty[:5]:
        print(f"    {t!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
