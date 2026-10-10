#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 EC2 instance (t3.small, us-east-1, Hackathon_VPC).
# Run as the default 'ubuntu' user:  bash setup.sh
# The instance needs NO IAM role and NO inbound ports except SSH from your own IP:
# it only calls outbound APIs and pushes the website to GitHub with a repo-scoped deploy key.
set -euo pipefail

REPO_SSH="git@github.com:hacker-git-code/underwrite-.git"
APP="$HOME/underwrite"

sudo apt-get update -y
sudo apt-get install -y git curl ca-certificates fonts-dejavu

# Headless Chrome, used only to print memo dossiers to PDF.
if ! command -v google-chrome >/dev/null; then
  curl -fsSLo /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y /tmp/chrome.deb
fi

# uv: Python toolchain + locked dependencies.
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Deploy key: write access to this one repository only (not your GitHub account).
mkdir -p ~/.ssh && chmod 700 ~/.ssh
if [ ! -f ~/.ssh/underwrite_deploy ]; then
  ssh-keygen -t ed25519 -N "" -f ~/.ssh/underwrite_deploy -C "underwrite-ec2"
  echo
  echo "Add this PUBLIC key in GitHub: repo Settings -> Deploy keys -> Add deploy key -> tick 'Allow write access':"
  echo
  cat ~/.ssh/underwrite_deploy.pub
  echo
  read -rp "Press Enter once the key is added... "
fi
cat > ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/underwrite_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null

[ -d "$APP" ] || git clone "$REPO_SSH" "$APP"
cd "$APP"
uv sync
git config user.name "underwrite-bot"
git config user.email "underwrite-bot@users.noreply.github.com"
chmod +x deploy/nightly.sh

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo
  echo "Now put your keys in $APP/.env  (nano .env, then Ctrl+O, Enter, Ctrl+X)."
fi

# Every night at 20:30 UTC = 02:00 IST.
( crontab -l 2>/dev/null | grep -v underwrite-nightly ; \
  echo "30 20 * * * $APP/deploy/nightly.sh >> $HOME/underwrite-nightly.log 2>&1 # underwrite-nightly" ) | crontab -

echo
echo "Setup done. Check keys with:   cd $APP && uv run underwrite doctor"
echo "Run the nightly job once now:  $APP/deploy/nightly.sh"
