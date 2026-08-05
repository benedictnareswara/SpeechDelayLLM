# Bring-Up Runbook — bare board to working prototype

Follow these phases in order. Each ends with a **checkpoint**: if it fails, fix it there rather than moving on. Debugging a fully-assembled device is far harder than debugging one stage.

Hardware reference (pinouts, GPIO numbering, troubleshooting table) lives in [README.md](README.md). This file is the sequence.

**Written for a Windows laptop talking to the Pi over an Ethernet cable.** macOS/Linux equivalents are in collapsed blocks where they differ.

**Two independent tracks.** Phases 1–3 (the Pi) and phases 4–5 (the DFPlayer) don't depend on each other. Do the card prep on your laptop while the Pi flashes and boots.

---

## Phase 0 — Before you start

### Parts checklist

- [ ] Orange Pi Zero 3
- [ ] **Two** microSD cards — one for the Pi's OS (16 GB+, A1/A2 rated), one for the DFPlayer (**≤32 GB**; 4 GB is plenty)
- [ ] USB microphone
- [ ] DFPlayer Mini
- [ ] PAM8403 (or PAM8302) amplifier module
- [ ] Speaker, 4Ω 3W
- [ ] 5V 3A power supply
- [ ] 1kΩ resistor, 470µF electrolytic + 100nF ceramic capacitor
- [ ] Jumper wires, breadboard or perfboard
- [ ] USB-C cable, Ethernet cable
- [ ] **USB-TTL serial adapter (3.3V, CH340 or CP2102).** Listed as optional in older versions of this doc — treat it as required. It is both the debug console *and* the fallback that bypasses the UART overlay entirely (Phase 3).

> **Buy a good OS card.** Cheap microSD cards corrupt when power is cut mid-write, and this project deliberately draws current spikes right next to the Pi. A Samsung Endurance or SanDisk High Endurance card is a few dollars more and saves you re-flashing.

### ⚠️ Get the right image

The Orange Pi Zero 3 uses the **Allwinner H618**, and its official images ship kernel **6.1.x**. Kernel **5.4.125** is the legacy BSP for **H616/H6** boards — Orange Pi Zero 2, Orange Pi 3 LTS.

From the official Orange Pi Zero 3 download page, take:

> **Ubuntu 22.04 Jammy — server — linux6.1.x**

Confirm the filename starts with `Orangepizero3_` and the kernel is `6.1.x`. A `linux5.4.x` build may boot far enough to look fine and then leave you without the UART5 device-tree overlay this project needs — which is a much more confusing failure than not booting at all.

### Install the Windows tools

```powershell
winget install 7zip.7zip Balena.Etcher Git.Git Python.Python.3.12 Gyan.FFmpeg
```

Known-good as of this writing: `Orangepizero3_1.0.4_ubuntu_jammy_server_linux6.1.31.7z`. The version prefix moves; the `linux6.1.x` suffix is the part that must not.

Extract the archive with 7-Zip (right-click → 7-Zip → Extract Here). You should get a `.img` file of several hundred MB. If the download page provided a checksum, verify it:

```powershell
Get-FileHash -Algorithm SHA256 .\Orangepizero3_1.0.4_ubuntu_jammy_server_linux6.1.31.img
```

<details>
<summary>macOS / Linux</summary>

```bash
brew install p7zip ffmpeg
7z x Orangepizero3_1.0.4_ubuntu_jammy_server_linux6.1.31.7z
shasum -a 256 Orangepizero3_1.0.4_ubuntu_jammy_server_linux6.1.31.img
```
</details>

---

## Phase 1 — Flash the OS card

Open **balenaEtcher**, select the `.img`, select the card, flash. It verifies the write automatically and refuses to target your system disk. Rufus works too (choose *DD Image* mode when prompted).

