# Bring-Up Runbook — bare board to working prototype

Follow these phases in order. Each ends with a **checkpoint**: if it fails, fix it there rather than moving on. Debugging a fully-assembled device is far harder than debugging one stage.

Hardware reference (pinouts, GPIO numbering, troubleshooting table) lives in [README.md](README.md). This file is the sequence.

**Two independent tracks.** Phases 1–3 (the Pi) and phases 4–5 (the DFPlayer) don't depend on each other. Do the card prep on your Mac while the Pi flashes and boots.

---

## Phase 0 — Before you start

### Parts checklist

- [ ] Orange Pi Zero 3
- [ ] **Two** microSD cards — one for the Pi's OS (16 GB+, A1/A2 rated), one for the DFPlayer (any size ≤32 GB; 4 GB is plenty)
- [ ] USB microphone
- [ ] DFPlayer Mini
- [ ] PAM8403 (or PAM8302) amplifier module
- [ ] Speaker, 4Ω 3W
- [ ] 5V 3A USB-C power supply
- [ ] 1kΩ resistor, 470µF electrolytic + 100nF ceramic capacitor
- [ ] Jumper wires, breadboard or perfboard
- [ ] USB-C cable, Ethernet cable (strongly recommended for first boot)
- [ ] *Optional but worth it:* USB-TTL serial adapter (3.3V) for the debug console

> **Buy a good OS card.** Cheap microSD cards corrupt when power is cut mid-write, and this project deliberately draws current spikes right next to the Pi. A Samsung Endurance or SanDisk High Endurance card is a few dollars more and saves you re-flashing.

### ⚠️ Verify your image matches the board

You mentioned `orangepiezero3_1.0.0_ubuntu_jammy_server_linux5.4.125.7z`. **Check this before flashing.**

Kernel **5.4.125** is the Allwinner legacy BSP kernel used for **H616/H6** boards — Orange Pi Zero 2, Orange Pi 3 LTS. The Orange Pi Zero 3 uses the **H618**, whose official images ship kernel **6.1.x**. A Zero 2 image on a Zero 3 will not boot: wrong device tree, wrong SoC.

Go to the official Orange Pi Zero 3 download page and confirm the filename starts with `Orangepizero3_` and the kernel is `6.1.x`. If you already have a 5.4.125 image, download the correct one before continuing.

**Symptom if you get this wrong:** the red power LED comes on, the green LED never blinks, nothing on HDMI, no DHCP lease. It looks like a dead board — it isn't.

### Extract the image

```bash
brew install p7zip
```

```bash
7z x Orangepizero3_1.0.0_ubuntu_jammy_server_linux6.1.31.7z
```

You should get a `.img` file of several hundred MB. If the download page provided a `.sha` file, verify it:

```bash
shasum -a 256 Orangepizero3_1.0.0_ubuntu_jammy_server_linux6.1.31.img
```

---

## Phase 1 — Flash the OS card

