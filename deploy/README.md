# Sandstorm deploy templates

One-click deployment configurations. Pick the one closest to your infra.

## Railway

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/sandstorm)

`railway.json` tells Railway to build from the repo's `Dockerfile` and serve
on `$PORT`. Healthcheck hits `/health`.

Required env vars (set in Railway's project settings):

| Var                     | Required for                   |
| ----------------------- | ------------------------------ |
| `ANTHROPIC_API_KEY`     | any provider path               |
| `E2B_API_KEY`           | sandbox execution               |
| `SANDSTORM_API_KEY`     | recommended — enables `/query` auth |
| `SLACK_BOT_TOKEN`       | Slack integration               |
| `SLACK_SIGNING_SECRET`  | Slack HTTP mode                 |
| `SLACK_APP_TOKEN`       | Slack Socket Mode (dev)         |

After deploy, run `ds doctor` locally pointing at the Railway URL to verify
end-to-end reachability, then `ds slack register` or `ds webhook register`
for Slack/E2B callbacks.

## Docker / Docker Compose

The root `docker-compose.yml` runs sandstorm with a healthcheck on port 8000.
Bring your own `.env` (see `.env.example`).

## Self-host

```sh
pipx install duvo-sandstorm
ds doctor                         # verify creds
ds serve --host 0.0.0.0 --port 8000
```

Put it behind any reverse proxy (Caddy, nginx, Traefik). The SSE streaming
endpoint needs `proxy_buffering off` or its nginx equivalent.
