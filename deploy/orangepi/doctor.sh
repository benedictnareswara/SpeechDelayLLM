#!/usr/bin/env bash
#
# SpeechLLM — diagnose an Orange Pi install
#
#     sudo /opt/speechllm/deploy/orangepi/doctor.sh
#
# Every check that fails prints the command that fixes it. Read-only: this
# script never changes the system.
#
set -uo pipefail   # deliberately no -e; a failing check must not abort the run

PREFIX=/opt/speechllm
CONFIG=/etc/speechllm/device.env
VENV="$PREFIX/.venv/bin/python"

PASS=0; FAIL=0; WARN=0

section() { printf '\n\033[1;34m── %s ─────────────────────────────\033[0m\n' "$*"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  \033[1;31m✗\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
soft() { printf '  \033[1;33m!\033[0m %s\n' "$*"; WARN=$((WARN+1)); }
fix()  { printf '      \033[2m→ %s\033[0m\n' "$*"; }

# device.env drives most of the checks below.
if [[ -f "$CONFIG" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$CONFIG"; set +a
fi
DFPLAYER_PORT="${DFPLAYER_PORT:-/dev/ttyS5}"
DFPLAYER_BUSY_GPIO="${DFPLAYER_BUSY_GPIO:-256}"
AUDIO_INPUT_DEVICE="${AUDIO_INPUT_DEVICE:-}"
HF_HOME="${HF_HOME:-$PREFIX/models/hf}"

# ── Board ────────────────────────────────────────────────────
section "Board"
printf '  model:   %s\n' "$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo unknown)"
printf '  kernel:  %s\n' "$(uname -r)"
printf '  arch:    %s\n' "$(uname -m)"

case "$(uname -r)" in
    6.1.*) ok "kernel 6.1.x — the Zero 3 (H618) BSP line" ;;
    5.4.*) soft "kernel 5.4.x is the older H616/H6 line, not the Zero 3 BSP"
           fix "if the UART checks below fail, reflash with an Ubuntu Jammy linux6.1.x image" ;;
    *)     soft "unrecognized kernel line; UART overlays may differ from the docs" ;;
esac

# ── Serial / UART ────────────────────────────────────────────
section "Serial port for the DFPlayer"

OVERLAY_DIR=/boot/dtb/allwinner/overlay
if [[ -d "$OVERLAY_DIR" ]]; then
    UART_OVERLAYS="$(ls "$OVERLAY_DIR" 2>/dev/null | grep -i uart | tr '\n' ' ')"
    if [[ -n "$UART_OVERLAYS" ]]; then
        ok "UART overlays shipped by this image: $UART_OVERLAYS"
    else
        bad "no UART overlays in $OVERLAY_DIR — this image cannot enable UART5"
        fix "reflash with the Zero 3 Ubuntu Jammy linux6.1.x image, or use a USB-TTL adapter"
    fi
else
    soft "$OVERLAY_DIR not found"
fi

ENVFILE=/boot/orangepiEnv.txt
if [[ -f "$ENVFILE" ]]; then
    if grep -qE '^overlays=.*uart5' "$ENVFILE"; then
        ok "$ENVFILE enables a uart5 overlay: $(grep -E '^overlays=' "$ENVFILE")"
    else
        bad "$ENVFILE does not enable a uart5 overlay"
        fix "sudo orangepi-config → System → Hardware → enable the uart5 overlay → reboot"
        fix "or add these two lines to $ENVFILE and reboot:"
        fix "    overlay_prefix=sun50i-h616"
        fix "    overlays=${UART_OVERLAYS:+$(printf '%s' "$UART_OVERLAYS" | tr ' ' '\n' | sed -n 's/^sun50i-h616-\(.*uart5.*\)\.dtbo$/\1/p' | head -1)}"
        fix "(the name above is read from your own overlay dir — do not copy it from a guide)"
    fi
fi

mapfile -t PORTS < <(ls /dev/ttyS[0-9]* /dev/ttyUSB[0-9]* 2>/dev/null)
if [[ ${#PORTS[@]} -gt 0 ]]; then
    ok "serial ports present: ${PORTS[*]}"
else
    bad "no serial ports at all"
fi

if [[ -e "$DFPLAYER_PORT" ]]; then
    ok "DFPLAYER_PORT=$DFPLAYER_PORT exists"

    # A node existing proves NOTHING. The 8250 driver creates /dev/ttyS0..N for
    # every UART slot the SoC could have; without the device-tree overlay there
    # is no hardware behind it and the first tcgetattr() returns EIO:
    #     termios.error: (5, 'Input/output error')
    # /proc/tty/driver/serial is the ground truth — a real port reports a UART
    # type and an mmio address, an unconfigured one reports "uart:unknown".
    if [[ "$DFPLAYER_PORT" == *ttyS* ]]; then
        PORT_NUM="${DFPLAYER_PORT##*ttyS}"
        SERIAL_INFO="$(awk -v n="${PORT_NUM}:" '$1 == n' /proc/tty/driver/serial 2>/dev/null)"
        if [[ -z "$SERIAL_INFO" ]]; then
            soft "could not read /proc/tty/driver/serial (run this script with sudo)"
        elif [[ "$SERIAL_INFO" == *uart:unknown* ]]; then
            bad "$DFPLAYER_PORT has NO hardware behind it: $SERIAL_INFO"
            fix "the node exists but the overlay is not loaded — enabling it is still required"
            fix "check:  grep -E '^(overlay_prefix|overlays)=' /boot/orangepiEnv.txt"
            fix "then reboot, and confirm with: dmesg | grep -i ttyS"
        else
            ok "$DFPLAYER_PORT is backed by real hardware: $SERIAL_INFO"
        fi
    fi

    if sudo -u speechllm test -r "$DFPLAYER_PORT" && sudo -u speechllm test -w "$DFPLAYER_PORT"; then
        ok "the speechllm user can read/write it"
    else
        bad "the speechllm user cannot open $DFPLAYER_PORT"
        fix "sudo usermod -aG dialout speechllm && sudo systemctl restart speechllm"
    fi
else
    bad "DFPLAYER_PORT=$DFPLAYER_PORT does not exist"
    if [[ ${#PORTS[@]} -gt 0 ]]; then
        fix "available instead: ${PORTS[*]} — set DFPLAYER_PORT in $CONFIG"
    fi
    fix "or plug in a USB-TTL adapter and use /dev/ttyUSB0 (no device-tree work needed)"
fi

# An overlay can load and still leave the UART dead: on H616/H618 the pins may
# already be claimed. Pin 226 is PH2, the TX pin this project uses.
PINCTRL_ERR="$(dmesg 2>/dev/null | grep -i 'pinctrl.*request() failed' | tail -3)"
if [[ -n "$PINCTRL_ERR" ]]; then
    bad "the kernel refused to hand out UART pins:"
    printf '      %s\n' "$PINCTRL_ERR"
    fix "another overlay or peripheral owns those pins; disable it, or use a USB-TTL adapter"
else
    ok "no pinctrl allocation errors in dmesg"
fi

# ── Python environment ───────────────────────────────────────
section "Virtualenv"
if [[ -x "$VENV" ]]; then
    ok "interpreter at $VENV"
    for mod in yaml numpy onnxruntime faster_whisper serial soxr sounddevice speechllm_core speechllm_device; do
        if ERRMSG="$("$VENV" -c "import $mod" 2>&1)"; then
            ok "import $mod"
        else
            bad "import $mod — $(echo "$ERRMSG" | tail -1)"
            fix "sudo $PREFIX/deploy/orangepi/install.sh   (rebuilds the venv from scratch)"
        fi
    done
else
    bad "no virtualenv at $VENV"
    fix "sudo $PREFIX/deploy/orangepi/install.sh"
fi

# ── GPIO (DFPlayer BUSY line) ────────────────────────────────
section "BUSY pin (GPIO $DFPLAYER_BUSY_GPIO / PI0 / physical pin 11)"
if "$VENV" -c "import gpiod" 2>/dev/null; then
    ok "libgpiod available inside the venv (preferred backend)"
elif [[ -d /sys/class/gpio ]]; then
    soft "libgpiod not in the venv; falling back to the sysfs backend"
    fix "re-run install.sh — it links the apt python3-libgpiod into the venv"
else
    bad "neither libgpiod nor sysfs GPIO is available"
    fix "playback will be timed from manifest durations instead of the BUSY line"
fi

# ── Audio input ──────────────────────────────────────────────
section "Microphone"
if CARDS="$(arecord -l 2>/dev/null)" && [[ -n "$CARDS" ]]; then
    printf '%s\n' "$CARDS" | sed 's/^/  /'
    if [[ -n "$AUDIO_INPUT_DEVICE" ]]; then
        if printf '%s' "$CARDS" | grep -qi -- "$AUDIO_INPUT_DEVICE"; then
            ok "AUDIO_INPUT_DEVICE='$AUDIO_INPUT_DEVICE' matches a capture device"
        else
            bad "AUDIO_INPUT_DEVICE='$AUDIO_INPUT_DEVICE' matches nothing above"
            fix "sudo -u speechllm $VENV -m speechllm_device --list-devices"
            fix "then set AUDIO_INPUT_DEVICE in $CONFIG"
        fi
    else
        soft "AUDIO_INPUT_DEVICE is unset — capture will use the ALSA default"
    fi
else
    bad "arecord found no capture devices"
    fix "check the USB microphone is seated, then: lsusb && arecord -l"
fi

# ── Models ───────────────────────────────────────────────────
section "Models"
SILERO="${VAD_MODEL_PATH:-$PREFIX/models/silero_vad.onnx}"
if [[ -s "$SILERO" ]]; then
    ok "Silero VAD at $SILERO ($(du -h "$SILERO" | cut -f1))"
else
    bad "Silero VAD missing at $SILERO"
    fix "sudo -u speechllm HF_HOME=$HF_HOME $VENV $PREFIX/setup_models.py"
fi

if [[ -d "$HF_HOME" ]] && find "$HF_HOME" -name '*.bin' -o -name '*.safetensors' 2>/dev/null | grep -q .; then
    ok "Whisper weights staged in $HF_HOME"
else
    bad "no Whisper weights in HF_HOME=$HF_HOME"
    fix "the device sets HF_HUB_OFFLINE=1, so this will NOT self-heal on first use"
    fix "while the Pi still has network: sudo -u speechllm HF_HOME=$HF_HOME $VENV $PREFIX/setup_models.py"
fi

# ── Phrase bank ──────────────────────────────────────────────
section "Phrase bank"
if [[ -x "$VENV" ]] && "$VENV" "$PREFIX/tools/verify_bank.py" >/dev/null 2>&1; then
    ok "manifest agrees with templates.py"
else
    bad "phrase bank check failed"
    fix "$VENV $PREFIX/tools/verify_bank.py     (shows the specific mismatch)"
    fix "if templates.py changed: re-render on your laptop and re-burn the DFPlayer card"
fi

# ── Service ──────────────────────────────────────────────────
section "Service"
if systemctl list-unit-files speechllm.service >/dev/null 2>&1; then
    STATE="$(systemctl is-active speechllm 2>/dev/null || true)"
    ENABLED="$(systemctl is-enabled speechllm 2>/dev/null || true)"
    ok "unit installed (enabled=$ENABLED, active=$STATE)"
    if [[ "$STATE" == "failed" ]]; then
        bad "the service is in a failed state"
        fix "journalctl -u speechllm -n 50 --no-pager"
    fi
else
    bad "speechllm.service is not installed"
    fix "sudo $PREFIX/deploy/orangepi/install.sh"
fi

# ── Summary ──────────────────────────────────────────────────
printf '\n\033[1m%d passed, %d warnings, %d failed\033[0m\n' "$PASS" "$WARN" "$FAIL"
[[ $FAIL -eq 0 ]] && printf '\033[1;32mReady.\033[0m\n'
exit $(( FAIL > 0 ? 1 : 0 ))
