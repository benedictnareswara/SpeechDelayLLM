# Orange Pi Zero 3 — Hardware & Deployment

Hardware reference for the SpeechLLM prototype: pinouts, wiring, and troubleshooting.

> **Setting up for the first time?** Follow **[SETUP.md](SETUP.md)** instead — it is the
> step-by-step runbook from flashing the SD card through to a running service, with a
> checkpoint at each stage. This file is the reference you come back to.

> **Verify the pinout against your own board before soldering.** Run `gpio readall`
> (wiringOP) or check the official Zero 3 user manual. The Zero 3's 26-pin header is
> **not** identical to a Raspberry Pi's — most importantly, pins 8/10 are **UART5**,
> not UART0.

## Bill of materials

| Part | Notes |
|---|---|
| Orange Pi Zero 3 | Allwinner H618, quad Cortex-A53. 1 GB works; 2 GB+ is comfortable |
| USB microphone | Any UAC-compliant capsule; most only do 44.1/48 kHz (handled in software) |
| DFPlayer Mini | Plus its **own** microSD card, FAT32, ≤32 GB |
| PAM8403 or PAM8302 amp | ~$1. Required — see the speaker warning below |
| Speaker, 4Ω 3W | |
| 5V 3A supply | Feeding a small distribution rail |
| 1kΩ resistor | Series on the DFPlayer RX line |
| 470µF + 100nF capacitors | Across DFPlayer VCC/GND |

Note there are **two** SD cards: one holds the Pi's OS, the other lives inside the DFPlayer and holds the phrase bank. The Pi cannot read the DFPlayer's card.

## 26-pin header — pins used

| Physical pin | Function | Connects to |
|---|---|---|
| 2 or 4 | 5V | DFPlayer VCC *(see power note)* |
| 6 | GND | Common ground rail |
| 8 | `PH2` / UART5_TX | → 1kΩ → DFPlayer RX |
| 10 | `PH3` / UART5_RX | ← DFPlayer TX |
| 11 | `PI0` (GPIO 256) | ← DFPlayer BUSY |
| 9, 14, 20, 25 | GND | Additional ground returns |

The serial debug console lives on the **separate 3-pin header** (UART0 / `PH0`,`PH1`), so using UART5 here does not conflict with it.

## DFPlayer Mini pinout

Two rows of 8:

- Left, top→bottom: `VCC(1) RX(2) TX(3) DAC_R(4) DAC_L(5) SPK_2(6) GND(7) SPK_1(8)`
- Right, bottom→top: `IO_1(9) GND(10) IO_2(11) ADKEY_1(12) ADKEY_2(13) USB+(14) USB-(15) BUSY(16)`

## Connections

```
Orange Pi Zero 3                     DFPlayer Mini
─────────────────                    ─────────────
pin 2  (5V)      ───────────────────  VCC   (1)      ← see power note
pin 6  (GND)     ───────┬───────────  GND   (7)
                        └───────────  GND   (10)
pin 8  (PH2/TX5) ──[1kΩ]────────────  RX    (2)
pin 10 (PH3/RX5) ───────────────────  TX    (3)
pin 11 (PI0)     ───────────────────  BUSY  (16)     LOW while playing

DFPlayer DAC_R (4) ───────────────►  PAM8403  R-IN
DFPlayer GND   (7) ───────────────►  PAM8403  GND
                        5V ───────►  PAM8403  VCC
                   PAM8403 R-OUT+ ─►  Speaker +   (4Ω 3W)
                   PAM8403 R-OUT- ─►  Speaker −

USB microphone ──────────────────►  either USB-A port (no wiring)
```

### ⚠️ Do not connect the 4Ω speaker to SPK_1/SPK_2

The DFPlayer's onboard amplifier is specified for 3W into **8Ω**. A 4Ω load roughly doubles the current draw, which causes distortion, thermal throttling, and brownouts that reset the module mid-sentence. It is also a bridge-tied output, so neither terminal may be grounded.

Use the `DAC_R` line-out into a PAM8403 as drawn. *(Alternative if you'd rather buy nothing: swap to an 8Ω 3W speaker and drive SPK_1/SPK_2 directly, skipping the amp.)*

### ⚠️ Power

Do not run the DFPlayer **and** the amp from the Pi's header pins alone. Playback current spikes will brown out the SoC and can corrupt the OS SD card.

Use a 5V/3A supply feeding a small distribution rail, with the Pi's USB-C and the DFPlayer VCC as separate branches sharing one **star ground**. Fit 470µF electrolytic + 100nF ceramic across DFPlayer VCC/GND.

The Zero 3's Type-C port is **power only** — not a data or OTG port.

### ⚠️ Logic levels

Orange Pi GPIO is 3.3V and **not 5V tolerant**. The DFPlayer's TX and BUSY idle at 3.3V so they connect directly. The 1kΩ on RX is the standard series resistor that suppresses audible switching noise.

## Board configuration

Enable UART5 and confirm the device node:

```bash
sudo orangepi-config     # System → Hardware → enable "ph-uart5" → reboot
ls -l /dev/ttyS*         # expect /dev/ttyS5
```

GPIO numbering on the Allwinner BSP kernel is `bank_index * 32 + pin`, banks A=0 … I=8. So `PI0` = 8×32 + 0 = **256**.

Check the microphone is visible:

```bash
arecord -l
cat /proc/asound/cards
```

## Preparing the DFPlayer's SD card

On your laptop, not the Pi:

```bash
python tools/render_bank.py                   # or --voice google-cloud
diskutil eraseDisk FAT32 BANK MBRFormat /dev/diskN   # macOS
cp -R assets/bank/01 assets/bank/02 /Volumes/BANK/
dot_clean /Volumes/BANK && find /Volumes/BANK -name '._*' -delete
python tools/verify_bank.py --card /Volumes/BANK
```

**That cleanup step is not optional on macOS.** Finder writes AppleDouble `._` files which the DFPlayer counts as tracks, shifting every index.

## Install

```bash
sudo ./deploy/orangepi/install.sh
```

Then work through the milestones:

```bash
# M0 — benchmark first; Whisper is the whole latency budget
python tools/bench_device.py

# M3 — DFPlayer smoke test
python -m speechllm_device.hardware.dfplayer --folder 1 --track 1

# M4 — microphone
python -m speechllm_device --list-devices    # set AUDIO_INPUT_DEVICE in device.env

# M5 — full run, WiFi off
python -m speechllm_device --verbose

# M6 — service
sudo systemctl start speechllm && journalctl -u speechllm -f
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `/dev/ttyS5` missing | UART5 overlay not enabled — `orangepi-config`, then reboot |
| Permission denied on the port | User not in `dialout`; log out and back in after `usermod` |
| DFPlayer plays the wrong phrase | Stray `._` files on the card, or code 0x03 used instead of 0x0F |
| "track not found" (error 0x06) | File missing, or the module was queried before the card mounted (~2 s) |
| Module resets mid-phrase | Power brownout — separate supply, add the bulk capacitor |
| Device replies to itself in a loop | BUSY pin not wired or wrong GPIO number; check `DFPLAYER_BUSY_GPIO=256` |
| No audio at all, BUSY toggles correctly | Amp not powered, or speaker wired to SPK_1/SPK_2 instead of DAC_R |
| Whisper hangs at startup | Model not pre-staged and no network; set `HF_HOME` and pre-copy the weights |
| Refuses to start: bank mismatch | `templates.py` changed since the card was burned — re-render and re-copy |
