# Demo video script (target 2:50)

Judging weights the video at 20% ("how clearly it explains the agent and the tool use") and the agent itself at 30%,
so the video is built around **watching the agents make decisions**. Record at 1080p, terminal font ≥ 16pt.

**Before recording, open in tabs:** the live site · one agent dossier (Ramp) · its neatlogs trace · GitHub commits ·
`prompts/v2/COACH_NOTES.md` · `submission/ENTIRE.md` · the cfo.ai model. Warm the cache once:
`uv run underwrite run "Ramp" --domain ramp.com --chaos 0.2`.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:12 | Live site hero, then click **TRY IT LIVE** | "Underwrite is a team of AI agents that does venture due diligence overnight, and checks its own work, because the theme is agents you'd trust without watching. And anyone can try it." |
| 0:12–0:30 | **Underwrite Live** (https://184-73-13-58.sslip.io): type a company, press RESEARCH IT, the case file opens and the trail starts (speed up 4×; pause on a `CHECK … claim rejected in-loop` line) | "You type a startup, and you watch the agents work in real time: searching, reading, recording facts. Here the checker caught a misquote and sent the agent back to fix it. This runs on AWS, with limits so the free credits last." |
| 0:12–0:45 | Terminal, `underwrite run "Ramp"` (speed up 3×). Pause on `[agent] step N -> web_search(...)`, then a `REJECTED` line and the `self-corrected` line | "The analyst agent decides every move: pull the **Crustdata** record, search, read a page, record a claim. Each claim has to quote its source exactly, and it's checked the instant it's recorded. Here it misquoted, got bounced, and fixed it itself." |
| 0:45–1:05 | Pause on `[skeptic] objection…` and `sending the analyst back` | "Then a skeptic agent attacks the work: 'your traction numbers come from one blog, and you never checked risks.' It sends the analyst back. Nobody told it to look for a congressional investigation into Ramp; it found one because the skeptic pushed." |
| 1:05–1:25 | Dossier page 1 (hover a red circle), page 3 (skeptic rounds, rejected claims) | "The output is an evaluation form like Sequoia's 1977 Apple memo. Every red number links to the exact quote; page three shows the skeptic's objections and what was thrown out." |
| 1:25–1:40 | Terminal: chaos run (`[inject]` → `[recover]`), and the `daily quota exhausted → falling back` lines | "Failures are normal: rate limits, dead models, broken output. It retries, switches models or data sources, and every step is checkpointed, so even a crash resumes mid-investigation." |
| 1:40–1:55 | Terminal `underwrite watch` (`CHANGED …` lines) + an UPDATED card on the site | "Every night a watcher re-checks each company and re-investigates only what changed." |
| 1:55–2:25 | **neatlogs** trace tree → `underwrite coach` output → `COACH_NOTES.md` → `underwrite compare` table | "Every run is a trace in **neatlogs**. The coach agent reads those traces, detections and triage fixes over the neatlogs MCP server, rewrites the agents' prompts, and re-runs a 12-company exam with an answer key. Its new version made the memos far more trustworthy: on companies it never saw, facts right went from 67 to 80 percent and 98 percent of claims were backed by their source. But it answered fewer questions and slipped on the training companies, so the coach **rejected its own change**. That's what you want from something running unattended: it doesn't ship a change just because one number looks good." |
| 2:25–2:38 | `submission/ENTIRE.md` / `entire checkpoint list` / `entire graph checkpoint` | "**Entire** checkpointed every coding session, and its code graph mapped the refactor from pipeline to agents before we touched it." |
| 2:38–2:48 | **cfo.ai** model | "**cfo.ai** turned measured cost per memo into pricing, margins and runway." |
| 2:48–2:50 | Site memo grid | "Underwrite: the diligence team that works while you sleep." |
