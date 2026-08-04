# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

SpeechLLM — an Indonesian speech therapy assistant for children aged 18–36 months, built to run on an **Orange Pi Zero 3 with no network connection**. A toddler babbles at a USB microphone; the device recognizes the sound, maps it to a canonical phoneme, and plays an encouraging Indonesian phrase built on speech-therapy *expansion* and *modeling* techniques.

## The architectural decision everything follows from

Audio output is a **DFPlayer Mini**, which plays numbered MP3s from its own microSD card. It cannot be fed audio generated at runtime — the Pi can only say "play track 47".

So the phrase bank (exactly **105 phrases**: 21 phonemes × 5 variants in `routing/templates.py`) is **rendered to MP3 once at build time on a laptop** and burned to the card. At runtime the device only chooses a track number. Consequences that shape the whole codebase:

- The device needs **no API keys and no internet**. `google-generativeai`, `gTTS`, `fastapi` are deliberately *not* device dependencies.
- Gemini is a **build-time authoring tool** (`tools/expand_bank.py`), never a runtime dependency. A human reviews every phrase before a child hears it.
- `speechllm_core.generation` still exists and is exercised by the dev server, but the device never imports it.
- A response with no pre-rendered track raises `UnspeakableResponse` rather than playing something arbitrary.

## Layout

Three installable packages. `core` is pure logic — no hardware, no I/O — so it stays testable on a laptop.

```
packages/speechllm-core/      detection, routing, generation, bank numbering
packages/speechllm-device/    Orange Pi app: capture, VAD, STT, pipeline, hardware, sinks
packages/speechllm-server/    FastAPI dev harness (laptop only, not deployed)
tools/                        build-time: render_bank, verify_bank, bench_device
deploy/orangepi/              install.sh, systemd unit, device.env, asound.conf
assets/bank/manifest.json     committed index of what is on the SD card
```

## Commands

Setup (needs Python ≥3.10; the macOS system Python 3.9 is too old):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e packages/speechllm-core -e packages/speechllm-server
pip install pytest pytest-asyncio
```

Tests — run from the repo root:

```bash
pytest tests/ -q
```

Single test / single case:

```bash
pytest tests/test_segmenter.py -v
pytest tests/test_orchestrator.py::TestMicGating -v
pytest -m "not hardware"          # skip anything needing the board
```

Dev server (laptop):

```bash
uvicorn speechllm_server.main:app --reload
```

Phrase bank:

```bash
python tools/render_bank.py --dry-run     # show the plan
python tools/render_bank.py               # synthesize 105 MP3s + manifest
python tools/verify_bank.py               # consistency check (also runs in pytest)
python tools/verify_bank.py --card /Volumes/BANK
```

Device (on the Pi):

```bash
python -m speechllm_device --list-devices
python -m speechllm_device --dry-run -v
python -m speechllm_device.hardware.dfplayer --folder 1 --track 7
python tools/bench_device.py
```

## Architecture

**`core/detection/phonemes.py`** is the semantic chokepoint. Recognizer text → one of ~21 canonical labels via exact `PHONEME_MAP` lookup, then Levenshtein fuzzy match (≤5 chars only, confidence scaled down 0.3 per edit), then first-word recursion, then `NOISE`.

**`core/routing/`** — `INTENT_REGISTRY` maps each phoneme to a `TherapeuticIntent`; `SemanticRouter.route()` is the single entry point for the response path. It rejects `NOISE` and anything below `phoneme_confidence_threshold`, then rolls `gemini_usage_percent` (0 on the device) to choose Gemini vs template. Any Gemini failure falls through to a template — the child never gets an error.

`pick_template_variant()` returns `(resolved_phoneme, variant_index, text)` and the router records it on `TherapyResponse.bank_phoneme` / `.bank_variant`. **The device maps a response to a track by that pair, never by matching the text** — two pools can share phrasing. `resolved_phoneme` differs from the input when an unknown label falls back to the NOISE pool, and the track lookup depends on knowing that.

**`core/bank/numbering.py`** is the single source of truth for which phrase is which track. Numbering is a pure function of `sorted(TEMPLATES)` plus list order, so re-rendering an unchanged `templates.py` always produces identical track numbers.

**`device/pipeline/segmenter.py`** is the endpointing state machine (SILENT ↔ SPEAKING) that turns per-frame VAD decisions into utterances. It finally consumes `vad_min_speech_ms` / `vad_max_speech_ms` / `vad_silence_ms`, which were dead config before. Note the **pre-roll ring buffer**: VAD takes a few frames to become confident, and without replaying those the initial consonant — exactly what separates "ma" from "a" — gets clipped.

**`device/pipeline/orchestrator.py`** is the main loop: capture → VAD → segmenter → STT → phoneme → router → sink. Deliberately synchronous; `route()` is async only for the Gemini path the device never takes.

## Things that will bite you

- **Mic gating is not optional.** The speaker sits inches from the microphone. `_recover()` — cooldown, `capture.drain()`, `vad.reset()`, `segmenter.reset()` — is what stops the device transcribing its own voice and talking to itself forever. The DFPlayer BUSY pin (PI0, physical pin 11) is the ground truth for "still speaking". `tests/test_orchestrator.py::TestMicGating` guards it.
- **Adding a phoneme means three tables in lockstep**: `PHONEME_MAP`, `INTENT_REGISTRY`, `TEMPLATES`. Miss one and it silently degrades to the NOISE pool — that is what happened to the removed `KUCING` label. `tests/test_bank.py::TestCoverage` and `tools/verify_bank.py` enforce it. After changing templates, **re-render the bank and re-burn the card**, or the device refuses to boot on the manifest mismatch.
- **Every response must stay ≤10 words**, template or generated. Asserted across the whole table.
- **Address DFPlayer tracks with CMD 0x0F (folder/file), never 0x03.** 0x03 indexes by FAT write order, so a re-copied card plays the wrong phrases.
- **Strip macOS `._` files from the SD card** (`dot_clean`, `find -name '._*' -delete`). The DFPlayer counts them as tracks.
- **Settings are frozen.** `speechllm_core.settings.settings` is an immutable dataclass; inject values through constructors (as `Orchestrator(cooldown_ms=…)` does) rather than trying to monkeypatch it.
- **Don't import hardware modules for type hints.** `orchestrator.py` keeps `AudioCapture`/`SileroVAD`/`WhisperRecognizer` under `TYPE_CHECKING` so the pipeline is importable — and testable — without onnxruntime or faster-whisper.
- **Whisper dominates the latency budget** (0.8–2.5 s on the A53). Measure with `tools/bench_device.py` before tuning anything else. The "thinking" chime plays the instant an utterance ends specifically to cover it.

## Hardware

Orange Pi Zero 3, USB mic, DFPlayer Mini, 4Ω 3W speaker. `deploy/orangepi/SETUP.md` is the bring-up runbook (flashing → wiring → service); `deploy/orangepi/README.md` is the hardware reference. Two points worth repeating: the Pi's GPIO is **3.3V and not 5V tolerant**, and the 4Ω speaker must **not** be driven from the DFPlayer's `SPK_1`/`SPK_2` pins (rated for 8Ω) — use `DAC_R` into a PAM8403.