> When flashing finishes, Windows will pop up **"You need to format the disk in drive E: before you can use it."**
> **Click Cancel.** The card now holds Linux ext4 partitions that Windows cannot read. Formatting destroys the flash you just did. Expect this dialog every time you insert the card from now on.

**✅ Checkpoint:** Etcher reports "Flash Complete", and Windows offers to format the card when you re-insert it.

---

## Phase 2 — First boot and network over Ethernet

1. Insert the OS card into the Pi.
2. Connect the Ethernet cable between the Pi and your laptop.
3. Connect the USB-C power supply **last**.

First boot takes 1–2 minutes — it resizes the filesystem and reboots itself once. The green LED blinking is your sign of life.

### Share your laptop's internet over the cable

The Pi image is a DHCP **client**. A direct cable has no DHCP **server**, so without this step the Pi never gets an address and you cannot reach it. Windows Internet Connection Sharing solves both that and the Pi's need for internet in Phase 7:

1. Press `Win+R`, run `ncpa.cpl`
2. Right-click your **Wi-Fi** adapter → **Properties** → **Sharing** tab
3. Tick **"Allow other network users to connect through this computer's Internet connection"**
4. In the dropdown below, select your **Ethernet** adapter → OK

Your laptop becomes `192.168.137.1` and hands the Pi an address on that subnet. Give it ~30 seconds, then:

```powershell
arp -a | findstr 192.168.137
```

> **Alternative: use a router.** Plug both the laptop and the Pi into your router instead and skip ICS entirely. Find the Pi in the router's DHCP client list under the hostname `orangepizero3`. Simpler if you have one handy, and it survives the laptop sleeping.

### Log in

```powershell
ssh orangepi@192.168.137.x
```

OpenSSH is built into Windows 10 (1809+) and 11 — no PuTTY needed. Default credentials are `orangepi` / `orangepi`. Ubuntu images force a password change on first login — do it and record the new one.

### Confirm you're on the right board

```bash
uname -a && cat /proc/device-tree/model && free -h
```

You want `aarch64`, kernel `6.1.x`, and a model string mentioning **Zero 3**. If the kernel reads 5.4.x, you have the wrong image — go back to Phase 0. It may still work well enough to continue, but expect Phase 3 to fail.

**✅ Checkpoint:** SSH works, `uname -a` shows aarch64 with kernel 6.1.x, model reads Orange Pi Zero 3.

### If it never appears: the serial console

This is why the USB-TTL adapter is on the required list. The Zero 3 has a **3-pin debug header separate from the 26-pin GPIO header** (that separation is why UART5 is free for the DFPlayer later).

Connect adapter GND↔GND, adapter RX↔board TX, adapter TX↔board RX — **do not connect the adapter's VCC.** Find the COM port in Device Manager under *Ports (COM & LPT)*, then open PuTTY → Serial, 115200 baud.

You will see U-Boot output, which tells you whether the board is failing to find the card, failing on the device tree, or panicking in the kernel.

---

## Phase 3 — Give the DFPlayer a serial port

The DFPlayer needs **9600 8N1 on some UART**. It does not care which one. There are two ways to give it one, and the second is far less trouble.

### Option A (recommended for the prototype) — USB-TTL adapter

Plug the USB-TTL adapter into either of the Pi's USB ports:

```bash
ls -l /dev/ttyUSB*
```

That's it. No device tree, no reboot, no overlay. Set `DFPLAYER_PORT=/dev/ttyUSB0` in `/etc/speechllm/device.env` after Phase 7, and wire the DFPlayer to the adapter instead of to header pins 8/10 (Phase 6 shows both).

The trade-off is one occupied USB port and a slightly less tidy build. For getting a working prototype in front of a child, take it.

### Option B — UART5 on the GPIO header

Header pins 8 and 10 (`PH2`/`PH3`) only become a serial port once a device-tree overlay is loaded at boot.

**First, find out what your image actually ships.** The overlay name has changed across releases, and guessing is why this step commonly fails:

