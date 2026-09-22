#!/usr/bin/env bash
# Deploy bot.py to the server and restart the systemd service.
#   ./deploy.sh local        -> deploys on this machine (run it on the server)
#   ./deploy.sh              -> deploys over SSH to root@31.59.105.156
#   ./deploy.sh index        -> deploys over SSH to the "index" host in ~/.ssh/config
set -euo pipefail

TARGET="${1:-root@31.59.105.156}"
REMOTE_DIR=/opt/dlbot
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$TARGET" == "local" ]]; then
  run() { bash -c "$1"; }
  copy() { install -m 644 "${@:1:$#-1}" "${@: -1}"; }
else
  run() { ssh "$TARGET" bash -c "'$1'"; }
  copy() { scp "${@:1:$#-1}" "$TARGET:${@: -1}"; }
fi

echo "==> Deploying to $TARGET"

run "mkdir -p $REMOTE_DIR"
copy "$SRC/bot.py" "$SRC/get_token.py" "$SRC/requirements.txt" "$REMOTE_DIR/"

# The repo's dlbot.service holds placeholders, so an existing one on the server
# carries the real tokens and must never be overwritten by it.
if run "test -f /etc/systemd/system/dlbot.service"; then
  echo "==> Keeping existing dlbot.service (has your configured secrets)"
else
  echo "==> Installing dlbot.service — fill in the Environment= values before it will run"
  copy "$SRC/dlbot.service" "/etc/systemd/system/dlbot.service"
fi

run "command -v aria2c >/dev/null && command -v ffmpeg >/dev/null || { apt-get update -q && apt-get install -y -q aria2 ffmpeg; }"
run "pip3 install --break-system-packages -q -r $REMOTE_DIR/requirements.txt"
run "systemctl daemon-reload && systemctl enable --now dlbot && systemctl restart dlbot"
sleep 3
run "systemctl status dlbot --no-pager -l | head -20" || true

echo "==> Done. Logs: journalctl -u dlbot -f"
