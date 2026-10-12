# Demo video (2:10)

Published with the launch quote-tweet (1920×1080, 30 fps, H.264 + AAC, 24 MB; under X's 2:20 upload limit). The
rendered file and thumbnail stay out of git (`submission/underwrite-demo.mp4`, `submission/video-thumbnail.png`).

**How it was made.** Every shot is a real screen recording, nothing mocked up: a headless browser typed "Perplexity"
into Underwrite Live on Oct 12 and filmed the whole 8-minute run, then opened the dossier it wrote; the code, Coach
notes and Entire commit shots are the public GitHub pages. Waiting is sped up and marked with an "N× speed" badge.
The voiceover is AI-generated (Microsoft Edge neural voice), and captions are burned in because X autoplays muted.

The filmed run: 21 claims, 100% supported by their source, 5 misquotes rejected the moment they were recorded (the
agent fixed them in 3 self-corrections), 5 skeptic objections over two rounds, 12 failures recovered (Gemini 503s, a daily-quota fallback), 12
Crustdata credits, 487 s. Dossier: https://184-73-13-58.sslip.io/memo/perplexity/

| Time | On screen | Voiceover |
|---|---|---|
| 0:00 | Underwrite Live, typing "Perplexity" | Okay. So this is Underwrite. You type in any startup, and a team of AI agents does the due diligence an analyst would spend hours on. |
| 0:08 | Case file opens, trail starts (4×) | The problem with research agents? They make stuff up. Confidently. And at 3 a.m., nobody's there to catch it. |
| 0:15 | Agent trail (7×) | So here, the analyst agent picks every move. Pull the Crustdata record. Search. Read a page. Record a fact. But every fact has to quote the exact sentence it came from, and code checks that quote against the source the moment it's recorded. |
| 0:29 | Punch-in: `claim rejected in-loop` (red box) → `self-corrected` (green box) | Watch. It misquoted a source, got bounced, and fixed it itself. |
| 0:34 | Trail (fast) to `judge: 16 supported` | Then an independent judge checks that each quote actually proves the claim. |
| 0:38 | Skeptic objections ("sourced from low-authority SEO blogs") | And then, my favorite part. A skeptic agent reads everything and basically goes: nah. Your traction numbers come from SEO blogs. Go back. |
| 0:48 | Round two (fast) → VERIFIED stamp | So the analyst goes back for round two. Eight minutes later, you get this. |
| 0:53 | Dossier page 1, hovering red source numbers | An evaluation form, styled after Sequoia's 1977 memo on Apple. Every red number is a source. Hover it, and there's the exact quote. |
| 1:02 | Page 2, page 3 appendix | Page two is the memo. Page three is the receipts: every source, every claim it threw out, and the full agent log. |
| 1:10 | Punch-in: `RECOVERED … daily quota exhausted; falling back` | And stuff breaks overnight. Models run out of quota. APIs time out. It falls back, retries, and checkpoints every single step. This one run recovered twelve times, on its own. |
| 1:22 | `coach.py`: neatlogs MCP calls (`list_detections`, `triage_list`, `search_traces`, …) | Now the wild part. Every run is traced in neatlogs. A coach agent reads those traces, detections and suggested fixes, over the neatlogs MCP server. |
| 1:33 | `prompts/v2/COACH_NOTES.md` (Decision: rejected) | It rewrites the agents' prompts, and re-runs a twelve-company exam with an answer key. |
| 1:38 | Held-out results table | On companies it had never seen, facts right went from 67 to 80 percent. Claims backed by their source: 82 to 98. |
| 1:47 | Site scoreboard, REJECTED tags; `decide()` gate | But it answered fewer questions. So the coach rejected its own upgrade. Which is exactly what you want from an agent nobody's watching. |
| 1:54 | Commit e473e38 with its `Entire-Checkpoint:` trailer | Every coding session that built this is checkpointed with Entire, and the live app runs on AWS. |
| 2:00 | Site → TRY IT LIVE → Underwrite Live | It's live right now. Go type in a startup. Link's below. Underwrite. Due diligence that works while you sleep. |
| 2:06 | End card: try-it URL, repo, tools | |