```bash
ls /boot/dtb/allwinner/overlay/ | grep -i uart
```

The overlay name is that filename with the `sun50i-h616-` prefix and `.dtbo` suffix stripped. On the official Orange Pi Jammy 6.1.31 image you get:

```
sun50i-h616-ph-uart5.dtbo   →  ph-uart5     ← the one you want
sun50i-h616-ph-uart2.dtbo   →  ph-uart2
sun50i-h616-pi-uart2.dtbo   →  pi-uart2
sun50i-h616-pi-uart3.dtbo   →  pi-uart3
sun50i-h616-pi-uart4.dtbo   →  pi-uart4
sun50i-h616-disable-uart0.dtbo
```

The prefix is the **GPIO bank**, not a word order quirk: `ph-uart5` is UART5 routed to the **PH** pins — `PH2`/`PH3`, header pins 8 and 10. The `pi-uart*` overlays map other UARTs onto port I pins and are not what you want.

> ⚠️ **Do not guess this name.** Armbian builds for the same SoC call it `uart5-ph` or `uart5`; the official Orange Pi image calls it `ph-uart5`. U-Boot ignores an unknown overlay **silently** — no error, no serial port — which is exactly the symptom that sends you looking at your wiring instead of your config. Always take the name from the `ls` above.

Enable it with `sudo orangepi-config` → **System → Hardware**, spacebar, save, reboot. Or edit the boot config directly:

```bash
sudo nano /boot/orangepiEnv.txt
```

```
overlay_prefix=sun50i-h616
overlays=ph-uart5
```

Reboot, then check **both** of these — the second one matters:

```bash
ls -l /dev/ttyS*
```

```bash
dmesg | grep -iE 'uart|pinctrl'
```

Two things can go wrong even when the overlay loads:

- **The node may not be `ttyS5`.** Numbering follows device-tree aliases, and on some builds UART5 surfaces as `/dev/ttyS1`. Whatever appears is what goes in `DFPLAYER_PORT`; nothing in the code hardcodes `ttyS5`.
- **The port can exist and still be dead.** If `dmesg` shows `sun50i-h616-pinctrl ...: request() failed for pin 226`, another peripheral already owns the pins. Pin 226 is `PH2` — the TX pin this project uses. Disable whatever claims it, or fall back to Option A.

**✅ Checkpoint:** `ls /dev/ttyS* /dev/ttyUSB*` shows at least one port, and `dmesg` has no `request() failed` lines for it.

### Groups and housekeeping

```bash
sudo usermod -aG dialout,audio,gpio orangepi
```

Log out and back in for that to take effect — group membership isn't retroactive to a live session.

Set timezone and locale in `orangepi-config` (**Personal → Timezone / Locale**), then update:

```bash
sudo apt update && sudo apt upgrade -y
```

**✅ Checkpoint:** `id` lists dialout, audio and gpio.

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

**On your laptop**, not the Pi. This is the only step that uses a text-to-speech service.

### Render the phrases

```powershell
cd C:\path\to\SpeechDelayLLM
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r tools\requirements-tools.txt
```

```powershell
python tools\render_bank.py
```

That uses gTTS — free, no key. For noticeably better Indonesian voices, set up a Google Cloud service account and use `python tools\render_bank.py --voice google-cloud` instead.

**Listen to a couple before continuing.** These are going to a child:

```powershell
start assets\bank\01\001.mp3
```

### What the card must look like

The layout is not a convention, it is load-bearing:

```
E:\
├── 01\001.mp3 … 01\105.mp3    the 105 therapy phrases
└── 02\001.mp3 … 02\003.mp3    ready / thinking / error tones
```

