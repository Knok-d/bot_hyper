#!/usr/bin/env bash
# Bootstrap script for installing the Hyperliquid tracker bot on a fresh VPS.
# Tested on Ubuntu 22.04 / 24.04 and Debian 12.
#
# Run as root:   bash install.sh
# It will:
#   1. Create the 'bot' system user
#   2. Install Python 3.11+ and venv
#   3. Clone/copy project to /opt/bot_hyper
#   4. Create virtualenv and install requirements
#   5. Install + enable the systemd service
#
# Before running: copy the project tree to /tmp/bot_hyper or set $SRC.

set -euo pipefail

SRC="${SRC:-/tmp/bot_hyper}"
DEST="/opt/bot_hyper"
SERVICE_NAME="bot_hyper"

if [[ "$EUID" -ne 0 ]]; then
    echo "Run as root (sudo bash install.sh)"
    exit 1
fi

echo "==> Installing system packages"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip ca-certificates

if ! id -u bot >/dev/null 2>&1; then
    echo "==> Creating user 'bot'"
    useradd --system --create-home --shell /usr/sbin/nologin bot
fi

echo "==> Syncing project to $DEST"
mkdir -p "$DEST"
if [[ -d "$SRC" ]]; then
    rsync -a --delete \
        --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
        --exclude 'bot.log' --exclude '.git' \
        "$SRC"/ "$DEST"/
else
    echo "Source dir $SRC not found. Copy project there first, e.g.:"
    echo "  scp -r ./bot_hyper root@HOST:/tmp/"
    exit 1
fi

echo "==> Creating virtualenv"
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --upgrade pip wheel
"$DEST/.venv/bin/pip" install -r "$DEST/requirements.txt"

echo "==> Setting ownership"
chown -R bot:bot "$DEST"
chmod 600 "$DEST/.env" 2>/dev/null || true

echo "==> Installing systemd unit"
cp "$DEST/deploy/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"

echo "==> Done. Check status:"
echo "    systemctl status ${SERVICE_NAME}"
echo "    journalctl -u ${SERVICE_NAME} -f"
