#!/usr/bin/env python3
"""
Render the phrase bank to MP3 files for the DFPlayer's SD card.

Runs on your laptop, not the device. This is the only place a text-to-speech
service is used — the Orange Pi never synthesizes anything at runtime, which is
what lets it work with no network and no API key.

    python tools/render_bank.py                      # gTTS, free, no key
    python tools/render_bank.py --voice google-cloud # better id-ID voices
    python tools/render_bank.py --force              # re-render everything

Output (default assets/bank/):

    01/001.mp3 … 01/105.mp3   therapy phrases
    02/001.mp3 … 02/003.mp3   ready / thinking / error tones
    manifest.json             index, committed to git

Only changed phrases are re-synthesized: each file's source text is hashed and
compared against the existing manifest, so editing one template costs one API
call rather than 105.

Copying to the card — FAT32, MBR, <=32GB. Full instructions in
deploy/orangepi/SETUP.md Phase 4.

    Windows (admin PowerShell):
        diskpart  ->  clean / create partition primary / format fs=fat32
        robocopy .\\assets\\bank\\01 E:\\01 /E
        robocopy .\\assets\\bank\\02 E:\\02 /E

    macOS:
        diskutil eraseDisk FAT32 BANK MBRFormat /dev/diskN
        cp -R assets/bank/01 assets/bank/02 /Volumes/BANK/
        dot_clean /Volumes/BANK && find /Volumes/BANK -name '._*' -delete

That last step is not optional on macOS. Finder writes AppleDouble `._` files
that the DFPlayer counts as tracks, shifting every index.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "speechllm-core" / "src"))

from speechllm_core.bank.manifest import BankManifest, Track  # noqa: E402
from speechllm_core.bank.numbering import (  # noqa: E402
    BANK_FOLDER,
    UI_FOLDER,
    UiSound,
    iter_bank_entries,
)

# Short, non-verbal tones. Rendered as speech only as a fallback; prefer
# dropping real chime files in assets/ui_source/ (ready.mp3 etc.) and they will
# be used verbatim.
UI_SOUNDS: dict[UiSound, str] = {
    UiSound.READY: "Halo sayang!",
    UiSound.THINKING: "Mmm...",
    UiSound.ERROR: "Aduh, coba lagi ya!",
}


def sha_of(text: str, voice: str) -> str:
    """Hash the inputs that determine the audio, so re-renders are incremental."""
    return hashlib.sha256(f"{voice}\x00{text}".encode()).hexdigest()[:16]


# ── TTS backends ─────────────────────────────────────────────

# gTTS talks to an undocumented Google Translate endpoint that rate-limits
# bursts. Rendering 105 phrases back-to-back reliably trips it, so every
# synthesis is retried with backoff and paced with a small delay.
SYNTH_ATTEMPTS = 4
SYNTH_BACKOFF_S = 3.0
GTTS_PACING_S = 0.4


def with_retry(fn, *args, attempts: int = SYNTH_ATTEMPTS, **kwargs) -> None:
    """Call a synthesizer, retrying transient network/rate-limit failures."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            fn(*args, **kwargs)
            return
        except Exception as e:  # noqa: BLE001 - any failure is worth a retry here
            last = e
            if attempt < attempts:
                delay = SYNTH_BACKOFF_S * attempt
                print(f"    … attempt {attempt} failed ({e}); retrying in {delay:.0f}s")
                time.sleep(delay)
    raise RuntimeError(f"synthesis failed after {attempts} attempts: {last}")


def synth_gtts(text: str, dest: Path, lang: str = "id") -> None:
    from gtts import gTTS

    # slow=True gives clearer articulation, which is the point for a child
    # learning to form these sounds.
    gTTS(text=text, lang=lang, slow=True).save(str(dest))
    time.sleep(GTTS_PACING_S)


def synth_google_cloud(text: str, dest: Path, voice_name: str = "id-ID-Wavenet-A") -> None:
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code="id-ID", name=voice_name),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=0.85,   # slower than default: these are teaching prompts
            pitch=2.0,            # slightly brighter, reads as warmer to children
        ),
    )
    dest.write_bytes(response.audio_content)


SYNTHESIZERS = {
    "gtts": synth_gtts,
    "google-cloud": synth_google_cloud,
}


# ── Post-processing ──────────────────────────────────────────


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def normalize(path: Path) -> None:
    """Even out loudness so no phrase startles a toddler.

    EBU R128 at -16 LUFS, a common target for speech playback.
    """
    tmp = path.with_suffix(".norm.mp3")
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(path),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-codec:a", "libmp3lame", "-b:a", "64k", "-ar", "44100", "-ac", "1",
            str(tmp),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"    ! normalize failed ({result.stderr.strip()[:80]}), keeping raw audio")
        tmp.unlink(missing_ok=True)
        return
    tmp.replace(path)