- **FAT32, MBR partition table.** The DFPlayer cannot read exFAT or a GPT disk.
- **≤32 GB.** Larger cards are unreliable in this module, and Windows won't offer FAT32 above 32 GB anyway.
- **Two-digit folders, three-digit files, both zero-padded.** `01\007.mp3`, never `1\7.mp3`.
- Playback uses DFPlayer command **`0x0F` (play folder/file)**, which resolves by *filename*. The more commonly seen `0x03` resolves by *FAT write order*, which is why a re-copied card can silently play the wrong phrase for every sound. Since we use `0x0F`, copy order doesn't matter — but the names must be exact.

### Format and copy on Windows

Explorer's right-click → Format leaves the existing partition table alone, and we need a fresh MBR. Use `diskpart` from an **Administrator** PowerShell:

```
diskpart
list disk
select disk N
clean
create partition primary
select partition 1
format fs=fat32 quick label=BANK
assign
exit
```

> ⚠️ `list disk` shows every disk in the machine. Identify the card by **size** and double-check before `select`. `clean` on the wrong disk wipes your laptop.

`clean` writes a fresh MBR; `create partition primary` + `format fs=fat32` gives the DFPlayer exactly what it expects. Then copy the two folders (assume the card came up as `E:`):

```powershell
robocopy .\assets\bank\01 E:\01 /E
robocopy .\assets\bank\02 E:\02 /E
```

### Clean up and verify

Windows creates `System Volume Information`, and may leave `Thumbs.db` or `desktop.ini` behind. Because we address tracks by filename these don't shift indexes the way macOS `._` files do, but they waste space and confuse later inspection:

```powershell
attrib -h -s E:\* /S /D
Remove-Item -Recurse -Force 'E:\System Volume Information' -ErrorAction SilentlyContinue
Get-ChildItem E:\ -Recurse -Include Thumbs.db,desktop.ini | Remove-Item -Force
```

```powershell
python tools\verify_bank.py --card E:\
```

Eject through **Safely Remove Hardware** in the system tray. Windows buffers writes, and pulling the card early gives you half-written MP3s that fail in ways that look like wiring faults.

<details>
<summary>macOS</summary>

```bash
diskutil list
diskutil eraseDisk FAT32 BANK MBRFormat /dev/diskN
cp -R assets/bank/01 assets/bank/02 /Volumes/BANK/
```

**Stripping AppleDouble metadata is not optional on macOS.** Finder writes `._` sidecar files and `.DS_Store`, and the DFPlayer counts them as tracks:

```bash
dot_clean /Volumes/BANK
find /Volumes/BANK -name '._*' -delete
find /Volumes/BANK -name '.DS_Store' -delete
python tools/verify_bank.py --card /Volumes/BANK
diskutil eject /Volumes/BANK
```
</details>

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

Add to what you already built in Phase 5, depending on which serial route you took in Phase 3.

**Option A — USB-TTL adapter (recommended):**

```
USB-TTL adapter                      DFPlayer Mini
───────────────                      ─────────────
GND              ───────────────────  GND   (7)     ← connect FIRST
TX               ──[1kΩ]────────────  RX    (2)
RX               ───────────────────  TX    (3)

Orange Pi Zero 3
─────────────────
pin 6  (GND)     ───────────────────  common ground rail
pin 11 (PI0)     ───────────────────  BUSY  (16)
```

The BUSY line still goes to the Pi — it is what gates the microphone. The adapter, the DFPlayer and the Pi must all share one ground.

**Option B — UART5 on the header:**

```
Orange Pi Zero 3                     DFPlayer Mini
─────────────────                    ─────────────
pin 6  (GND)     ───────────────────  GND   (7)     ← common ground, connect FIRST
pin 8  (PH2/TX5) ──[1kΩ]────────────  RX    (2)
pin 10 (PH3/RX5) ───────────────────  TX    (3)
pin 11 (PI0)     ───────────────────  BUSY  (16)
```

Four rules, either way:

