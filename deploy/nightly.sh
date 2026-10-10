#!/usr/bin/env bash
# The unattended job: research the next few companies on the watchlist, rebuild the website,
# and publish it. Safe to re-run: finished companies are skipped, unfinished ones resume.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.."

echo "=== nightly run $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
git pull --rebase --autostash
uv sync --quiet

# 3 new companies a night keeps Crustdata use around 60 credits/night.
uv run underwrite batch deploy/watchlist.txt --new-only --limit "${UW_NIGHTLY_LIMIT:-3}"
uv run underwrite site

git add docs runs
if git diff --cached --quiet; then
  echo "nothing new to publish"
else
  git commit -m "nightly: unattended run $(date -u +%Y-%m-%dT%H:%MZ)"
  git push
fi
