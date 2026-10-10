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

## 3. Keeping keys safe

- `.env` is created with `chmod 600` (only the `ubuntu` user can read it) and is git-ignored.
- The instance has no IAM role, so even a compromised process has no AWS credentials to steal; the agent's
  direct page fetcher also refuses non-public addresses such as the instance metadata service.
- SSH is open to your IP only. The deploy key can push to this repository and nothing else.
- When the hackathon is over: **terminate the instance**, delete the deploy key in GitHub, and rotate the API keys.

## 4. Watching it

```bash
tail -f ~/underwrite-nightly.log     # what the last run did
crontab -l                           # the schedule
```

Each night's commit (`nightly: unattended run …`) shows up in the repo history, and the traces in neatlogs.
