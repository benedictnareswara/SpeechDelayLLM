#!/usr/bin/env python3
"""
Verify the phrase bank is complete and internally consistent.

    python tools/verify_bank.py                    # check code invariants
    python tools/verify_bank.py --card /Volumes/BANK  # also check a mounted SD card

Checks, in order of how badly each one bites:

1.  Every phoneme the extractor can emit has an intent AND templates.
    This is the failure that produced the orphaned KUCING label: a phoneme with
    no templates silently degrades to the NOISE pool, so the child gets a
    generic prompt instead of the response their sound earned.
2.  Every phrase fits the ≤10-word therapy constraint.
3.  The manifest matches templates.py exactly (text and track numbers).
4.  With --card: every referenced file exists on the card, and no stray files
    (notably macOS `._` AppleDouble entries) are present to shift the indexes.

Exit code is non-zero if anything fails, so this works in CI. tests/test_bank.py
runs checks 1-3 as part of the normal pytest run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "speechllm-core" / "src"))

from speechllm_core.bank.manifest import BankManifest  # noqa: E402
from speechllm_core.bank.numbering import UI_FOLDER, iter_bank_entries  # noqa: E402
from speechllm_core.detection.phonemes import PHONEME_MAP  # noqa: E402
from speechllm_core.routing.intents import INTENT_REGISTRY  # noqa: E402
from speechllm_core.routing.templates import TEMPLATES  # noqa: E402

MAX_WORDS = 10


def check_phoneme_coverage() -> list[str]:
    """Every emittable phoneme needs both an intent and templates."""
    problems = []
    emittable = {phoneme for phoneme, _ in PHONEME_MAP.values()} | {"NOISE"}

    for phoneme in sorted(emittable):
        if phoneme not in INTENT_REGISTRY:
            problems.append(
                f"{phoneme}: extractor can emit it, but INTENT_REGISTRY has no entry "
                f"→ silently falls back to the NOISE intent"
            )
        if phoneme not in TEMPLATES:
            problems.append(
                f"{phoneme}: extractor can emit it, but TEMPLATES has no phrases "
                f"→ silently plays a NOISE-pool response"
            )

    for phoneme in sorted(set(INTENT_REGISTRY) - emittable):
        problems.append(
            f"{phoneme}: has an intent but the extractor can never emit it (dead entry)"
        )

    for phoneme in sorted(set(TEMPLATES) - emittable):
        problems.append(
            f"{phoneme}: has templates but the extractor can never emit it (dead entry)"
        )

    return problems


def check_phrase_lengths() -> list[str]:
    problems = []
    for phoneme, phrases in sorted(TEMPLATES.items()):
        for i, text in enumerate(phrases):
            words = len(text.split())
            if words > MAX_WORDS:
                problems.append(f"{phoneme}[{i}]: {words} words (max {MAX_WORDS}) — {text!r}")
            if not text.strip():
                problems.append(f"{phoneme}[{i}]: empty phrase")
    return problems


def check_manifest(manifest_path: Path) -> list[str]:
    if not manifest_path.exists():
        return [f"no manifest at {manifest_path} — run tools/render_bank.py"]
    try:
        return BankManifest.load(manifest_path).validate_against_templates()
    except Exception as e:  # noqa: BLE001
        return [f"could not read manifest: {e}"]


def check_card(card: Path, manifest_path: Path) -> list[str]:
    problems: list[str] = []
    if not card.exists():
        return [f"card path {card} does not exist"]

    for entry in iter_bank_entries():
        if not (card / entry.filename).exists():
            problems.append(f"missing on card: {entry.filename} ({entry.text!r})")

    if manifest_path.exists():
        manifest = BankManifest.load(manifest_path)
        for name, track in manifest.ui_tracks.items():
            path = card / f"{UI_FOLDER:02d}" / f"{track:03d}.mp3"
            if not path.exists():
                problems.append(f"missing ui sound on card: {path.name} ({name})")

    # AppleDouble and Spotlight leftovers are counted as tracks by the DFPlayer.
    junk = [p for p in card.rglob("._*")]
    junk += [p for p in card.rglob(".DS_Store")]
    junk += [p for p in card.glob(".Spotlight-V100")]
    junk += [p for p in card.glob(".Trashes")]
    if junk:
        problems.append(
            f"{len(junk)} stray macOS file(s) on the card will shift DFPlayer track indexes. Fix:\n"
            f"      dot_clean {card} && find {card} -name '._*' -delete && "
            f"find {card} -name '.DS_Store' -delete"
        )

    for path in sorted(card.rglob("*.mp3")):
        rel = path.relative_to(card)
        if not (len(rel.parts) == 2 and rel.parts[0].isdigit() and rel.stem.isdigit()):
            problems.append(f"unexpected file layout: {rel} (expected NN/NNN.mp3)")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the SpeechLLM phrase bank")
    parser.add_argument(
        "--manifest", type=Path, default=REPO_ROOT / "assets" / "bank" / "manifest.json"
    )
    parser.add_argument("--card", type=Path, default=None, help="mounted SD card to check")
    parser.add_argument("--skip-manifest", action="store_true", help="check code invariants only")
    args = parser.parse_args(argv)

    sections: list[tuple[str, list[str]]] = [
        ("phoneme coverage", check_phoneme_coverage()),
        ("phrase lengths", check_phrase_lengths()),
    ]
    if not args.skip_manifest:
        sections.append(("manifest ↔ templates", check_manifest(args.manifest)))
    if args.card is not None:
        sections.append((f"SD card {args.card}", check_card(args.card, args.manifest)))

    failed = False
    for name, problems in sections:
        if problems:
            failed = True
            print(f"✗ {name}: {len(problems)} problem(s)")
            for p in problems:
                print(f"    {p}")
        else:
            print(f"✓ {name}")

    if not failed:
        total = sum(len(v) for v in TEMPLATES.values())
        print(f"\n✅ Bank is consistent: {len(TEMPLATES)} phonemes, {total} phrases")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
