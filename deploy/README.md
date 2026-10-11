# Running Underwrite unattended on AWS EC2

The website on GitHub Pages is static. A small EC2 instance runs the agent every night, adds the new memos to
`docs/`, and pushes. Nobody has to be watching: that is the point.

**Cost:** a t3.small is about $0.02/hour (~$0.50/day) plus ~$0.05/day for a 20 GB disk. Running it for the whole
hackathon and judging week costs a few dollars of the $25 allowance. Stop it when you're done.

## 1. Launch the instance (AWS console, logged in with the hackathon IAM user)

1. Region **US East (N. Virginia) us-east-1** (top-right).
2. EC2 → **Launch instance**:
   - Name: `underwrite-runner`
   - AMI: **Ubuntu Server 24.04 LTS**
   - Instance type: **t3.small** (allowed: t2/t3/t3a, nano to large)
   - Key pair: create one (`underwrite-key`, .pem) and keep the file private
   - Network: **Hackathon_VPC**, any public subnet, **auto-assign public IP: enable**
   - Security group: inbound **SSH (22) from My IP only**. Nothing else.
   - Storage: 20 GB gp3 (limit is 50 GB)
   - No IAM instance profile is needed.
3. Launch. Only **one instance per IAM user** is allowed; terminate an old one before launching another.

## 2. Connect and set up

EC2 → your instance → **Connect** → **EC2 Instance Connect** → Connect (opens a terminal in the browser). Then:

```bash
curl -fsSLO https://raw.githubusercontent.com/hacker-git-code/underwrite-/main/deploy/setup.sh
bash setup.sh
```

The script prints an SSH **public** key. Add it in GitHub → this repo → **Settings → Deploy keys → Add deploy key**,
tick **Allow write access**, save, and press Enter in the terminal. (A deploy key can only push to this one repo.)

Then put your keys on the server:

```bash
cd ~/underwrite && nano .env      # paste GEMINI_API_KEY, GROQ_API_KEY, CRUSTDATA_API_KEY, NEATLOGS_API_KEY
uv run underwrite doctor          # every line should say ok / key set
~/underwrite/deploy/nightly.sh    # first run now; afterwards it runs every night at 02:00 IST
```

## 2b. Underwrite Live: let anyone use it from their browser

The same instance can host the public web app (type a company, watch the agents work, get the dossier). It needs
the web ports open: EC2 → your instance → **Security** tab → the security group → **Edit inbound rules** → add
**HTTP (80)** and **HTTPS (443)** from **Anywhere-IPv4**. Then, in the instance terminal:

```bash
cd ~/underwrite && git pull && uv sync
bash deploy/web.sh                 # prints the address, e.g. https://3-80-1-2.sslip.io
```

`deploy/web.sh` installs Caddy (automatic HTTPS from Let's Encrypt, no domain needed thanks to sslip.io) and runs
`underwrite serve` as a systemd service that restarts on crashes and reboots; a job that was running resumes from
its checkpoint. Free-use limits, all in `.env`: `UW_WEB_PER_VISITOR` (default 2 new memos per visitor per day),
`UW_WEB_DAILY_CAP` (25 per day for the whole site), `UW_WEB_MAX_QUEUE` (8), plus the Crustdata balance floor
`UW_MIN_CREDIT_BALANCE`. Companies researched in the last 30 days open instantly and cost nothing.

## 3. Keeping keys safe

- `.env` is created with `chmod 600` (only the `ubuntu` user can read it) and is git-ignored.
- The instance has no IAM role, so even a compromised process has no AWS credentials to steal; the agent's
  direct page fetcher also refuses non-public addresses such as the instance metadata service.
- SSH is open to your IP only. The deploy key can push to this repository and nothing else.
- The web app never sends a key to the browser. Visitors are counted by a salted hash of their IP (no raw IPs are
  stored), and it only listens on 127.0.0.1 behind Caddy.
- When the hackathon is over: **terminate the instance**, delete the deploy key in GitHub, and rotate the API keys.

## 4. Watching it

```bash
tail -f ~/underwrite-nightly.log     # what the last run did
crontab -l                           # the schedule
```

Each night's commit (`nightly: unattended run …`) shows up in the repo history, and the traces in neatlogs.