1. **Common ground first, always.** Signal wires between boards that don't share a ground reference can destroy inputs.
2. **The 1kΩ goes in series on TX → DFPlayer RX.** It suppresses audible switching noise. DFPlayer TX → RX connects directly.
3. **TX goes to RX, RX goes to TX.** Crossed, not straight. This is the single most common wiring mistake.
4. **Do not power the DFPlayer from the Pi's 5V header pins.** With the amp attached, playback current spikes will brown out the SoC and can corrupt the OS card mid-write. Feed both from the 5V rail, sharing one star ground with the Pi.

Before applying power, check continuity with a multimeter: the two grounds should read near zero ohms; TX ↔ DFPlayer pin 2 should read ~1kΩ.

**✅ Checkpoint:** continuity checks pass, no shorts between 5V and GND, board powers up and SSH still works.

---

## Phase 7 — Install the software

The Pi needs network for this phase only — which it has, through the Ethernet cable and ICS from Phase 2. Everything after this runs offline.

### Push from Windows

On your laptop, commit and push whatever you have:

```powershell
git add -A
git commit -m "Device build"
git push
```

> **Line endings matter here.** Git for Windows defaults to `core.autocrlf=true`, which would check out `install.sh` with CRLF endings and make the Pi fail with `/bin/bash^M: bad interpreter`. The repo's `.gitattributes` pins `eol=lf` for every file the Pi reads, so this is handled — but if you ever see that error, that's why. Verify with `git ls-files --eol deploy/orangepi/install.sh`; you want `w/lf`.

### Clone on the Pi

```bash
sudo apt update && sudo apt install -y git
```

```bash
git clone https://github.com/benedictnareswara/SpeechDelayLLM.git ~/SpeechDelayLLM
```

```bash
cd ~/SpeechDelayLLM && sudo ./deploy/orangepi/install.sh
```

If the scripts aren't executable (Windows doesn't carry the executable bit), run `sudo bash ./deploy/orangepi/install.sh` instead.

The clone deliberately does **not** include the rendered MP3s — they're gitignored, because they belong on the DFPlayer's card, not the Pi. What it does include is `assets/bank/manifest.json`, the index the device validates against at boot. If the manifest and `templates.py` ever disagree, the device refuses to start rather than playing the wrong phrase for a child's sound.

`install.sh` stages both models for you, into the same `HF_HOME` the service reads. Do it while the cable is still plugged in — `HF_HUB_OFFLINE=1` means Whisper will not fetch anything later.

### Check everything at once

```bash
sudo /opt/speechllm/deploy/orangepi/doctor.sh
```

That inspects the serial port and overlay, the venv's imports, the GPIO backend, the microphone, both models, the phrase bank and the service, and prints the fixing command for anything that fails. Run it any time something stops working.

<details>
<summary>Alternative: copy from your laptop instead of cloning</summary>

Useful when you have local changes that aren't pushed yet. From PowerShell, with OpenSSH's `scp`:

```powershell
scp -r . orangepi@192.168.137.x:~/SpeechDelayLLM
```
</details>

### Updating later

```bash
cd ~/SpeechDelayLLM && git pull && sudo ./deploy/orangepi/install.sh
```

`install.sh` is safe to re-run: it rebuilds the virtualenv from scratch (`venv --clear`) so a half-finished earlier install can't linger, while preserving your `/etc/speechllm/device.env` so on-device tuning survives.

> If you changed `routing/templates.py`, you must also **re-render the bank and re-burn the DFPlayer card** (Phase 4). Pulling new code alone leaves the card stale and the device will refuse to start.

**✅ Checkpoint:** `install.sh` finishes without errors and `doctor.sh` reports no failures.

---

## Phase 8 — Bring-up tests, in order

### M0 — Benchmark first

Do this before anything else. Whisper is the entire latency budget, and every later tuning decision depends on the real number.

```bash
cd /opt/speechllm && sudo -u speechllm .venv/bin/python tools/bench_device.py
```

Under ~2 s perceived is comfortable; 2–3 s is workable with the thinking chime; over 3 s means shorten `VAD_SILENCE_MS`, or move to whisper.cpp before building further.

