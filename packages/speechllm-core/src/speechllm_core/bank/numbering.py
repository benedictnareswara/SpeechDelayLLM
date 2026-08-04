"""
Phrase Bank — Deterministic Track Numbering

The DFPlayer Mini plays numbered files from its own microSD card. This module
is the single source of truth for which phrase lives at which track number, so
`tools/render_bank.py` (which writes the card) and the device runtime (which
plays from it) can never disagree.

Numbering is a pure function of `routing/templates.py`, derived from sorted
phoneme keys and the template order within each phoneme. Re-running the
renderer on an unchanged templates.py always produces identical track numbers.

Layout on the card:

    /01/001.mp3 … /01/105.mp3   therapy phrases (21 phonemes × 5 variants)
    /02/001.mp3 … /02/003.mp3   UI sounds (ready / thinking / error)

Addressing uses DFPlayer command 0x0F (play folder/file), which resolves by
*filename*. The more commonly seen 0x03 ("play the Nth file") resolves by FAT
write order instead, so a re-copied card silently plays the wrong phrase.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import IntEnum

from speechllm_core.routing.templates import TEMPLATES

# DFPlayer folders must be two-digit directories: /01, /02, …
BANK_FOLDER = 1   # therapy phrases
UI_FOLDER = 2     # chimes and error tones

# DFPlayer addresses at most 255 files per numbered folder.
MAX_TRACKS_PER_FOLDER = 255


class UiSound(IntEnum):
    """Non-speech feedback tones, in folder /02."""

    READY = 1     # played once at boot, after models finish loading
    THINKING = 2  # played the instant an utterance ends, to cover STT latency
    ERROR = 3     # played when the pipeline fails, so failure is never silent


@dataclass(frozen=True)
class BankEntry:
    """One renderable phrase and its fixed position on the SD card."""

    phoneme: str
    variant: int   # 0-based index into TEMPLATES[phoneme]
    text: str
    folder: int
    track: int

    @property
    def filename(self) -> str:
        """Path on the card, e.g. '01/007.mp3'."""
        return f"{self.folder:02d}/{self.track:03d}.mp3"


def iter_bank_entries() -> Iterator[BankEntry]:
    """Yield every phrase in the bank, in canonical track order.

    Ordering is `sorted(TEMPLATES)` then template list order. Sorting the
    phoneme keys matters: dict order would otherwise reshuffle every track
    number whenever someone reorders the TEMPLATES literal.
    """
    track = 1
    for phoneme in sorted(TEMPLATES):
        for variant, text in enumerate(TEMPLATES[phoneme]):
            if track > MAX_TRACKS_PER_FOLDER:
                raise ValueError(
                    f"Phrase bank exceeds {MAX_TRACKS_PER_FOLDER} tracks, the DFPlayer "
                    f"per-folder limit. Split across folders before adding more phrases."
                )
            yield BankEntry(
                phoneme=phoneme,
                variant=variant,
                text=text,
                folder=BANK_FOLDER,
                track=track,
            )
            track += 1


def track_for(phoneme: str, variant: int) -> int:
    """Return the track number for a (phoneme, variant) pair.

    Raises KeyError if the phoneme has no templates — which means it is
    half-wired and would otherwise degrade silently to the NOISE pool.
    """
    if phoneme not in TEMPLATES:
        raise KeyError(f"No templates for phoneme {phoneme!r}")
    variants = TEMPLATES[phoneme]
    if not 0 <= variant < len(variants):
        raise IndexError(
            f"Variant {variant} out of range for {phoneme!r} ({len(variants)} available)"
        )
    for entry in iter_bank_entries():
        if entry.phoneme == phoneme and entry.variant == variant:
            return entry.track
    raise AssertionError("unreachable: phoneme present in TEMPLATES but not enumerated")


def bank_size() -> int:
    """Total number of therapy phrases in the bank."""
    return sum(len(v) for v in TEMPLATES.values())
