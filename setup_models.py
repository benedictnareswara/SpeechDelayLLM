"""
Model Setup Script — SpeechLLM

Sets up the required models for the SpeechLLM system.
Uses only Python stdlib — no wget, curl, or other dependencies needed.

Models:
  1. Silero VAD ONNX (~2MB)   → downloaded here into models/
  2. Whisper (~75MB for tiny) → fetched by faster-whisper into $HF_HOME

On an offline device, run this once while it still has network, or copy the
models/ directory and the HuggingFace cache across from a laptop.

⚠️ Set HF_HOME to the same path the service uses (device.env pins
/opt/speechllm/models/hf). Staged anywhere else, the service — which runs as a
different user with HF_HUB_OFFLINE=1 and ProtectHome=true — cannot read it, and
the failure only surfaces at the first transcription.

Usage:
    HF_HOME=/opt/speechllm/models/hf python setup_models.py
"""

import os
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"

# Match the runtime. Staging "tiny" while the device is configured for "base"
# means the first transcription tries to download in offline mode and fails.
MODEL_SIZE = os.getenv("STT_MODEL_SIZE", "tiny")
COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "int8")

# Pinned to a tag, NOT master. The upstream file changed model generation in
# place — v4 exposed separate LSTM `h`/`c` inputs, v5 replaced them with one
# combined `state` tensor — so tracking master silently changes the ONNX
# interface under the device. input/vad.py handles both generations, but two
# units staged weeks apart should still get the same weights.
SILERO_REF = "v5.1"
SILERO_URL = (
    f"https://github.com/snakers4/silero-vad/raw/{SILERO_REF}/"
    "src/silero_vad/data/silero_vad.onnx"
)
SILERO_FILE = "silero_vad.onnx"


def print_step(msg: str):
    print(f"\n{'─' * 55}")
    print(f"  {msg}")
    print(f"{'─' * 55}")


def download_with_progress(url: str, dest: Path, label: str):
    print(f"  Downloading {label}...")
    print(f"  URL: {url}")

    def reporthook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(downloaded / total_size * 100, 100)
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            mb = downloaded / 1_000_000
            total_mb = total_size / 1_000_000
            print(f"\r  [{bar}] {pct:.0f}%  {mb:.1f}/{total_mb:.1f} MB", end="", flush=True)
        else:
            mb = downloaded / 1_000_000
            print(f"\r  Downloaded {mb:.1f} MB...", end="", flush=True)

    try:
        urllib.request.urlretrieve(url, dest, reporthook)
        print()
        print(f"  ✅ Saved: {dest.name} ({dest.stat().st_size / 1_000_000:.1f} MB)")
    except Exception as e:
        print(f"\n  ❌ Download failed: {e}")
        sys.exit(1)


def main():
    print("\n" + "═" * 55)
    print("  SpeechLLM — Model Setup")
    print("═" * 55)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Models directory: {MODELS_DIR}")

    # ── Step 1: Silero VAD ONNX ──────────────────────────────
    print_step("Step 1/2 — Silero VAD ONNX Model (~2MB)")
    silero_dest = MODELS_DIR / SILERO_FILE

    if silero_dest.exists():
        print(f"  ✅ Already exists, skipping: {SILERO_FILE}")
    else:
        download_with_progress(SILERO_URL, silero_dest, "Silero VAD")

    # ── Step 2: Whisper weights ──────────────────────────────
    hf_home = os.getenv("HF_HOME")
    print_step(f"Step 2/2 — Whisper '{MODEL_SIZE}' ({COMPUTE_TYPE})")
    if hf_home:
        print(f"  Cache: {hf_home}")
    else:
        print("  ⚠️ HF_HOME is not set — caching to ~/.cache/huggingface/.")
        print("     On the device this must match device.env, or the service")
        print("     will not find these weights. Re-run as:")
        print("       HF_HOME=/opt/speechllm/models/hf python setup_models.py")

    ok = True
    try:
        from faster_whisper import WhisperModel
        print(f"  Loading '{MODEL_SIZE}' (downloading if not cached)...")
        _ = WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)
        print(f"  ✅ Whisper '{MODEL_SIZE}' ready")
    except Exception as e:
        ok = False
        print(f"  ❌ Whisper model setup failed: {e}")
        print("     The device runs offline (HF_HUB_OFFLINE=1), so this will")
        print("     NOT resolve itself on first use. Fix it before Milestone 5.")

    # ── Done ─────────────────────────────────────────────────
    print("\n" + "═" * 55)
    print("  ✅ Setup complete!")
    print("═" * 55)
    print()
    print("  Models:")
    for f in sorted(MODELS_DIR.iterdir()):
        if f.is_file():
            print(f"    📄 {f.name}  ({f.stat().st_size / 1_000_000:.1f} MB)")
    print(f"    📁 Whisper '{MODEL_SIZE}' → {hf_home or '~/.cache/huggingface/'}")
    print()
    print("  Next:  python -m speechllm_device --dry-run -v")
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
