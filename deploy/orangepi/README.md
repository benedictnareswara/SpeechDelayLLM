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
| USB-TTL adapter, 3.3V | CH340/CP2102. Debug console *and* the zero-config serial route |

Note there are **two** SD cards: one holds the Pi's OS, the other lives inside the DFPlayer and holds the phrase bank. The Pi cannot read the DFPlayer's card.

## 26-pin header — pins used

Printed pinout diagrams label these inconsistently, so here is every name for the same physical pin:

| Physical pin | Allwinner | sysfs GPIO | wiringOP | Function here | Connects to |
|---|---|---|---|---|---|
| 2 / 4 | — | — | — | 5V | *(rail only — do **not** power the DFPlayer from here)* |
| 6 | — | — | — | GND | Common ground rail |
| 8 | `PH2` | 226 | 3 | UART5_TX | → 1kΩ → DFPlayer RX (2) |
| 10 | `PH3` | 227 | 4 | UART5_RX | ← DFPlayer TX (3) |
| 11 | `PI0` | **256** | 6 | GPIO input | ← DFPlayer BUSY (16) |
| 9, 14, 20, 25 | — | — | — | GND | Additional ground returns |

The sysfs number is `bank_index × 32 + pin`, with banks A=0 … I=8. So `PI0` = 8×32 + 0 = **256**, which is what `DFPLAYER_BUSY_GPIO` is set to. `PH2` = 7×32 + 2 = 226 — worth remembering, because that number shows up in kernel pin-conflict errors.

The serial debug console lives on the **separate 3-pin header** (UART0 / `PH0`,`PH1`), so using UART5 here does not conflict with it.

## DFPlayer Mini pinout

Two rows of 8:

- Left, top→bottom: `VCC(1) RX(2) TX(3) DAC_R(4) DAC_L(5) SPK_2(6) GND(7) SPK_1(8)`
- Right, bottom→top: `IO_1(9) GND(10) IO_2(11) ADKEY_1(12) ADKEY_2(13) USB+(14) USB-(15) BUSY(16)`

## Connections

The DFPlayer and the amp run from the **5V rail**, never from the Pi's header pins — see the power note below.

```
        5V 3A supply
             │
   ┌─────────┼───────────────┬──────────────────┐
   │         │               │                  │
Orange Pi   DFPlayer VCC(1)  PAM8403 VCC        (star ground to all three)
 USB-C       + 470µF/100nF
             │
Orange Pi Zero 3                     DFPlayer Mini
─────────────────                    ─────────────
pin 6  (GND)     ───────┬───────────  GND   (7)
                        └───────────  GND   (10)
pin 8  (PH2/TX5) ──[1kΩ]────────────  RX    (2)
pin 10 (PH3/RX5) ───────────────────  TX    (3)
pin 11 (PI0/256) ───────────────────  BUSY  (16)     LOW while playing

DFPlayer DAC_R (4) ───────────────►  PAM8403  R-IN
DFPlayer GND   (7) ───────────────►  PAM8403  GND
                   PAM8403 R-OUT+ ─►  Speaker +   (4Ω 3W)
                   PAM8403 R-OUT- ─►  Speaker −

USB microphone ──────────────────►  either USB-A port (no wiring)
```

### Serial without the device tree

If the UART5 overlay is uncooperative (see *Board configuration*), a USB-TTL adapter in either USB port gives you `/dev/ttyUSB0` with no kernel configuration at all. Move the three serial wires from the header onto the adapter and set `DFPLAYER_PORT=/dev/ttyUSB0`:

```
USB-TTL GND ───────────────  DFPlayer GND (7)     ← plus the Pi's ground
USB-TTL TX  ──[1kΩ]────────  DFPlayer RX  (2)
USB-TTL RX  ───────────────  DFPlayer TX  (3)
```

BUSY still goes to Pi pin 11 either way — that line is what gates the microphone, and nothing else can replace it.

### ⚠️ Do not connect the 4Ω speaker to SPK_1/SPK_2

The DFPlayer's onboard amplifier is specified for 3W into **8Ω**. A 4Ω load roughly doubles the current draw, which causes distortion, thermal throttling, and brownouts that reset the module mid-sentence. It is also a bridge-tied output, so neither terminal may be grounded.

