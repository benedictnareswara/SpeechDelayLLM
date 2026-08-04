"""
Tests for the phrase bank — numbering, coverage, and manifest consistency.

The coverage tests here are the guard against the failure mode that produced the
orphaned KUCING label: a phoneme the extractor can emit but that has no intent
or no templates degrades silently to the NOISE pool, so a child gets a generic
prompt instead of a response to the sound they actually made.
"""

import pytest
from speechllm_core.bank.manifest import BankManifest, BankMismatchError, Track
from speechllm_core.bank.numbering import (
    MAX_TRACKS_PER_FOLDER,
    UiSound,
    bank_size,
    iter_bank_entries,
    track_for,
)
from speechllm_core.detection.phonemes import PHONEME_MAP
from speechllm_core.routing.intents import INTENT_REGISTRY
from speechllm_core.routing.templates import TEMPLATES


def emittable_phonemes() -> set[str]:
    """Every phoneme label extract_phoneme() can produce."""
    return {phoneme for phoneme, _ in PHONEME_MAP.values()} | {"NOISE"}


class TestCoverage:
    """The three-table invariant: PHONEME_MAP ↔ INTENT_REGISTRY ↔ TEMPLATES."""

    def test_every_emittable_phoneme_has_an_intent(self):
        missing = sorted(emittable_phonemes() - set(INTENT_REGISTRY))
        assert not missing, (
            f"Phonemes the extractor emits with no INTENT_REGISTRY entry: {missing}. "
            f"They fall back to the NOISE intent silently."
        )

    def test_every_emittable_phoneme_has_templates(self):
        missing = sorted(emittable_phonemes() - set(TEMPLATES))
        assert not missing, (
            f"Phonemes the extractor emits with no TEMPLATES entry: {missing}. "
            f"They play a NOISE-pool phrase silently."
        )

    def test_no_dead_intents(self):
        dead = sorted(set(INTENT_REGISTRY) - emittable_phonemes())
        assert not dead, f"Intents for phonemes that can never be emitted: {dead}"

    def test_no_dead_templates(self):
        dead = sorted(set(TEMPLATES) - emittable_phonemes())
        assert not dead, f"Templates for phonemes that can never be emitted: {dead}"

    def test_phoneme_map_entries_are_well_formed(self):
        # An earlier version stored bare strings here and normalized them in a
        # loop afterwards, which is how an unmapped label slipped through.
        for key, value in PHONEME_MAP.items():
            assert isinstance(value, tuple) and len(value) == 2, (
                f"PHONEME_MAP[{key!r}] = {value!r}, expected a (phoneme, category) tuple"
            )


class TestNumbering:
    def test_numbering_is_deterministic(self):
        first = [(e.phoneme, e.variant, e.track) for e in iter_bank_entries()]
        second = [(e.phoneme, e.variant, e.track) for e in iter_bank_entries()]
        assert first == second

    def test_tracks_are_contiguous_from_one(self):
        tracks = [e.track for e in iter_bank_entries()]
        assert tracks == list(range(1, len(tracks) + 1))

    def test_entry_count_matches_template_count(self):
        assert len(list(iter_bank_entries())) == bank_size()

    def test_fits_dfplayer_folder_limit(self):
        assert bank_size() <= MAX_TRACKS_PER_FOLDER

    def test_filenames_are_dfplayer_shaped(self):
        for entry in iter_bank_entries():
            assert entry.filename.startswith("01/")
            assert entry.filename.endswith(".mp3")
            assert len(entry.filename) == len("01/001.mp3")

    def test_track_for_round_trips(self):
        for entry in list(iter_bank_entries())[::7]:
            assert track_for(entry.phoneme, entry.variant) == entry.track

    def test_track_for_rejects_unknown_phoneme(self):
        with pytest.raises(KeyError):
            track_for("KUCING", 0)

    def test_track_for_rejects_out_of_range_variant(self):
        with pytest.raises(IndexError):
            track_for("MA", 999)

    def test_ui_sounds_do_not_collide(self):
        values = [int(s) for s in UiSound]
        assert len(values) == len(set(values))


class TestManifest:
    def _manifest_from_templates(self, **overrides) -> BankManifest:
        tracks = [
            Track(
                phoneme=e.phoneme,
                variant=e.variant,
                text=overrides.get("text_for", lambda t: t)(e.text),
                folder=e.folder,
                track=e.track,
                duration_ms=1500,
                sha256="deadbeef",
                voice="test",
            )
            for e in iter_bank_entries()
        ]
        return BankManifest(
            version=1, voice="test", rendered_at="2026-01-01T00:00:00+00:00",
            tracks=tracks, ui_tracks={"ready": 1, "thinking": 2, "error": 3},
        )

    def test_matching_manifest_validates(self):
        assert self._manifest_from_templates().validate_against_templates() == []

    def test_text_drift_is_detected(self):
        manifest = self._manifest_from_templates(text_for=lambda t: t.replace("Ayah", "Bapak"))
        problems = manifest.validate_against_templates()
        assert problems
        assert any("text drift" in p for p in problems)

    def test_missing_track_is_detected(self):
        manifest = self._manifest_from_templates()
        trimmed = BankManifest(
            version=manifest.version, voice=manifest.voice, rendered_at=manifest.rendered_at,
            tracks=manifest.tracks[:-1], ui_tracks=manifest.ui_tracks,
        )
        assert any("missing from card" in p for p in trimmed.validate_against_templates())

    def test_orphan_track_is_detected(self):
        manifest = self._manifest_from_templates()
        extra = Track(
            phoneme="KUCING", variant=0, text="Kucing!", folder=1, track=200,
            duration_ms=1000, sha256="x", voice="test",
        )
        polluted = BankManifest(
            version=manifest.version, voice=manifest.voice, rendered_at=manifest.rendered_at,
            tracks=[*manifest.tracks, extra], ui_tracks=manifest.ui_tracks,
        )
        assert any("orphan" in p for p in polluted.validate_against_templates())

    def test_require_valid_raises_on_drift(self):
        manifest = self._manifest_from_templates(text_for=lambda t: "berbeda sekali")
        with pytest.raises(BankMismatchError):
            manifest.require_valid()

    def test_round_trips_through_json(self, tmp_path):
        original = self._manifest_from_templates()
        path = tmp_path / "manifest.json"
        original.dump(path)
        reloaded = BankManifest.load(path)
        assert reloaded.tracks == original.tracks
        assert reloaded.ui_tracks == original.ui_tracks
        assert reloaded.validate_against_templates() == []

    def test_version_mismatch_is_rejected(self, tmp_path):
        path = tmp_path / "manifest.json"
        self._manifest_from_templates().dump(path)
        path.write_text(path.read_text().replace('"version": 1', '"version": 99', 1))
        with pytest.raises(BankMismatchError):
            BankManifest.load(path)

    def test_track_number_lookup(self):
        manifest = self._manifest_from_templates()
        for entry in list(iter_bank_entries())[::11]:
            assert manifest.track_number(entry.phoneme, entry.variant) == entry.track
