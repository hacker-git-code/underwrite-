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

## Submission (Mon Oct 12, 7:00–11:55 PM IST)
Quote the official neatlogs post with:
> **Team:** Rehan Momin (solo) · **Project:** Underwrite: an autonomous due-diligence agent that verifies every claim and improves itself from its neatlogs traces · **Try it:** https://184-73-13-58.sslip.io · **Repo:** https://github.com/hacker-git-code/underwrite- · **Site:** https://hacker-git-code.github.io/underwrite-/ · **Demo:** <video link> #neatHack