Use the `DAC_R` line-out into a PAM8403 as drawn. *(Alternative if you'd rather buy nothing: swap to an 8Ω 3W speaker and drive SPK_1/SPK_2 directly, skipping the amp.)*

### ⚠️ Power

Do not run the DFPlayer **or** the amp from the Pi's header pins. Playback current spikes will brown out the SoC and can corrupt the OS SD card mid-write.

Use a 5V/3A supply feeding a small distribution rail, with the Pi's USB-C, the DFPlayer VCC and the amp VCC as separate branches sharing one **star ground**. Fit 470µF electrolytic + 100nF ceramic across DFPlayer VCC/GND.

The Zero 3's Type-C port is **power only** — not a data or OTG port.

### ⚠️ Logic levels

Orange Pi GPIO is 3.3V and **not 5V tolerant**. The DFPlayer's TX and BUSY idle at 3.3V so they connect directly. The 1kΩ on RX is the standard series resistor that suppresses audible switching noise.

## Board configuration

Find the overlay your image actually ships — the name has changed across releases:

```bash
ls /boot/dtb/allwinner/overlay/ | grep -i uart
```

Strip the `sun50i-h616-` prefix and `.dtbo` suffix to get the overlay name. The official Orange Pi Jammy 6.1.31 image ships **`sun50i-h616-ph-uart5.dtbo` → `ph-uart5`**, where the `ph` prefix is the GPIO bank — UART5 on `PH2`/`PH3`, header pins 8 and 10.

> Armbian builds for the same SoC name it `uart5-ph` or `uart5` instead. U-Boot ignores an unknown overlay silently — no error, no serial port — so always read the name off the `ls` rather than copying it from a guide.

```bash
sudo orangepi-config     # System → Hardware → enable ph-uart5 → reboot
```

Or in `/boot/orangepiEnv.txt`:

```
overlay_prefix=sun50i-h616
overlays=ph-uart5
```

Then verify both the node and the kernel's opinion of it:

```bash
ls -l /dev/ttyS*
dmesg | grep -iE 'uart|pinctrl'
```

The node is not guaranteed to be `ttyS5` — device-tree aliases decide the number, and some builds surface UART5 as `ttyS1`. Whatever appears is what goes in `DFPLAYER_PORT`. And a `pinctrl ...: request() failed for pin 226` line means the port exists but the pins are already claimed by something else, so the UART is dead; use the USB-TTL route above.

Check the microphone is visible:

```bash
arecord -l
cat /proc/asound/cards
```

## Preparing the DFPlayer's SD card

On your laptop, not the Pi. Required layout — the folder/file names are load-bearing, because playback uses DFPlayer command `0x0F` (play folder/file), which resolves by *filename*:

```
01/001.mp3 … 01/105.mp3    therapy phrases
02/001.mp3 … 02/003.mp3    ready / thinking / error
```

FAT32, **MBR** partition table, ≤32 GB, zero-padded two-digit folders and three-digit files.

**Windows** (Administrator PowerShell — `diskpart`, because Explorer's Format won't rewrite the partition table):

```powershell
diskpart
# list disk / select disk N / clean / create partition primary
# select partition 1 / format fs=fat32 quick label=BANK / assign / exit
robocopy .\assets\bank\01 E:\01 /E
robocopy .\assets\bank\02 E:\02 /E
python tools\verify_bank.py --card E:\
```

**macOS:**

```bash
diskutil eraseDisk FAT32 BANK MBRFormat /dev/diskN
cp -R assets/bank/01 assets/bank/02 /Volumes/BANK/
dot_clean /Volumes/BANK && find /Volumes/BANK -name '._*' -delete
python tools/verify_bank.py --card /Volumes/BANK
```

**That cleanup step is not optional on macOS.** Finder writes AppleDouble `._` files which the DFPlayer counts as tracks, shifting every index.

## Install

```bash
sudo ./deploy/orangepi/install.sh
```

Then check everything at once:

```bash
sudo ./deploy/orangepi/doctor.sh
```

`doctor.sh` is read-only. It inspects the serial port and overlay, every import in the virtualenv, the GPIO backend, the microphone, both models, the phrase bank and the service — and prints the fixing command for whatever fails. Run it first whenever something stops working.

Then work through the milestones:

```bash
# M0 — benchmark first; Whisper is the whole latency budget
python tools/bench_device.py

# M3 — DFPlayer smoke test (add --port /dev/ttyUSB0 to try another port)
python -m speechllm_device.hardware.dfplayer --folder 1 --track 1

# M4 — microphone
python -m speechllm_device --list-devices    # set AUDIO_INPUT_DEVICE in device.env

# M5 — full run, network unplugged
python -m speechllm_device --verbose

# M6 — service
sudo systemctl start speechllm && journalctl -u speechllm -f
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Serial port missing (`FileNotFoundError`, errno 2) | Overlay not enabled, no reboot, or the wrong overlay name — read it off `ls /boot/dtb/allwinner/overlay/` |
| Port exists but the DFPlayer never answers | `dmesg` shows `request() failed for pin 226` — pins already claimed; use a USB-TTL adapter |
| Permission denied on the port (errno 13) | User not in `dialout`; log out and back in after `usermod` |
| `bad interpreter: /bin/bash^M` | CRLF line endings from a Windows checkout; `.gitattributes` pins these to LF |
| `cannot import name 'Editops'` / `'yaml' has no attribute 'dump'` | A damaged package survived in the venv; re-run `install.sh`, which rebuilds it with `venv --clear` |
| DFPlayer plays the wrong phrase | Stray metadata files on the card, or code 0x03 used instead of 0x0F |
| "track not found" (error 0x06) | File missing, or the module was queried before the card mounted (~2 s) |
| Module resets mid-phrase | Power brownout — separate supply, add the bulk capacitor |
| Device replies to itself in a loop | BUSY pin not wired or wrong GPIO number; check `DFPLAYER_BUSY_GPIO=256` |
| No audio at all, BUSY toggles correctly | Amp not powered, or speaker wired to SPK_1/SPK_2 instead of DAC_R |
| Whisper hangs at startup | Weights staged under a different `HF_HOME` than the service reads, with `HF_HUB_OFFLINE=1` |
| Refuses to start: bank mismatch | `templates.py` changed since the card was burned — re-render and re-copy |
