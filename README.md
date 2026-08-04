# SpeechLLM — Terapi Wicara AI 🇮🇩

AI-powered speech therapy assistant for Indonesian children aged 18–36 months, built to run **offline** on an Orange Pi Zero 3.

A toddler babbles into a USB microphone. The device recognizes the sound, maps it to a canonical phoneme, and plays back an encouraging Indonesian phrase built on **Expansion** and **Modeling** speech-therapy techniques — with no internet connection and no API key.

## How it works

```
🎤 USB mic → [Silero VAD] → [Segmenter] → [Whisper tiny] → [Phoneme Extractor]
                                                                    │
                                                          [Semantic Router]
                                                                    │
                                                          [Phrase Bank lookup]
                                                                    │
                              🔊 Speaker ← [PAM8403 amp] ← [DFPlayer Mini: play track 47]
```

The key design decision: **the DFPlayer Mini plays numbered MP3s from its own SD card and cannot speak text generated at runtime.** So all 105 therapy phrases are rendered to audio once, on a laptop, using a high-quality Indonesian voice, and burned to that card. At runtime the Pi only decides *which track to play*.

That inversion is what makes the device work with zero network:

| | |
|---|---|
| Runtime API keys | **none** |
| Runtime internet | **none** |
| Time to speak | ~100 ms after the decision |
| Voice quality | cloud TTS, rendered offline |
| Phrase safety | every line human-reviewed before rendering |

Gemini still has a role — as a **build-time authoring tool** that drafts new phrase variants for a human to review, never as a runtime dependency.

## Layout

```
packages/speechllm-core/     pure logic: detection, routing, generation, bank numbering
packages/speechllm-device/   Orange Pi app: capture, VAD, STT, pipeline, hardware, sinks
packages/speechllm-server/   FastAPI dev harness (laptop only)
tools/                       build-time: render_bank, verify_bank, bench_device
deploy/orangepi/             install.sh, systemd unit, wiring guide
assets/bank/manifest.json    committed index of what is on the SD card
```

`core` has no hardware or I/O imports, so the whole routing pipeline is testable on a laptop with no board attached.

## Quick start (laptop)

Requires Python 3.10+.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e packages/speechllm-core -e packages/speechllm-server
pip install pytest pytest-asyncio
pytest tests/ -q
```

Poke at the routing logic over HTTP:

```bash
uvicorn speechllm_server.main:app --reload
```

```bash
curl -X POST http://localhost:8000/process-text -H "Content-Type: application/json" -d '{"text": "ma"}'
```

```json
{
  "text": "Mama! Iya Mama di sini sayang!",
  "source": "template",
  "phoneme": "MA",
  "intent_category": "syllable_modeling",
  "technique": "modeling",
  "latency_ms": 0.12,
  "confidence": 0.9,
  "bank_phoneme": "MA",
  "bank_variant": 0
}
```

`bank_phoneme` + `bank_variant` are what the device turns into an SD-card track number.

## Building the phrase bank

Run on your laptop; this is the only step that uses a text-to-speech service.

```bash
pip install -r tools/requirements-tools.txt
python tools/render_bank.py                # gTTS (free, no key)
python tools/render_bank.py --voice google-cloud   # better id-ID voices
python tools/verify_bank.py
```

Then copy to the DFPlayer's card (FAT32) and strip macOS metadata — **not optional**, since AppleDouble `._` files are counted as tracks:

```bash
cp -R assets/bank/01 assets/bank/02 /Volumes/BANK/
dot_clean /Volumes/BANK && find /Volumes/BANK -name '._*' -delete
python tools/verify_bank.py --card /Volumes/BANK
```

Only changed phrases are re-synthesized, so editing one template costs one API call rather than 105.

## Hardware

| Part | Notes |
|---|---|
| Orange Pi Zero 3 | Allwinner H618, quad Cortex-A53 |
| USB microphone | Any UAC capsule |
| DFPlayer Mini + microSD | FAT32, ≤32 GB, separate from the OS card |
| PAM8403 amp | Required — do not drive a 4Ω speaker from the DFPlayer directly |
| Speaker 4Ω 3W | |
| 5V 3A supply | Do not power the DFPlayer from the Pi's header alone |

**First-time setup:** [deploy/orangepi/SETUP.md](deploy/orangepi/SETUP.md) walks you from flashing the SD card to a running service, with a checkpoint at every stage.

**Hardware reference:** [deploy/orangepi/README.md](deploy/orangepi/README.md) has the full wiring diagram, GPIO numbering, power warnings and troubleshooting table.

## Deploying

Full walkthrough in [deploy/orangepi/SETUP.md](deploy/orangepi/SETUP.md). In short:

```bash
sudo ./deploy/orangepi/install.sh
```

Then work the milestones in order — **benchmark first**, since Whisper is the entire latency budget on an A53:

```bash
python tools/bench_device.py                                      # M0
python -m speechllm_device.hardware.dfplayer --folder 1 --track 1 # M3
python -m speechllm_device --list-devices                         # M4
python -m speechllm_device --verbose                              # M5, WiFi off
sudo systemctl start speechllm                                    # M6
```

## Speech therapy techniques

**Expansion (Ekspansi)** — take the child's sound, expand it into a real word, praise:
> Child: "a" → "Ayah! Wah pintar, coba bilang Ayah!"

**Modeling (Pemodelan)** — provide the correct pronunciation with an enthusiastic tone:
> Child: "ma" → "Mama! Iya Mama di sini, pintar sekali!"

**Melodic Jargon Response** — redirect unintelligible babbling toward real words:
> Child: "lalala" → "Wah suara bagus! Coba bilang Mama!"

Every response is capped at 10 words, enforced across the whole template table by the test suite.

## Adding a phoneme

Three tables must change in lockstep, or the new sound silently degrades to the generic NOISE pool:

1. `PHONEME_MAP` in `core/detection/phonemes.py`
2. `INTENT_REGISTRY` in `core/routing/intents.py`
3. `TEMPLATES` in `core/routing/templates.py`

Then re-render the bank and re-burn the card — the device refuses to start if the card and the code disagree. `tests/test_bank.py` and `tools/verify_bank.py` enforce all of this.

## License

MIT
