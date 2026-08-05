"""
End-to-end pipeline tests with fake hardware.

Drives the real Orchestrator, Segmenter and SemanticRouter with scripted audio,
a fake VAD and a fake recognizer — no microphone, no ONNX, no DFPlayer. This is
what makes the device logic testable on a laptop.
"""

import numpy as np
from speechllm_core.bank.numbering import UiSound
from speechllm_core.routing.router import SemanticRouter, TherapyResponse
from speechllm_device.input.stt import RecognitionResult
from speechllm_device.output.base import UnspeakableResponse
from speechllm_device.pipeline.orchestrator import Orchestrator
from speechllm_device.pipeline.segmenter import Segmenter

FRAME = 512


class FakeCapture:
    """Replays a scripted (frame, is_speech) sequence."""

    def __init__(self, utterances: int = 1, speech_frames: int = 13, gap_frames: int = 20):
        self.script: list[tuple[np.ndarray, bool]] = []
        for _ in range(utterances):
            self.script += [(np.zeros(FRAME, np.int16), False)] * 5
            self.script += [(np.full(FRAME, 5000, np.int16), True)] * speech_frames
            self.script += [(np.zeros(FRAME, np.int16), False)] * gap_frames
        self.drains = 0

    def frames(self, timeout: float = 1.0):
        yield from (f for f, _ in self.script)

    def drain(self) -> int:
        self.drains += 1
        return 0


class FakeVAD:
    def __init__(self, script):
        self._decisions = [s for _, s in script]
        self._i = 0
        self.resets = 0

    def detect(self, frame):
        decision = self._decisions[self._i]
        self._i += 1
        return decision, 0.92 if decision else 0.03

    def reset(self):
        self.resets += 1


class FakeSTT:
    def __init__(self, words: list[str], *, fail: bool = False):
        self._words = words
        self._i = 0
        self._fail = fail
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        assert audio.dtype == np.int16, f"recognizer got {audio.dtype}, expected int16"
        assert audio.ndim == 1
        if self._fail:
            raise RuntimeError("simulated transcription failure")
        word = self._words[self._i % len(self._words)]
        self._i += 1
        return RecognitionResult(text=word, confidence=0.88, is_partial=False)


class RecordingSink:
    """Records what was spoken and when, to assert on mic gating."""

    def __init__(self, *, unspeakable: bool = False):
        self.spoken: list[TherapyResponse] = []
        self.ui: list[UiSound] = []
        self.closed = False
        self._unspeakable = unspeakable

    def speak(self, response: TherapyResponse) -> float:
        if self._unspeakable:
            raise UnspeakableResponse("no track for this response")
        self.spoken.append(response)
        return 0.0

    def play_ui(self, sound: UiSound) -> None:
        self.ui.append(sound)

    def close(self) -> None:
        self.closed = True


def build(words, *, utterances=1, sink=None, stt=None, **capture_kwargs):
    capture = FakeCapture(utterances=utterances, **capture_kwargs)
    sink = sink or RecordingSink()
    orchestrator = Orchestrator(
        capture,
        FakeVAD(capture.script),
        stt or FakeSTT(words),
        SemanticRouter(),
        sink,
        Segmenter(min_speech_ms=150, max_speech_ms=3000, silence_ms=500),
        log_path=None,
        cooldown_ms=0,   # skip the real cooldown sleep; gating is asserted via drain()
    )
    return orchestrator, capture, sink


