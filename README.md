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

There is no cloud code in the shipped system at all — no LLM client, no HTTP server, no key handling. The response path is a lookup.

## Layout

```
packages/speechllm-core/     pure logic: detection, routing, bank numbering — zero dependencies
packages/speechllm-device/   Orange Pi app: capture, VAD, STT, pipeline, hardware, sinks
tools/                       build-time: render_bank, verify_bank, bench_device
deploy/orangepi/             install.sh, doctor.sh, systemd unit, wiring guide
assets/bank/manifest.json    committed index of what is on the SD card
```

`core` has no hardware or I/O imports **and no third-party dependencies**, so the whole routing pipeline is testable on a laptop with no board attached — and cannot fail to build on a device with no compiler.

## Quick start (laptop)

Requires Python 3.10+.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e packages/speechllm-core && pip install pytest ruff
pytest tests/ -q
```

Try the routing logic directly:

```bash
python -c "
from speechllm_core.detection.phonemes import extract_phoneme
from speechllm_core.routing.router import SemanticRouter
r = SemanticRouter().route(extract_phoneme('ma', 0.9))
print(r.text, '→ bank', r.bank_phoneme, r.bank_variant)
"
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

Then copy to the DFPlayer's card — FAT32 with an **MBR** partition table, ≤32 GB, laid out as `01/001.mp3 … 01/105.mp3` and `02/001.mp3 … 02/003.mp3`. Full per-OS instructions are in [SETUP.md Phase 4](deploy/orangepi/SETUP.md); the short version:

```powershell
# Windows: diskpart → clean → create partition primary → format fs=fat32
robocopy .\assets\bank\01 E:\01 /E ; robocopy .\assets\bank\02 E:\02 /E
python tools\verify_bank.py --card E:\
```

```bash
# macOS: stripping AppleDouble metadata is NOT optional — the DFPlayer counts ._ files as tracks
diskutil eraseDisk FAT32 BANK MBRFormat /dev/diskN
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

Full walkthrough in [deploy/orangepi/SETUP.md](deploy/orangepi/SETUP.md). On the Pi:

```bash
git clone https://github.com/benedictnareswara/SpeechDelayLLM.git ~/SpeechDelayLLM
```

```bash
cd ~/SpeechDelayLLM && sudo ./deploy/orangepi/install.sh
```

Then check the whole install at once — it names the fix for anything that fails:

```bash
sudo ./deploy/orangepi/doctor.sh
```

Then work the milestones in order — **benchmark first**, since Whisper is the entire latency budget on an A53:

```bash
python tools/bench_device.py                                      # M0
python -m speechllm_device.hardware.dfplayer --folder 1 --track 1 # M3
python -m speechllm_device --list-devices                         # M4
python -m speechllm_device --verbose                              # M5, network unplugged
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
