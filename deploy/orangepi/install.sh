#!/usr/bin/env bash
#
# SpeechLLM — Orange Pi Zero 3 installer
#
# Run on the device, from a checkout of this repo:
#
#     sudo ./deploy/orangepi/install.sh
#
# Installs to /opt/speechllm, creates a service user, and enables the systemd
# unit. Idempotent: the virtualenv is rebuilt from scratch every run, so a
# half-finished earlier install cannot poison this one.
#
# What it deliberately does NOT do:
#   * enable the UART5 overlay — that needs orangepi-config and a reboot
#   * copy the phrase bank to the DFPlayer's SD card — that card is not
#     readable by the Pi; render on a laptop and copy there
#
set -euo pipefail

PREFIX=/opt/speechllm
SERVICE_USER=speechllm
CONFIG_DIR=/etc/speechllm
LOG_DIR=/var/log/speechllm
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

log()  { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run with sudo."

# ── Sanity checks ────────────────────────────────────────────
log "Checking the board"
ARCH="$(uname -m)"
[[ "$ARCH" == "aarch64" ]] || warn "Architecture is $ARCH, expected aarch64."
printf '  kernel:  %s\n' "$(uname -r)"
printf '  memory:  %s\n' "$(free -h | awk '/^Mem:/ {print $2}')"

# Any hardware UART, plus USB-serial adapters, which are the zero-config way to
# talk to the DFPlayer if the device-tree overlay fights back.
mapfile -t SERIAL_PORTS < <(ls /dev/ttyS[0-9]* /dev/ttyUSB[0-9]* 2>/dev/null || true)
if [[ ${#SERIAL_PORTS[@]} -eq 0 ]]; then
    warn "No serial ports found — the DFPlayer will not work."
    warn "Run deploy/orangepi/doctor.sh after this finishes; it explains how to fix it."
else
    printf '  serial:  %s\n' "${SERIAL_PORTS[*]}"
fi

# This install needs the network; everything after it runs offline. Check now
# rather than dying half way through a 100 MB download.
if ! getent hosts pypi.org >/dev/null 2>&1; then
    warn "Cannot resolve pypi.org — DNS is down. The install will fail partway."
    warn "  routing:  ping -c2 1.1.1.1"
    warn "  dns:      cat /etc/resolv.conf"
    warn "  fix:      sudo resolvectl dns \$(ip route show default | awk '{print \$5; exit}') 1.1.1.1 8.8.8.8"
    die "Fix networking, then re-run. Nothing has been changed."
fi

# ── System packages ──────────────────────────────────────────
log "Installing system packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3-venv python3-dev build-essential \
    libportaudio2 portaudio19-dev libsndfile1 \
    alsa-utils ffmpeg python3-libgpiod

# ── Service user ─────────────────────────────────────────────
log "Creating the $SERVICE_USER user"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/speechllm \
            --shell /usr/sbin/nologin "$SERVICE_USER"
fi
# Some Orange Pi BSP images ship a `gpio` group and some do not. Create it if
# missing rather than tolerating its absence: without group access to the GPIO
# character device the BUSY pin falls back to a mock, and mic gating degrades
# from a hardware signal to a guess.
getent group gpio >/dev/null || groupadd --system gpio
for group in audio dialout gpio; do
    usermod -aG "$group" "$SERVICE_USER"
done

# ── Files ────────────────────────────────────────────────────
log "Installing to $PREFIX"
mkdir -p "$PREFIX" "$CONFIG_DIR" "$LOG_DIR" "$PREFIX/models/hf"
# --delete keeps a re-run from leaving files behind from an older layout.
rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
    --exclude '.ruff_cache' --exclude '.pytest_cache' --exclude '*.egg-info' \
    --exclude 'logs' --exclude 'samples' \
    "$REPO_DIR/" "$PREFIX/"

# ── Python environment ───────────────────────────────────────
# --clear is load-bearing. Without it, `python3 -m venv` reuses an existing
# site-packages, pip reports damaged packages as "already satisfied", and a
# single failed install stays broken forever. That is exactly how a corrupt
# rapidfuzz and PyYAML survived several re-runs of this script.
log "Building the virtualenv (from scratch)"
python3 -m venv --clear "$PREFIX/.venv"
"$PREFIX/.venv/bin/pip" install --quiet --upgrade pip setuptools wheel

# libgpiod ships as an apt package (python3-libgpiod), which an isolated venv
# cannot see — so the "preferred" GPIO backend could never load and the code
# silently fell back to sysfs. Link it in. The PyPI `gpiod` package is not a
# substitute: it needs libgpiod 2.x and Jammy ships 1.6.
GPIOD_SRC="$(/usr/bin/python3 -c 'import gpiod, sys; sys.stdout.write(gpiod.__file__)' 2>/dev/null || true)"
if [[ -n "$GPIOD_SRC" && -e "$GPIOD_SRC" ]]; then
    SITE_PACKAGES="$("$PREFIX/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    # A package installs as .../gpiod/__init__.py; a plain extension as gpiod*.so.
    if [[ "$(basename "$GPIOD_SRC")" == "__init__.py" ]]; then
        GPIOD_SRC="$(dirname "$GPIOD_SRC")"
    fi
    ln -sfn "$GPIOD_SRC" "$SITE_PACKAGES/$(basename "$GPIOD_SRC")"
    echo "  linked gpiod → $SITE_PACKAGES"
else
    warn "python3-libgpiod not importable; the BUSY pin will use the sysfs backend."
fi

if [[ -f "$REPO_DIR/deploy/orangepi/requirements-device.txt" ]]; then
    log "Installing pinned aarch64 dependencies"
    "$PREFIX/.venv/bin/pip" install -r "$REPO_DIR/deploy/orangepi/requirements-device.txt"
else
    warn "No requirements-device.txt — resolving unpinned (Milestone 0 should pin these)."
fi
# --no-build-isolation is deliberate. Without it pip builds each editable
# install in a throwaway environment and re-downloads setuptools from PyPI,
# so installing our own pure-Python packages needs working DNS — and fails
# with "Could not find a version that satisfies setuptools>=68" the moment the
# network blinks. setuptools and wheel are already in the venv from above.
log "Installing the SpeechLLM packages"
"$PREFIX/.venv/bin/pip" install --quiet --no-build-isolation -e "$PREFIX/packages/speechllm-core"
"$PREFIX/.venv/bin/pip" install --quiet --no-build-isolation -e "$PREFIX/packages/speechllm-device"

# ── Models ───────────────────────────────────────────────────
# HF_HOME must match device.env, or the model is cached somewhere the service
# cannot reach: this runs as root, the service runs as speechllm with
# HF_HUB_OFFLINE=1 and ProtectHome=true. Getting this wrong fails at Milestone 5
# with an offline cache miss, long after the install looked successful.
log "Staging models"
HF_HOME="$PREFIX/models/hf" "$PREFIX/.venv/bin/python" "$PREFIX/setup_models.py" || \
    warn "Model staging failed. With no network, copy models/ across from your laptop."

# ── Configuration ────────────────────────────────────────────
log "Installing configuration"
if [[ ! -f "$CONFIG_DIR/device.env" ]]; then
    install -m 0644 "$REPO_DIR/deploy/orangepi/device.env" "$CONFIG_DIR/device.env"
    echo "  wrote $CONFIG_DIR/device.env"
else
    echo "  keeping existing $CONFIG_DIR/device.env"
    echo "  (compare against deploy/orangepi/device.env for new settings)"
fi

if [[ -f "$REPO_DIR/deploy/orangepi/asound.conf" ]]; then
    install -m 0644 "$REPO_DIR/deploy/orangepi/asound.conf" /etc/asound.conf
fi

# GPIO access for the DFPlayer BUSY line. Without this the service runs but
# falls back to timing playback from manifest durations, and the microphone
# can reopen while the speaker is still talking.
if [[ -f "$REPO_DIR/deploy/orangepi/99-speechllm-gpio.rules" ]]; then
    install -m 0644 "$REPO_DIR/deploy/orangepi/99-speechllm-gpio.rules" \
        /etc/udev/rules.d/99-speechllm-gpio.rules
    udevadm control --reload-rules && udevadm trigger --subsystem-match=gpio || \
        warn "udev reload failed; a reboot will apply the GPIO rules."
    echo "  installed GPIO udev rules"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX" "$LOG_DIR"

# ── Service ──────────────────────────────────────────────────
log "Installing the systemd unit"
install -m 0644 "$REPO_DIR/deploy/orangepi/speechllm.service" \
    /etc/systemd/system/speechllm.service
systemctl daemon-reload
systemctl enable speechllm.service

# ── Preflight ────────────────────────────────────────────────
log "Verifying the phrase bank"
if ! sudo -u "$SERVICE_USER" "$PREFIX/.venv/bin/python" "$PREFIX/tools/verify_bank.py"; then
    warn "Phrase bank check failed — render it on your laptop and re-sync assets/bank/."
fi

cat <<EOF

$(log "Installed")

  Check everything at once:
       sudo $PREFIX/deploy/orangepi/doctor.sh

  Then, in order:

    1. Confirm the microphone is visible:
         sudo -u $SERVICE_USER $PREFIX/.venv/bin/python -m speechllm_device --list-devices
       Then set AUDIO_INPUT_DEVICE in $CONFIG_DIR/device.env

    2. Smoke-test the DFPlayer (needs the SD card in the module):
         sudo -u $SERVICE_USER $PREFIX/.venv/bin/python \\
             -m speechllm_device.hardware.dfplayer --folder 1 --track 1

    3. Benchmark before trusting the latency budget:
         sudo -u $SERVICE_USER $PREFIX/.venv/bin/python $PREFIX/tools/bench_device.py

    4. Try a full run in the foreground:
         sudo -u $SERVICE_USER $PREFIX/.venv/bin/python -m speechllm_device --verbose

    5. Start the service:
         sudo systemctl start speechllm
         journalctl -u speechllm -f

EOF
