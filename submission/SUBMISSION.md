# neatHack submission kit (Mon 12 Oct, 7:00–11:55 PM IST)

Both steps are required: **quote-tweet the official @neatlogs launch post** (tagging @neatlogs, @EntireHQ and
@arithecfo) **and** fill in the form. The first 50 quote-tweets get engagement, so post first, then fill in the form.

## 1. The quote-tweet

Attach `submission/underwrite-demo.mp4` (2:10, 1080p, under X's 2:20 limit) to the quote-tweet itself; native video
autoplays in the timeline, links to YouTube don't. Text and thread: [POSTS.md](POSTS.md#launch-quote-tweet).

## 2. Form answers

**Team name:** Underwrite (Rehan Momin, solo)

**Project name:** Underwrite

**One-liner:** AI agents that do venture due diligence unattended: every fact quotes its source, a skeptic sends the
analyst back, and a coach improves the agents from their own neatlogs traces.

**Project description:**

> Research agents make things up, and an agent you leave running overnight has nobody watching to catch it.
> Underwrite is a team of agents that does first-pass venture due diligence on any startup and checks its own work.
> An analyst agent decides every move (pull the Crustdata company record, search the web, read a page, record a
> fact). Every fact must quote the exact sentence it came from; code checks the quote against the source the moment
> it is recorded, and bounces it back to the agent if it isn't there. An independent judge checks that each quote
> proves its claim, disagreements between sources are flagged, and a skeptic agent attacks the result and sends the
> analyst back until the evidence holds. The output is a three-page dossier modelled on Sequoia's 1977 Apple memo,
> where every red number links to its quote. Model outages, quota limits and crashes are recovered from
> automatically (every step is checkpointed). A coach agent reads the agents' neatlogs traces, detections and triage
> fixes over the neatlogs MCP server, rewrites their prompts and re-runs a 12-company exam with an answer key: on
> unseen companies it raised facts right from 67% to 80% and source-backed claims from 82% to 98%, but answered fewer
> questions, so its own gate rejected the change. Anyone can try it live, free, on AWS.

**How we used the sponsor tools:**

- **neatlogs:** every run is a trace (workflow, agent, tool, guardrail and LLM spans, prompt templates and versions,
  recovery log spans). The Coach reads traces, detections and triage fixes over the neatlogs MCP server to decide how
  to rewrite the prompts (`underwrite/coach.py`, `prompts/v2/COACH_NOTES.md`).
- **Entire:** every coding session that built the repo is checkpointed and tied to its commit (`Entire-Checkpoint:`
  trailers, refs pushed to GitHub); entire-graph mapped the pipeline-to-agent refactor (`submission/ENTIRE.md`).
- **cfo.ai:** the business plan's inputs for Ari: pricing, unit costs measured from real runs (~$0.26 a memo),
  revenue scenarios and runway questions (`business/PLAN.md`).
- **Crustdata** (company records, web search, page fetch) and **AWS EC2** (the public live app).

**GitHub repo:** https://github.com/hacker-git-code/underwrite-

**Live demo (try it):** https://184-73-13-58.sslip.io

**Website (memo gallery + scoreboard):** https://hacker-git-code.github.io/underwrite-/

**Demo video:** the X post's video link, or an unlisted YouTube upload of `submission/underwrite-demo.mp4`
(thumbnail: `submission/video-thumbnail.png`)

**Quote-tweet link:** paste the URL of your quote-tweet

## 3. Before you hit post

- [ ] Open https://184-73-13-58.sslip.io once: the app is up and "agents are free".
- [ ] The quote-tweet is a **quote** of the official @neatlogs launch post (not a reply, not a new post).
- [ ] It tags **@neatlogs @EntireHQ @arithecfo** and has the video attached.
- [ ] Post the thread replies under your own quote-tweet.
- [ ] Form submitted with the quote-tweet URL.
- [ ] Add the quote-tweet and video links to `hackathon.md`.
