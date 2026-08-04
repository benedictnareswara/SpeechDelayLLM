"""
Tests for the utterance segmenter — the endpointing state machine.

Frames are synthetic: the segmenter only consumes the VAD's boolean decision
and confidence, so these tests drive it directly with scripted decisions rather
than running real audio through Silero.
"""

import numpy as np
import pytest
from speechllm_device.pipeline.segmenter import (
    PREROLL_FRAMES,
    EndReason,
    Segmenter,
    State,
)

FRAME_SIZE = 512
SAMPLE_RATE = 16000
FRAME_MS = FRAME_SIZE / SAMPLE_RATE * 1000  # 32 ms


def frame(value: int = 1000) -> np.ndarray:
    return np.full(FRAME_SIZE, value, dtype=np.int16)


def feed(seg: Segmenter, pattern: str, confidence: float = 0.9):
    """Drive the segmenter with a pattern string: '.' silence, 'S' speech.

    Returns the list of utterances that completed.
    """
    out = []
    for char in pattern:
        is_speech = char == "S"
        result = seg.push(frame(), is_speech, confidence if is_speech else 0.05)
        if result is not None:
            out.append(result)
    return out


def frames_for_ms(ms: float) -> int:
    return int(np.ceil(ms / FRAME_MS))


@pytest.fixture
def seg():
    return Segmenter(
        sample_rate=SAMPLE_RATE,
        frame_size=FRAME_SIZE,
        min_speech_ms=150,
        max_speech_ms=3000,
        silence_ms=500,
    )


class TestTriggering:
    def test_starts_silent(self, seg):
        assert seg.state is State.SILENT
        assert not seg.is_speaking

    def test_silence_alone_never_triggers(self, seg):
        assert feed(seg, "." * 100) == []
        assert seg.state is State.SILENT

    def test_short_burst_is_rejected(self, seg):
        # 150 ms needs 5 frames; 3 frames of speech is a click, not a word.
        assert feed(seg, "..SSS..") == []
        assert seg.state is State.SILENT

    def test_sustained_speech_triggers(self, seg):
        feed(seg, "." * 3 + "S" * frames_for_ms(200))
        assert seg.is_speaking

    def test_repeated_short_bursts_do_not_accumulate(self, seg):
        # Each burst is below threshold and separated by silence: intermittent
        # noise must not add up into a false trigger.
        for _ in range(10):
            feed(seg, "SS.")
        assert seg.state is State.SILENT


class TestEndpointing:
    def test_completes_after_trailing_silence(self, seg):
        utterances = feed(
            seg,
            "S" * frames_for_ms(400) + "." * (frames_for_ms(500) + 1),
        )
        assert len(utterances) == 1
        assert utterances[0].reason is EndReason.SILENCE

    def test_does_not_complete_on_a_brief_pause(self, seg):
        # 200 ms gap is a toddler drawing breath, not the end of a turn.
        utterances = feed(
            seg,
            "S" * frames_for_ms(300) + "." * frames_for_ms(200) + "S" * frames_for_ms(300),
        )
        assert utterances == []
        assert seg.is_speaking

    def test_max_length_forces_a_cut(self, seg):
        utterances = feed(seg, "S" * frames_for_ms(4000))
        assert len(utterances) == 1
        assert utterances[0].reason is EndReason.MAX_LENGTH
        assert utterances[0].duration_ms <= 3000 + PREROLL_FRAMES * FRAME_MS + FRAME_MS

    def test_returns_to_silent_after_completing(self, seg):
        feed(seg, "S" * frames_for_ms(400) + "." * (frames_for_ms(500) + 1))
        assert seg.state is State.SILENT

    def test_two_utterances_in_sequence(self, seg):
        pattern = ("S" * frames_for_ms(300) + "." * (frames_for_ms(500) + 2)) * 2
        assert len(feed(seg, pattern)) == 2


class TestPreroll:
    def test_preroll_is_prepended(self, seg):
        # Silence first fills the ring buffer, so the utterance should be longer
        # than the speech frames alone.
        speech_frames = frames_for_ms(200)
        feed(seg, "." * 20 + "S" * speech_frames)
        utterances = feed(seg, "." * (frames_for_ms(500) + 1))

        assert len(utterances) == 1
        captured = utterances[0].sample_count / FRAME_SIZE
        assert captured > speech_frames, "pre-roll frames were not prepended"
        assert captured <= speech_frames + PREROLL_FRAMES + frames_for_ms(500) + 1

    def test_preroll_is_capped(self, seg):
        feed(seg, "." * 500 + "S" * frames_for_ms(200))
        utterances = feed(seg, "." * (frames_for_ms(500) + 1))
        captured = utterances[0].sample_count / FRAME_SIZE
        # 500 silent frames must not all end up in the utterance.
        assert captured < 100


class TestUtteranceContents:
    def test_audio_is_int16(self, seg):
        got = feed(seg, "S" * frames_for_ms(300) + "." * (frames_for_ms(500) + 1))
        assert got[0].audio.dtype == np.int16

    def test_confidences_are_tracked(self, seg):
        got = feed(seg, "S" * frames_for_ms(300) + "." * (frames_for_ms(500) + 1), confidence=0.77)
        assert got[0].peak_confidence == pytest.approx(0.77)
        assert 0.0 < got[0].mean_confidence <= 0.77

    def test_duration_matches_sample_count(self, seg):
        got = feed(seg, "S" * frames_for_ms(400) + "." * (frames_for_ms(500) + 1))
        expected = got[0].sample_count / SAMPLE_RATE * 1000
        assert got[0].duration_ms == pytest.approx(expected)


class TestLifecycle:
    def test_flush_returns_partial_utterance(self, seg):
        feed(seg, "S" * frames_for_ms(400))
        utterance = seg.flush()
        assert utterance is not None
        assert utterance.reason is EndReason.FLUSHED

    def test_flush_when_silent_returns_none(self, seg):
        assert seg.flush() is None

    def test_reset_clears_in_progress_speech(self, seg):
        feed(seg, "S" * frames_for_ms(400))
        assert seg.is_speaking
        seg.reset()
        assert seg.state is State.SILENT
        # After a reset the next burst must re-earn its trigger.
        assert feed(seg, "SS") == []
