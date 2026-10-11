#!/usr/bin/env bash
# Underwrite Live on this EC2 instance: the public web app behind Caddy, with automatic HTTPS.
# Run after setup.sh, as the 'ubuntu' user:   bash ~/underwrite/deploy/web.sh
# The instance's security group must allow inbound HTTP (80) and HTTPS (443) from anywhere.
# No domain needed: the address is <public-ip-with-dashes>.sslip.io (set UW_HOST to use your own domain).
set -euo pipefail

APP="$HOME/underwrite"
IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
HOST="${UW_HOST:-${IP//./-}.sslip.io}"
PROMPTS="${UW_PROMPTS:-$(grep -E '^UW_PROMPTS=' "$APP/.env" 2>/dev/null | cut -d= -f2 || true)}"
PROMPTS="${PROMPTS:-v1}"

# Caddy: reverse proxy that gets and renews a Let's Encrypt certificate by itself.
if ! command -v caddy >/dev/null; then
  sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y caddy
fi
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$HOST {
	encode gzip
	reverse_proxy 127.0.0.1:8080 {
		flush_interval -1
	}
}
EOF
sudo systemctl reload caddy || sudo systemctl restart caddy

# The app as a service: starts on boot, restarts if it crashes; queued jobs resume from their checkpoints.
sudo tee /etc/systemd/system/underwrite-web.service >/dev/null <<EOF
[Unit]
Description=Underwrite Live
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=UW_PROMPTS=$PROMPTS
ExecStart=$HOME/.local/bin/uv run underwrite serve --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now underwrite-web
sudo systemctl restart underwrite-web

echo
echo "Underwrite Live is starting at:  https://$HOST"
echo "(the HTTPS certificate takes up to a minute the first time)"
echo "Logs:  journalctl -u underwrite-web -f"
