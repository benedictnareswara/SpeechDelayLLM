#!/usr/bin/env bash
#
# SpeechLLM — Orange Pi Zero 3 installer
#
# Run on the device, from a checkout of this repo:
#
#     sudo ./deploy/orangepi/install.sh
#
# Installs to /opt/speechllm, creates a service user, and enables the systemd
# unit. Idempotent: safe to re-run after pulling changes.
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

if [[ ! -e /dev/ttyS5 ]]; then
    warn "/dev/ttyS5 not found — the DFPlayer will not work."
    warn "Enable it:  sudo orangepi-config → System → Hardware → ph-uart5 → reboot"
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
# gpio group is created by the Orange Pi BSP; tolerate its absence.
for group in audio dialout gpio; do
    getent group "$group" >/dev/null && usermod -aG "$group" "$SERVICE_USER"
done

# ── Files ────────────────────────────────────────────────────
log "Installing to $PREFIX"
mkdir -p "$PREFIX" "$CONFIG_DIR" "$LOG_DIR" "$PREFIX/models/hf"
# --delete keeps a re-run from leaving files behind from an older layout.
rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
    --exclude 'logs' --exclude 'samples' \
    "$REPO_DIR/" "$PREFIX/"

# ── Python environment ───────────────────────────────────────
log "Building the virtualenv"
python3 -m venv "$PREFIX/.venv"
"$PREFIX/.venv/bin/pip" install --quiet --upgrade pip setuptools wheel

if [[ -f "$REPO_DIR/deploy/orangepi/requirements-device.txt" ]]; then
    log "Installing pinned aarch64 dependencies"
    "$PREFIX/.venv/bin/pip" install -r "$REPO_DIR/deploy/orangepi/requirements-device.txt"
else
    warn "No requirements-device.txt — resolving unpinned (Milestone 0 should pin these)."
fi
"$PREFIX/.venv/bin/pip" install --quiet -e "$PREFIX/packages/speechllm-core"
"$PREFIX/.venv/bin/pip" install --quiet -e "$PREFIX/packages/speechllm-device"

# ── Models ───────────────────────────────────────────────────
log "Staging models"
if [[ ! -f "$PREFIX/models/silero_vad.onnx" ]]; then
    "$PREFIX/.venv/bin/python" "$PREFIX/setup_models.py" || \
        warn "Model download failed. With no network, copy models/ from your laptop."
else
    echo "  silero_vad.onnx already present"
fi

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

  Next steps:

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
