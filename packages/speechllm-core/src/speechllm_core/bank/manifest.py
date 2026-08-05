"""
Phrase Bank — Manifest

`assets/bank/manifest.json` is the index of what was actually burned to the
DFPlayer's SD card. It is committed to git so the device knows the contents of
a card it cannot read back.

The device loads this at boot and refuses to start if it disagrees with
`routing/templates.py` — a mismatch means the card is stale and the child would
hear the wrong phrase for their sound.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from speechllm_core.bank.numbering import BankEntry, iter_bank_entries

MANIFEST_VERSION = 1


@dataclass(frozen=True)
class Track:
    """One rendered audio file on the SD card."""

    phoneme: str
    variant: int
    text: str
    folder: int
    track: int
    duration_ms: int
    sha256: str
    voice: str

    @property
    def filename(self) -> str:
        return f"{self.folder:02d}/{self.track:03d}.mp3"


class BankMismatchError(RuntimeError):
    """Raised when the manifest disagrees with the current templates."""


@dataclass(frozen=True)
class BankManifest:
    """Parsed manifest.json."""

    version: int
    voice: str
    rendered_at: str
    tracks: list[Track]
    ui_tracks: dict[str, int]

    # ── Loading ──────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> BankManifest:
        raw = json.loads(Path(path).read_text())
        if raw.get("version") != MANIFEST_VERSION:
            raise BankMismatchError(
                f"Manifest version {raw.get('version')} != expected {MANIFEST_VERSION}. "
                f"Re-run tools/render_bank.py."
            )
        return cls(
            version=raw["version"],
            voice=raw.get("voice", "unknown"),
            rendered_at=raw.get("rendered_at", ""),
            tracks=[Track(**t) for t in raw["tracks"]],
            ui_tracks=raw.get("ui_tracks", {}),
        )

    def dump(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "voice": self.voice,
            "rendered_at": self.rendered_at,
            "ui_tracks": self.ui_tracks,
            "tracks": [asdict(t) for t in self.tracks],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    # ── Lookup ───────────────────────────────────────────────

    def track_number(self, phoneme: str, variant: int) -> int:
        for t in self.tracks:
            if t.phoneme == phoneme and t.variant == variant:
                return t.track
        raise KeyError(f"No track for phoneme={phoneme!r} variant={variant}")

    # ── Validation ───────────────────────────────────────────

    def validate_against_templates(self) -> list[str]:
        """Compare the manifest to the live TEMPLATES table.

        Returns a list of human-readable problems; empty means the SD card
        matches the code. Called at device boot and by tools/verify_bank.py.
        """
        problems: list[str] = []
        expected: dict[tuple[str, int], BankEntry] = {
            (e.phoneme, e.variant): e for e in iter_bank_entries()
        }
        actual: dict[tuple[str, int], Track] = {(t.phoneme, t.variant): t for t in self.tracks}

        for key, entry in expected.items():
            got = actual.get(key)
            if got is None:
                problems.append(
                    f"missing from card: {entry.phoneme}[{entry.variant}] {entry.text!r}"
                )
                continue
            if got.text != entry.text:
                problems.append(
                    f"text drift at {entry.phoneme}[{entry.variant}] track {got.track}: "
                    f"card says {got.text!r}, templates say {entry.text!r}"
                )
            if got.track != entry.track:
                problems.append(
                    f"track number drift at {entry.phoneme}[{entry.variant}]: "
                    f"card says {got.track}, numbering says {entry.track}"
                )

        for key in actual.keys() - expected.keys():
            problems.append(f"orphan on card (no template): {key[0]}[{key[1]}]")

        return problems

    def require_valid(self) -> None:
        """Raise if the card and the code disagree."""
        problems = self.validate_against_templates()
        if problems:
            raise BankMismatchError(
                "Phrase bank does not match routing/templates.py:\n  "
                + "\n  ".join(problems)
                + "\n\nRe-run: python tools/render_bank.py"
            )
