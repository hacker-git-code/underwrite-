# Build-in-public posts (#neatHack)

"Building in public" is 15% of judging. Post on X (and LinkedIn if you like), tag the tools, add the link to each post
in `hackathon.md`. Tag the official neatlogs, Entire, cfo.ai and Crustdata accounts (check their handles on X). Never show your `.env` or API keys in a screenshot.

## 1. Day 1, kickoff (attach: memo page 1 PNG)
> Building **Underwrite** for #neatHack: an AI due-diligence analyst you can leave running overnight.
> Give it a list of startups → it researches each one and fills in a VC evaluation form like Sequoia's famous 1977 Apple memo. Every fact links to the sentence it came from.
> Using neatlogs for traces, Entire for checkpoints, Crustdata for company data.

## 2. Day 1, trust (attach: dossier page 3, rejected claims)
> The scariest thing about leaving an agent alone: it makes stuff up.
> Underwrite makes every claim quote its source, checks in code that the quote actually exists, then an independent judge checks it supports the claim. Anything that fails is crossed out in red, never in the memo. #neatHack

## 3. Day 2, recovery (attach: terminal GIF with [inject]/[recover] lines)
> Chaos mode: I inject 429s, timeouts and broken JSON on purpose.
> The agent backs off, switches model or data source, repairs the JSON, and finishes the memo. Crash it mid-run and `underwrite resume` picks up from the last checkpoint. #neatHack neatlogs

## 4. Day 2, self-improvement (attach: the README results table or COACH_NOTES.md)
> The agent that improves itself: a Coach reads Underwrite's own neatlogs traces + detections over MCP, rewrites its prompts and re-runs a 12-company exam with an answer key.
> v2 on companies it never saw: facts right 67% → 80%, claims backed by their source 82% → 98%. But it answered fewer questions, so the Coach rejected its own change. An agent that won't ship a change just because one number looks good. #neatHack

## 4b. Day 2, try it yourself (attach: screen recording of the live trail)
> You can now ask Underwrite's agents to research any startup from your browser and watch them work live: searching, quoting, getting caught misquoting and fixing it, a skeptic pushing back. Free (2 a day), running on AWS.
> https://184-73-13-58.sslip.io #neatHack

## 5. Day 3, it runs while I sleep (attach: screenshot of nightly commits / site)
> Underwrite now runs every night at 2am on an AWS EC2 box: researches 3 new startups, publishes the memos, pushes to GitHub. No one watching.
> Live: https://hacker-git-code.github.io/underwrite-/ · code: https://github.com/hacker-git-code/underwrite- #neatHack

## Launch quote-tweet

Submission night (Mon Oct 12, 7:00–11:55 PM IST). **Quote-tweet the official @neatlogs launch post** with this text
and attach `submission/underwrite-demo.mp4` as native video. Every post below is within X's 280-character limit
(links count as 23; the main post is 279, so if X says it's too long, change `try it ↓` to `try it:`).

**Main post (the quote-tweet, video attached):**

```text
i built AI agents that do VC due diligence while you sleep.

every fact must quote its source. a skeptic sends them back. a coach read their traces, rewrote their prompts, then rejected its own upgrade.

try it ↓
https://184-73-13-58.sslip.io

@neatlogs @EntireHQ @arithecfo #neatHack
```

**Reply 1 (attach: the dossier screenshot, `submission/video-thumbnail.png`):**

```text
how it works 🧵

→ an analyst agent picks every move: Crustdata record, search, read a page, record a fact
→ each fact must quote its source; code checks the quote instantly
→ a separate judge checks the quote proves it
→ a skeptic sends it back until the evidence holds
```

**Reply 2:**

```text
you get a 3-page dossier styled after Sequoia's 1977 Apple memo. every red number links the exact quote; page 3 is the receipts.

the run in the video: Perplexity, 8 min, 21 claims, 100% source-backed, 12 failures recovered on its own.
```

**Reply 3 (attach: screenshot of the scoreboard with the REJECTED tags, or `prompts/v2/COACH_NOTES.md`):**

```text
my favorite part: a coach agent reads their @neatlogs traces, detections and triage over MCP, rewrites the prompts, re-runs a 12-company exam.

unseen companies: facts right 67%→80%, source-backed claims 82%→98%.

but it answered fewer questions, so it rejected its own change.
```

**Reply 4:**

```text
built solo in 3 days for #neatHack. every coding session is checkpointed with @EntireHQ.

code: https://github.com/hacker-git-code/underwrite-
memos + scoreboard: https://hacker-git-code.github.io/underwrite-/

go make it research your favorite startup 👀
```

Every number above is real: the Perplexity run is the one filmed for the video (Underwrite Live, Oct 12), and the
Coach numbers are the held-out split in `prompts/v2/COACH_NOTES.md`.