def duration_ms(path: Path) -> int:
    """Probe duration; 0 if ffprobe is unavailable."""
    if shutil.which("ffprobe") is None:
        return 0
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return int(float(result.stdout.strip()) * 1000)
    except ValueError:
        return 0


# ── Main ─────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--voice", choices=sorted(SYNTHESIZERS), default="gtts")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "assets" / "bank")
    parser.add_argument("--force", action="store_true", help="re-render unchanged phrases too")
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, synthesize nothing")
    args = parser.parse_args(argv)

    synth = SYNTHESIZERS[args.voice]
    out_dir: Path = args.out
    manifest_path = out_dir / "manifest.json"

    # Reuse unchanged audio.
    previous: dict[tuple[str, int], Track] = {}
    if manifest_path.exists() and not args.force:
        try:
            previous = {(t.phoneme, t.variant): t for t in BankManifest.load(manifest_path).tracks}
        except Exception as e:  # noqa: BLE001
            print(f"Ignoring unreadable manifest ({e}); rendering everything.")

    entries = list(iter_bank_entries())
    print(f"Phrase bank: {len(entries)} phrases, voice={args.voice}, out={out_dir}")

    if args.dry_run:
        for e in entries[:5]:
            print(f"  {e.filename}  {e.phoneme}[{e.variant}]  {e.text!r}")
        print(f"  … and {len(entries) - 5} more")
        return 0

    if not args.no_normalize and not have_ffmpeg():
        print("! ffmpeg not found — skipping loudness normalization.")
        print("  Install it (brew install ffmpeg) or pass --no-normalize to silence this.")
        args.no_normalize = True

    (out_dir / f"{BANK_FOLDER:02d}").mkdir(parents=True, exist_ok=True)
    (out_dir / f"{UI_FOLDER:02d}").mkdir(parents=True, exist_ok=True)

    tracks: list[Track] = []
    rendered = reused = 0

    for entry in entries:
        dest = out_dir / entry.filename
        digest = sha_of(entry.text, args.voice)
        prior = previous.get((entry.phoneme, entry.variant))

        if prior and prior.sha256 == digest and dest.exists():
            tracks.append(Track(**{**prior.__dict__, "track": entry.track}))
            reused += 1
            continue

        print(
            f"  [{entry.track:3d}/{len(entries)}] "
            f"{entry.phoneme}[{entry.variant}] {entry.text!r}"
        )
        try:
            with_retry(synth, entry.text, dest)
        except Exception as e:  # noqa: BLE001
            print(f"    ! synthesis failed: {e}")
            print("      Progress is saved — re-run to resume from here.")
            return 1
        if not args.no_normalize:
            normalize(dest)
        rendered += 1

        tracks.append(
            Track(
                phoneme=entry.phoneme,
                variant=entry.variant,
                text=entry.text,
                folder=entry.folder,
                track=entry.track,
                duration_ms=duration_ms(dest),
                sha256=digest,
                voice=args.voice,
            )
        )

    # ── UI sounds ────────────────────────────────────────────
    ui_source = REPO_ROOT / "assets" / "ui_source"
    ui_tracks: dict[str, int] = {}
    for sound, fallback_text in UI_SOUNDS.items():
        dest = out_dir / f"{UI_FOLDER:02d}" / f"{int(sound):03d}.mp3"
        supplied = ui_source / f"{sound.name.lower()}.mp3"
        if supplied.exists():
            shutil.copyfile(supplied, dest)
            print(f"  ui  {sound.name.lower()} ← {supplied.name}")
        elif not dest.exists() or args.force:
            print(f"  ui  {sound.name.lower()} (synthesized: {fallback_text!r})")
            try:
                with_retry(synth, fallback_text, dest)
                if not args.no_normalize:
                    normalize(dest)
            except Exception as e:  # noqa: BLE001
                print(f"    ! ui synthesis failed: {e}")
        ui_tracks[sound.name.lower()] = int(sound)

    manifest = BankManifest(
        version=1,
        voice=args.voice,
        rendered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        tracks=tracks,
        ui_tracks=ui_tracks,
    )
    problems = manifest.validate_against_templates()
    if problems:
        print("\n! Manifest does not match templates.py:")
        for p in problems:
            print(f"    {p}")
        return 1

    manifest.dump(manifest_path)
    total_s = sum(t.duration_ms for t in tracks) / 1000
    print(
        f"\n✅ {len(tracks)} tracks ({rendered} rendered, {reused} reused), "
        f"{total_s:.0f}s of audio\n   manifest → {manifest_path}"
    )
    print("\nNext: copy assets/bank/01 and 02 to a FAT32/MBR card (SETUP.md Phase 4),")
    print("      then verify it:  python tools/verify_bank.py --card <card path>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
