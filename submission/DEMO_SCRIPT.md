# Demo video script (target 2:45)

Judging weights the video at 20% for "how clearly it explains the agent and the tool use", so every scene shows one
thing, on screen, with a sentence that names it. Record at 1080p, terminal font ≥ 16pt, browser zoom 110%.

**Before recording:** have these open in tabs: the live site, one dossier (Razorpay), the neatlogs trace for that run,
the GitHub repo (commit list), `prompts/v2/COACH_NOTES.md`, and the cfo.ai model. Run the chaos demo once beforehand
so its cache is warm (`uv run underwrite run "Linear" --domain linear.app --chaos 0.3`).

| Time | On screen | Say |
|---|---|---|
| 0:00–0:15 | Live site hero | "A first-pass VC memo takes an analyst hours. Underwrite writes one in four minutes, overnight, while nobody's watching. The hackathon theme is agents you'd trust to run alone, so the whole design is about trust." |
| 0:15–0:40 | Terminal: `underwrite run "Razorpay" …` scrolling (speed up 4×) | "It plans nine diligence questions, pulls Razorpay's record from **Crustdata**, searches and reads the web, extracts claims, and every claim has to quote the exact sentence it came from." |
| 0:40–1:05 | Dossier page 1, then hover a red circle, then page 3 | "The memo is an evaluation form like Sequoia's 1977 Apple memo. Every red number is a source; hover and you see the quote. Page three lists what each source proved, and the claims it threw out." |
| 1:05–1:25 | Terminal: chaos run with `[inject]` and `[recover]` lines highlighted | "Things break. Here I inject failures on purpose: a 429, a timeout, broken JSON. It backs off, switches to another model or data source, repairs the JSON, and finishes. If the machine dies it resumes from the last checkpoint." |
| 1:25–1:50 | **neatlogs**: the trace's span tree, a prompt version, a recovery log span | "Every run is a trace in **neatlogs**: each agent, tool call, prompt version, token cost and every recovery. That's not just for me." |
| 1:50–2:15 | Terminal `underwrite coach`, then `COACH_NOTES.md`, then `underwrite compare v1 v2` table | "The Coach agent reads those traces, detections and triage fixes through the neatlogs MCP server, rewrites the prompts, re-runs the 12-company exam, and keeps the change only if the score goes up. Here: fact accuracy went from X to Y on held-out companies." *(fill in real numbers)* |
| 2:15–2:30 | GitHub commit with `Entire-Checkpoint:` trailer, then `entire checkpoint explain <id>` | "**Entire** checkpointed every coding session that built this, linked to its commit, with secrets redacted." |
| 2:30–2:40 | **cfo.ai** model: unit economics + runway chart | "And **cfo.ai** turned the measured cost, about 38 cents a memo, into pricing, margins and runway." |
| 2:40–2:45 | Live site memo grid | "Underwrite. It does the reading while you sleep. Link's in the repo." |

## Shots to capture separately (for posts, too)

- 4× sped-up terminal GIF of a full run
- PNG of a dossier's page 1 (toolbar button "Download page 1 (PNG)")
- The before/after table
- The neatlogs trace tree