For a realistic number, record actual clips first:

```bash
sudo -u speechllm .venv/bin/python tools/bench_device.py --record 10 --wav-dir /tmp/clips
sudo -u speechllm .venv/bin/python tools/bench_device.py --wav-dir /tmp/clips
```

Once it passes, freeze the dependency set that worked — the whole set, not just the direct packages:

```bash
/opt/speechllm/.venv/bin/pip freeze > ~/SpeechDelayLLM/deploy/orangepi/requirements-device.txt
```

### M3 — DFPlayer over serial

```bash
sudo -u speechllm /opt/speechllm/.venv/bin/python \
    -m speechllm_device.hardware.dfplayer --folder 1 --track 1 --verbose
```

Pass `--port /dev/ttyUSB0` to try a different port without editing config. Then try track 47 and confirm you hear a *different* phrase — the same phrase both times means the card indexing is wrong.

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

Then the real thing. **Unplug the Ethernet cable** to prove offline operation:

```bash
sudo -u speechllm /opt/speechllm/.venv/bin/python -m speechllm_device --verbose
```

Say "ma" → you should hear a Mama phrase within about three seconds. If it hangs at startup instead, the Whisper weights aren't staged where the service can read them — `doctor.sh` checks exactly that.

**The test that matters most:** say ten things in a row. If the device ever responds to *itself* — a reply immediately triggering another reply with no one speaking — the BUSY pin isn't working. Check the wire to pin 11 and that `DFPLAYER_BUSY_GPIO=256`.

### M6 — Run as a service

```bash
sudo systemctl start speechllm && journalctl -u speechllm -f
```

Reboot and confirm it comes back on its own, then soak it for 30 minutes:

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

Start with `sudo /opt/speechllm/deploy/orangepi/doctor.sh` — it covers most of this table and prints the fix.

| Symptom | Likely cause |
|---|---|
| No boot, red LED only | Wrong image for the board (Phase 0), or a bad flash |
| Pi never gets an IP over the cable | ICS not enabled on the Wi-Fi adapter, or enabled on the wrong adapter |
| `/dev/ttyS5` missing, `FileNotFoundError` | Overlay not enabled, no reboot after enabling, or the wrong overlay name — take it from `ls /boot/dtb/allwinner/overlay/`, it differs between official and Armbian images |
| Serial port exists but nothing works | `dmesg` shows `pinctrl request() failed for pin 226` — the pins are already claimed. Use a USB-TTL adapter |
| `Permission denied` on the serial port | Not in `dialout` (note: that's errno 13, not the errno 2 above) |
| `bad interpreter: /bin/bash^M` | CRLF line endings from a Windows checkout — see `.gitattributes` in Phase 7 |
| `ImportError: cannot import name 'Editops'` | A damaged package survived in the venv. Re-run `install.sh`; it now rebuilds with `venv --clear` |
| `module 'yaml' has no attribute 'dump'` | Same cause as above |
| DFPlayer silent, BUSY toggles | Amp unpowered, or speaker on SPK_1/SPK_2 instead of DAC_R |
| Wrong phrase every time | Stray metadata files on the card shifting indexes |
| Error 0x06 "track not found" | File missing, or queried before the card mounted (~2 s) |
| Module resets mid-phrase | Power brownout — separate supply, add the bulk capacitor |
| Device talks to itself | BUSY pin not wired, or wrong GPIO number |
| Whisper hangs at startup | Models staged under the wrong `HF_HOME` while `HF_HUB_OFFLINE=1` |
| Refuses to start, bank mismatch | `templates.py` changed since the card was burned — re-render, re-copy |
| Random filesystem corruption | Cheap SD card, or the Pi is being browned out by playback |

For anything not here, the service journal is the first place to look:

```bash
journalctl -u speechllm -n 100 --no-pager
```
