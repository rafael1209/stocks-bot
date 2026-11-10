#!/usr/bin/env bash
# Ship the bot to the host and (re)start it.
#
#   ./deploy/deploy.sh            # code + rebuild + restart
#   ./deploy/deploy.sh --first    # also copy .env, today's state and the nginx vhost
#
# state/ and charts/ live on the host (bind mounts), so a redeploy keeps today's alerts
# and never re-sends them.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${STOCKS_HOST:?set STOCKS_HOST=root@<your-server-ip>}"
DIR="${STOCKS_DIR:-/root/stocks-bot}"

echo "→ packing the working tree"
tar czf - --exclude='./dashboard/node_modules' --exclude='./dashboard/dist' --exclude='./state' \
  --exclude='./charts' --exclude='./.env' --exclude='./web.env' --exclude='*/__pycache__' --exclude='./__pycache__' \
  --exclude='./.pytest_cache' --exclude='./backtest_log*' . |
  ssh "$HOST" "mkdir -p $DIR/state $DIR/charts && tar xzf - -C $DIR"

if [ "${1:-}" = "--first" ]; then
  echo "→ secrets, state and nginx vhost"
  scp -q .env "$HOST:$DIR/.env" && ssh "$HOST" "chmod 600 $DIR/.env"
  [ -d state ] && tar czf - state | ssh "$HOST" "tar xzf - -C $DIR"
  ssh "$HOST" "cp $DIR/deploy/stocks.chasman.net.conf /root/nginx-conf/stocks.chasman.net.conf \
    && docker exec nginx nginx -t && docker exec nginx nginx -s reload"
fi

echo "→ building and restarting"
ssh "$HOST" "cd $DIR && docker compose up -d --build"

echo "→ health (the new bot process must write a fresh status, not an old copied one)"
for attempt in $(seq 1 18); do
  if ssh "$HOST" "docker exec stocks-web python -c \"
import urllib.request, json, sys
s = json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/health'))
fresh = s.get('alive') and s.get('seconds_since_update', 999) < 90 and s.get('scans', 0) >= 1
print('bot alive:', s.get('alive'), '| scans:', s.get('scans'), '| updated', s.get('seconds_since_update'), 's ago')
sys.exit(0 if fresh else 1)\"" && ssh "$HOST" "docker inspect -f '{{.State.Running}} {{.RestartCount}}' stocks-bot | grep -q '^true 0$'"; then
    break
  fi
  [ "$attempt" = 18 ] && { echo "health check failed"; ssh "$HOST" "docker logs --tail 30 stocks-bot"; exit 1; }
  sleep 10
done
echo "live: https://stocks.chasman.net (PIN login)"
