"""
Model Setup Script — SpeechLLM

Sets up the required models for the SpeechLLM system.
Uses only Python stdlib — no wget, curl, or other dependencies needed.

Models:
  1. Silero VAD ONNX (~2MB)   → downloaded here into models/
  2. Whisper tiny (~75MB)     → auto-downloaded by faster-whisper on first use
                                 cached to ~/.cache/huggingface/ (or $HF_HOME)

On an offline device, run this once while it still has network, or copy the
models/ directory and the HuggingFace cache across from a laptop.

Usage:
    python setup_models.py
"""

import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"

SILERO_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/"
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

    # ── Step 2: Whisper tiny (auto-downloaded on first use) ───
    print_step("Step 2/2 — Whisper Tiny Indonesian Model (~75MB)")
    print("  This model is managed by faster-whisper and will be")
    print("  auto-downloaded to ~/.cache/huggingface/ on first use.")
    print()
    print("  Pre-downloading now to avoid delay on first API call...")

    try:
        from faster_whisper import WhisperModel
        print("  Loading tiny model (downloading if not cached)...")
        _ = WhisperModel("tiny", device="cpu", compute_type="int8")
        print("  ✅ Whisper tiny model ready")
    except Exception as e:
        print(f"  ❌ Whisper model setup failed: {e}")
        print("     It will be downloaded automatically on first use.")

    # ── Done ─────────────────────────────────────────────────
    print("\n" + "═" * 55)
    print("  ✅ Setup complete!")
    print("═" * 55)
    print()
    print("  Models:")
    for f in sorted(MODELS_DIR.iterdir()):
        print(f"    📄 {f.name}  ({f.stat().st_size / 1_000_000:.1f} MB)")
    print("    📁 Whisper tiny → ~/.cache/huggingface/ (auto-managed)")
    print()
    print("  Next steps:")
    print("    laptop:  uvicorn speechllm_server.main:app --reload")
    print("    device:  python -m speechllm_device --dry-run -v")
    print()


if __name__ == "__main__":
    main()
