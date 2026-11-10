# Deployment

Live at **https://stocks.chasman.net** (host `<your-server-ip>`), behind its own PIN login.

## Shape

```
Cloudflare (proxied, Full-Strict)
        │
   nginx container  ── /root/nginx-conf/stocks.chasman.net.conf
        │  shared-network
   stocks-web       ── dashboard_api.py on :8787 (React app + JSON + live bars, PIN login)
   stocks-bot       ── main.py: scanner, setups, Telegram alerts
        │
   /root/stocks-bot/state, charts   (bind mounts: today's alerts survive redeploys)
   /root/stocks-bot/.env            (Telegram token, chmod 600, never in the image)
   /root/stocks-bot/web.env         (PIN hash + session key only, chmod 600)
```

Same pattern as `game.chasman.net`: the origin uses the Cloudflare Origin Certificate
in `/etc/nginx/conf.d/certs/`, and nginx resolves the container name per request.

## Redeploy

```bash
./deploy/deploy.sh            # pack → build on host → restart → health check
./deploy/deploy.sh --first    # also copies .env, state/ and the nginx vhost
```

Changing a rule = edit `config.yaml`, then `./deploy/deploy.sh`.

## PIN

Set or change it on the host (the PIN is typed there and only its hash is stored):

```bash
ssh -t root@<your-server-ip> "cd /root/stocks-bot && python3 set_pin.py && docker compose up -d web"
```

5 wrong tries from one address lock it for 15 minutes; 30 wrong tries in an hour lock
everyone for the rest of that hour. Changing the PIN logs out every browser.

## Operating it

```bash
ssh root@<your-server-ip> 'docker logs -f stocks-bot'
ssh root@<your-server-ip> 'docker restart stocks-bot'
ssh root@<your-server-ip> 'docker exec nginx nginx -t && docker exec nginx nginx -s reload'
```

Run only one bot at a time (server **or** this computer) – two would send every alert twice.