**Easiest route:** install [balenaEtcher](https://etcher.balena.io/), select the `.img`, select the card, flash. It validates automatically and refuses to write to your system disk. Skip to the checkpoint.

**Command-line route**, if you prefer. Be careful — `dd` to the wrong disk destroys it.

```bash
diskutil list
```

Identify your card by **size** (e.g. `31.9 GB`), not by number — numbers shift between insertions. Then, replacing `N` with that disk number:

```bash
diskutil unmountDisk /dev/diskN
```

```bash
sudo dd if=Orangepizero3_1.0.0_ubuntu_jammy_server_linux6.1.31.img of=/dev/rdiskN bs=4m status=progress
```

Note `rdiskN` (raw device), not `diskN` — it's roughly 10× faster. Then:

```bash
sync && diskutil eject /dev/diskN
```

> When you re-insert the card, macOS will pop up **"The disk you inserted was not readable by this computer."** That is expected — the card holds a Linux filesystem. Click **Ignore**. Never click Initialize.

**✅ Checkpoint:** flashing completed with no errors, and macOS shows the "not readable" dialog when the card is re-inserted.

---

## Phase 2 — First boot and network

1. Insert the OS card into the Pi.
2. Connect Ethernet to your router. *(WiFi works too, but Ethernet removes a whole class of first-boot problems. Use it for setup, switch to WiFi later if you want.)*
3. Connect the USB-C power supply **last**.

First boot takes 1–2 minutes — it resizes the filesystem and reboots itself once. The green LED blinking is your sign of life.

### Find the board

Check your router's DHCP client list for a host named `orangepizero3`, or scan:

```bash
arp -a | grep -i orange
```

If that's empty, install `nmap` and sweep your subnet:

```bash
brew install nmap && sudo nmap -sn 192.168.1.0/24
```

### Log in

```bash
ssh orangepi@<the-ip>
```

Default credentials are `orangepi` / `orangepi` (root is `root` / `orangepi`). Ubuntu images force a password change on first login — do it and record the new one.

### Confirm you're on the right board

```bash
uname -a && cat /proc/device-tree/model && free -h
```

You want to see `aarch64`, kernel `6.1.x`, a model string mentioning **Zero 3**, and your expected RAM. If the model says Zero 2 or the kernel is 5.4, stop — you flashed the wrong image (see Phase 0).

**✅ Checkpoint:** SSH works, `uname -a` shows aarch64 with kernel 6.1.x, model reads Orange Pi Zero 3.

### If it won't boot: the serial console

This is why the USB-TTL adapter is worth owning. The Zero 3 has a **3-pin debug header separate from the 26-pin GPIO header** (that separation is why UART5 is free for the DFPlayer later). Connect adapter GND↔GND, adapter RX↔board TX, adapter TX↔board RX — **do not connect the adapter's VCC**. Then:

```bash
brew install minicom && minicom -D /dev/tty.usbserial-XXXX -b 115200
```

You'll see U-Boot output, which tells you whether the board is failing to find the card, failing on the device tree, or panicking in the kernel.

---

## Phase 3 — Configure the Pi

### Enable UART5

The DFPlayer talks over UART5 on header pins 8 and 10.

```bash
sudo orangepi-config
```

Navigate: **System → Hardware**, find the UART5 overlay (likely named `ph-uart5`), enable it with the spacebar, save, and reboot.

If the menu name doesn't match, list what your image actually ships:

```bash
ls /boot/dtb/allwinner/overlay/ | grep -i uart
```

You can also edit the boot config directly:

```bash
sudo nano /boot/orangepiEnv.txt
```

Add or extend the overlays line — space-separated if you have several:

```
overlays=ph-uart5
```

Reboot, then verify:

```bash
ls -l /dev/ttyS*
```

**✅ Checkpoint:** `/dev/ttyS5` exists.

### Groups and housekeeping

```bash
sudo usermod -aG dialout,audio,gpio orangepi
```

Log out and back in for that to take effect — group membership isn't retroactive to a live session.

Set timezone and locale while you're in `orangepi-config` (**Personal → Timezone / Locale**). Then update:

```bash
sudo apt update && sudo apt upgrade -y
```

If your board has 1 GB of RAM, confirm zram is active so Whisper has headroom:

```bash
zramctl && free -h
```

**✅ Checkpoint:** `id` lists dialout, audio and gpio; `/dev/ttyS5` still present after reboot.

### Plug in the microphone

```bash
arecord -l
```

You should see a `USB` card listed. Record three seconds:

```bash
arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 -d 3 /tmp/test.wav
```

Adjust `plughw:1,0` to match the card and device numbers from `arecord -l`.

**There is no speaker on the Pi in this design** — audio output goes through the DFPlayer, which isn't an ALSA device — so you can't just `aplay` it back. Check the levels numerically instead:

```bash
python3 -c "
import wave,array
w=wave.open('/tmp/test.wav');d=array.array('h',w.readframes(w.getnframes()))
peak=max(abs(x) for x in d);rms=(sum(x*x for x in d)/len(d))**0.5
print(f'peak={peak} ({peak/32768*100:.1f}%)  rms={rms:.0f}')
print('SILENT — check the mic' if peak<500 else 'CLIPPING — lower the gain' if peak>32000 else 'looks good')
"
```

Speak normally at about the distance a toddler would sit. Peak in the 20–80% range is healthy. Adjust capture gain with `alsamixer -c 1` (F4 for capture view) if needed.

**✅ Checkpoint:** recording produces a non-silent, non-clipping waveform.

---

## Phase 4 — Prepare the DFPlayer's SD card

**On your Mac**, not the Pi. This is the only step that uses a text-to-speech service.

```bash
cd ~/Project/LLM/SpeechDelayLLM
source .venv/bin/activate
pip install -r tools/requirements-tools.txt
brew install ffmpeg
```

Render the 105 phrases:

```bash
python tools/render_bank.py
```

That uses gTTS — free, no key. For noticeably better Indonesian voices, set up a Google Cloud service account and use `python tools/render_bank.py --voice google-cloud` instead.

**Listen to a sample before continuing.** These are going to a child:

```bash
afplay assets/bank/01/001.mp3 && afplay assets/bank/01/047.mp3
```

### Format and copy

Insert the DFPlayer's card. Find it by size:

```bash
diskutil list
```

Format as FAT32 with an MBR partition table — the DFPlayer cannot read exFAT or GUID:

```bash
diskutil eraseDisk FAT32 BANK MBRFormat /dev/diskN
```

```bash
cp -R assets/bank/01 assets/bank/02 /Volumes/BANK/
```

### ⚠️ Strip macOS metadata — not optional

Finder writes AppleDouble `._` sidecar files and `.DS_Store`. **The DFPlayer counts these as tracks**, shifting every index, and you get the wrong phrase for every sound.

```bash
dot_clean /Volumes/BANK
find /Volumes/BANK -name '._*' -delete
find /Volumes/BANK -name '.DS_Store' -delete
```

Verify:

```bash
python tools/verify_bank.py --card /Volumes/BANK
```

```bash
diskutil eject /Volumes/BANK
```

**✅ Checkpoint:** `verify_bank.py --card` reports all sections passing.

---

## Phase 5 — Test the DFPlayer alone

**Do this before connecting anything to the Pi.** It proves the module, the card, the amp and the speaker all work, with zero software involved. If you skip it and the assembled device is silent, you won't know which of five things is at fault.

Wire only this:

```
5V supply + ──────► DFPlayer VCC (1)
5V supply − ──────► DFPlayer GND (7)
                    470µF + 100nF across VCC/GND

DFPlayer DAC_R (4) ──► PAM8403 R-IN
DFPlayer GND   (7) ──► PAM8403 GND
5V supply +        ──► PAM8403 VCC
PAM8403 R-OUT+     ──► Speaker +
PAM8403 R-OUT−     ──► Speaker −
```

Insert the prepared card, apply power. Wait ~2 seconds for the card to mount, then **briefly touch IO_2 (pin 11) to GND** — that's the module's built-in "next track" button.

You should hear an Indonesian phrase.

> Default power-on volume is around 20/30 and can be startling. Keep your hand near the supply the first time.

**✅ Checkpoint:** touching IO_2 to GND plays audible, clean speech.

**If nothing plays:** re-check the card is FAT32/MBR with a `01` folder; confirm the amp has power; try the other amp channel; measure 5V actually present at DFPlayer pin 1 under load.

---

## Phase 6 — Wire it together

**Power everything off first.** The Pi's GPIO is 3.3V and **not 5V tolerant** — a slip here kills the pin or the SoC.

Add these four connections to what you already built in Phase 5:

```
Orange Pi Zero 3                     DFPlayer Mini
─────────────────                    ─────────────
pin 6  (GND)     ───────────────────  GND   (7)     ← common ground, connect FIRST
pin 8  (PH2/TX5) ──[1kΩ]────────────  RX    (2)
pin 10 (PH3/RX5) ───────────────────  TX    (3)
pin 11 (PI0)     ───────────────────  BUSY  (16)
```

Four rules:

1. **Common ground first, always.** Signal wires between boards that don't share a ground reference can destroy inputs.
2. **The 1kΩ goes in series on the Pi TX → DFPlayer RX line.** It suppresses audible switching noise. DFPlayer TX → Pi RX connects directly.
3. **TX goes to RX, RX goes to TX.** Crossed, not straight. This is the single most common wiring mistake.
4. **Do not power the DFPlayer from the Pi's 5V header pins** even though the diagram in README.md shows it as an option. With the amp attached, playback current spikes will brown out the SoC and can corrupt the OS card mid-write. Feed both from the 5V rail, sharing one star ground with the Pi.

Before applying power, check continuity with a multimeter: Pi pin 6 ↔ DFPlayer pin 7 should read near zero ohms; Pi pin 8 ↔ DFPlayer pin 2 should read ~1kΩ.

**✅ Checkpoint:** continuity checks pass, no shorts between 5V and GND, board powers up and SSH still works.

---

## Phase 7 — Install the software

Copy the project to the Pi:

```bash
rsync -av --exclude '.venv' --exclude '.git' --exclude 'assets/bank/01' --exclude 'assets/bank/02' \
    ~/Project/LLM/SpeechDelayLLM/ orangepi@<the-ip>:~/SpeechDelayLLM/
```

The rendered MP3s are excluded deliberately — they live on the DFPlayer's card, not the Pi. The **manifest** is included, and the device validates against it at boot.

On the Pi:

```bash
cd ~/SpeechDelayLLM && sudo ./deploy/orangepi/install.sh
```

### Stage the models while you still have network

The device is meant to run offline, and `HF_HUB_OFFLINE=1` in `device.env` will stop Whisper from reaching out later. So download now:

```bash
sudo -u speechllm HF_HOME=/opt/speechllm/models/hf /opt/speechllm/.venv/bin/python -c "
from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')
print('whisper tiny cached')"
```

```bash
ls -la /opt/speechllm/models/
```

You want `silero_vad.onnx` present, plus a populated `hf/` directory.

**✅ Checkpoint:** `install.sh` finishes without errors; both models are on disk.

---

## Phase 8 — Bring-up tests, in order

### M0 — Benchmark first

Do this before anything else. Whisper is the entire latency budget, and every later tuning decision depends on the real number.

```bash
cd /opt/speechllm && sudo -u speechllm .venv/bin/python tools/bench_device.py
```

Read the verdict it prints. Under ~2 s perceived is comfortable; 2–3 s is workable with the thinking chime; over 3 s means shorten `VAD_SILENCE_MS`, or move to whisper.cpp before building further.

For a realistic number, record actual clips first:

```bash
sudo -u speechllm .venv/bin/python tools/bench_device.py --record 10 --wav-dir /tmp/clips
sudo -u speechllm .venv/bin/python tools/bench_device.py --wav-dir /tmp/clips
```

### M3 — DFPlayer over UART

```bash
sudo -u speechllm /opt/speechllm/.venv/bin/python \
    -m speechllm_device.hardware.dfplayer --folder 1 --track 1 --verbose
```

Then try track 47 and confirm you hear a *different* phrase. Same phrase both times means the card indexing is wrong — go back and strip the `._` files.

### M4 — Microphone through the app

```bash
sudo -u speechllm /opt/speechllm/.venv/bin/python -m speechllm_device --list-devices
```

Put the matching substring into `AUDIO_INPUT_DEVICE` in `/etc/speechllm/device.env`. If your mic won't open at 16 kHz, leave `AUDIO_CAPTURE_RATE=48000` set — the code resamples.

### M5 — Full loop, offline

Dry run first (no audio output, logs only) to confirm the listen/segment/recognize path:

```bash
sudo -u speechllm /opt/speechllm/.venv/bin/python -m speechllm_device --dry-run --verbose
```

Say "ma" and watch for `🎤 utterance` → `📝 'ma'` → `🔊 [template track ...]`.

Then the real thing, **with WiFi off** to prove offline operation:

```bash
sudo nmcli radio wifi off
sudo -u speechllm /opt/speechllm/.venv/bin/python -m speechllm_device --verbose
```

Say "ma" → you should hear a Mama phrase within about three seconds.

**The test that matters most:** say ten things in a row. If the device ever responds to *itself* — a reply immediately triggering another reply with no one speaking — the BUSY pin isn't working. Check the wire to pin 11 and that `DFPLAYER_BUSY_GPIO=256`.

### M6 — Run as a service

```bash
sudo systemctl start speechllm && journalctl -u speechllm -f
```

Reboot and confirm it comes back on its own:

```bash
sudo reboot
```

Then soak it for 30 minutes and check the counters:

```bash
tail -f /var/log/speechllm/interactions.jsonl
```

**✅ Checkpoint:** survives a reboot, responds correctly, never triggers itself.

---

## Tuning once it works

Edit `/etc/speechllm/device.env`, then `sudo systemctl restart speechllm`.

| Symptom | Setting | Try |
|---|---|---|
| Cuts the child off mid-babble | `VAD_SILENCE_MS` | raise to 600–700 |
| Feels sluggish to respond | `VAD_SILENCE_MS` | lower to 300–350 |
| Triggers on room noise | `VAD_THRESHOLD` | raise to 0.6–0.7 |
| Misses quiet sounds | `VAD_THRESHOLD` | lower to 0.35–0.4 |
| Too loud / too quiet | `DFPLAYER_VOLUME` | 0–30, default 22 |
| Responds to its own voice | `SPEAK_COOLDOWN_MS` | raise to 500 — but fix the BUSY pin first |

Review real sessions to guide this:

```bash
python3 -c "
import json
for line in open('/var/log/speechllm/interactions.jsonl'):
    r=json.loads(line)
    print(f\"{r['ts'][11:19]}  {r['utterance_ms']:>5}ms  {r['transcript']!r:12} -> {r['phoneme']:6}  {r['total_ms']:>5}ms\")
"
```

---

## Quick troubleshooting

| Symptom | Likely cause |
|---|---|
| No boot, red LED only | Wrong image for the board (Phase 0), or a bad flash |
| `/dev/ttyS5` missing | UART5 overlay not enabled, or no reboot after enabling |
| Permission denied on `/dev/ttyS5` | Not in `dialout`, or didn't log out and back in |
| DFPlayer silent, BUSY toggles | Amp unpowered, or speaker on SPK_1/SPK_2 instead of DAC_R |
| Wrong phrase every time | Stray `._` files on the card |
| Error 0x06 "track not found" | File missing, or queried before the card mounted (~2 s) |
| Module resets mid-phrase | Power brownout — separate supply, add the bulk capacitor |
| Device talks to itself | BUSY pin not wired, or wrong GPIO number |
| Whisper hangs at startup | Models not staged and `HF_HUB_OFFLINE=1` set |
| Refuses to start, bank mismatch | `templates.py` changed since the card was burned — re-render, re-copy |
| Random filesystem corruption | Cheap SD card, or the Pi is being browned out by playback |

For anything not here, the service journal is the first place to look:

```bash
journalctl -u speechllm -n 100 --no-pager
```