class TestHappyPath:
    def test_single_utterance_produces_one_response(self):
        orchestrator, _, sink = build(["ma"])
        orchestrator.run()
        assert orchestrator.stats.utterances == 1
        assert orchestrator.stats.responses == 1
        assert len(sink.spoken) == 1

    def test_response_matches_the_detected_phoneme(self):
        orchestrator, _, sink = build(["ma"])
        orchestrator.run()
        assert sink.spoken[0].phoneme == "MA"
        assert sink.spoken[0].technique == "modeling"

    def test_multiple_utterances_each_get_a_response(self):
        orchestrator, _, sink = build(["ma", "susu", "a"], utterances=3)
        orchestrator.run()
        assert orchestrator.stats.responses == 3
        assert [r.phoneme for r in sink.spoken] == ["MA", "SUSU", "A"]

    def test_every_response_is_playable_from_the_bank(self):
        orchestrator, _, sink = build(["ma", "susu", "a"], utterances=3)
        orchestrator.run()
        for response in sink.spoken:
            assert response.bank_phoneme is not None
            assert response.bank_variant is not None

    def test_ready_chime_plays_before_listening(self):
        orchestrator, _, sink = build(["ma"])
        orchestrator.run()
        assert sink.ui[0] is UiSound.READY

    def test_thinking_chime_plays_for_each_utterance(self):
        orchestrator, _, sink = build(["ma", "susu"], utterances=2)
        orchestrator.run()
        assert sink.ui.count(UiSound.THINKING) == 2


class TestMicGating:
    """The device must never hear itself."""

    def test_capture_is_drained_after_speaking(self):
        orchestrator, capture, _ = build(["ma"])
        orchestrator.run()
        assert capture.drains == 1, "audio buffered while speaking was not discarded"

    def test_vad_is_reset_after_speaking(self):
        # Silero carries LSTM state; without a reset the device's own voice
        # becomes leading context for the child's next sound.
        orchestrator, _, _ = build(["ma"])
        vad = orchestrator._vad
        orchestrator.run()
        assert vad.resets >= 1

    def test_drain_and_reset_happen_once_per_utterance(self):
        orchestrator, capture, _ = build(["ma", "susu", "a"], utterances=3)
        vad = orchestrator._vad
        orchestrator.run()
        assert capture.drains == 3
        assert vad.resets == 3


class TestFailureHandling:
    def test_stt_failure_does_not_stop_the_session(self):
        orchestrator, _, sink = build(
            ["ma"], utterances=2, stt=FakeSTT(["ma"], fail=True)
        )
        orchestrator.run()
        assert orchestrator.stats.stt_failures == 2
        assert orchestrator.stats.responses == 0
        assert UiSound.ERROR in sink.ui

    def test_stt_failure_still_closes_the_mic_gate(self):
        orchestrator, capture, _ = build(["ma"], stt=FakeSTT(["ma"], fail=True))
        orchestrator.run()
        assert capture.drains == 1, "a failed turn must still drain and reset"

    def test_unspeakable_response_is_counted_not_raised(self):
        orchestrator, _, sink = build(["ma"], sink=RecordingSink(unspeakable=True))
        orchestrator.run()
        assert orchestrator.stats.unspeakable == 1
        assert UiSound.ERROR in sink.ui

    def test_unrecognized_speech_falls_back_gracefully(self):
        orchestrator, _, sink = build(["zzzz"])
        orchestrator.run()
        assert orchestrator.stats.noise_rejects == 1
        assert sink.spoken[0].source == "fallback"
        # A fallback still has a track: the child always hears something.
        assert sink.spoken[0].bank_phoneme == "NOISE"


class TestInteractionLog:
    def test_writes_one_jsonl_record_per_turn(self, tmp_path):
        import json

        log = tmp_path / "interactions.jsonl"
        capture = FakeCapture(utterances=2)
        orchestrator = Orchestrator(
            capture,
            FakeVAD(capture.script),
            FakeSTT(["ma", "susu"]),
            SemanticRouter(),
            RecordingSink(),
            Segmenter(min_speech_ms=150, max_speech_ms=3000, silence_ms=500),
            log_path=log,
            cooldown_ms=0,
        )
        orchestrator.run()

        records = [json.loads(line) for line in log.read_text().splitlines()]
        assert len(records) == 2
        assert records[0]["phoneme"] == "MA"
        assert records[0]["transcript"] == "ma"
        assert "total_ms" in records[0]

    def test_unwritable_log_does_not_break_the_session(self, tmp_path):
        # A full or read-only filesystem must not end a therapy session.
        blocked = tmp_path / "file.txt"
        blocked.write_text("not a directory")
        orchestrator, _, sink = build(["ma"])
        orchestrator._log_path = blocked / "nested" / "log.jsonl"
        orchestrator.run()
        assert len(sink.spoken) == 1
