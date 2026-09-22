#!/usr/bin/env bash
# Deploy bot.py to the server and restart the systemd service.
#   ./deploy.sh              -> deploys to root@31.59.105.156
#   ./deploy.sh index        -> deploys to the "index" host from ~/.ssh/config
set -euo pipefail

TARGET="${1:-root@31.59.105.156}"
REMOTE_DIR=/opt/dlbot
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Deploying to $TARGET"

ssh "$TARGET" "mkdir -p $REMOTE_DIR"
scp "$SRC/bot.py" "$SRC/get_token.py" "$SRC/requirements.txt" "$TARGET:$REMOTE_DIR/"

# The repo's dlbot.service holds placeholders, so an existing one on the server
# carries the real tokens and must never be overwritten by it.
if ssh "$TARGET" "test -f /etc/systemd/system/dlbot.service"; then
  echo "==> Keeping existing dlbot.service (has your configured secrets)"
else
  echo "==> Installing dlbot.service — fill in the Environment= values before it will run"
  scp "$SRC/dlbot.service" "$TARGET:/etc/systemd/system/dlbot.service"
fi

ssh "$TARGET" bash -s <<REMOTE
set -euo pipefail
command -v aria2c >/dev/null || { apt-get update -q && apt-get install -y -q aria2; }
pip3 install --break-system-packages -q -r $REMOTE_DIR/requirements.txt
systemctl daemon-reload
systemctl enable --now dlbot
systemctl restart dlbot
sleep 3
systemctl status dlbot --no-pager -l | head -20
REMOTE

echo "==> Done. Logs: ssh $TARGET journalctl -u dlbot -f"
