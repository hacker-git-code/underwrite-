# neatHack 2026 — Underwrite

## Project

**Underwrite** — an autonomous due-diligence agent you can leave running overnight.
Give it a list of startups; it plans the research, pulls company data from Crustdata,
searches and reads the web, extracts every factual claim with a source, has an
independent verifier check each claim against the source text, flags contradictions
(e.g. "website says 50 people, Crustdata says 18"), and writes a cited investment memo
as a three-page paper dossier (HTML, PDF, PNG).

A **Coach** loop reads the agent's own neatlogs traces, detections and triage fixes
over the neatlogs MCP server, rewrites the agent's prompts, re-runs the eval set,
and only keeps a change if the numbers improve.

- Challenge: "Build agents you'd trust to run without you watching." (single track)
- Required tools: neatlogs (tracing + Coach loop), Entire (checkpointed build sessions), cfo.ai (business plan)
- Repo: https://github.com/hacker-git-code/underwrite-
- Live site: https://hacker-git-code.github.io/underwrite-/
- Try it (public web app on AWS EC2): https://184-73-13-58.sslip.io

## Team

- Rehan Momin (solo)

## Stack

- Python 3.12, uv
- LLMs (free tiers): Gemini 3.8 Flash / 3.5 Flash / 3.5 Flash-Lite / 3.1 Flash-Lite, Groq gpt-oss-120b / 20b;
  Claude on Bedrock supported but not used (the AWS allowance covers EC2/Lambda only)
- Data: Crustdata (company enrich, web search, web fetch, credit balance)
- Observability: neatlogs Python SDK + neatlogs MCP (Coach)
- Build provenance: Entire CLI (checkpoints on every commit, secrets redacted)
- Hosting: GitHub Pages (site) + AWS EC2 t3.small (nightly runner)

## Build log

### 2026-10-10

- Read hackathon page, neatlogs SDK/MCP docs, Entire CLI README, Crustdata API docs.
- Chose idea: due-diligence agent + self-improving Coach loop.
- Installed Entire CLI 0.11.4, `git init`, `entire enable --agent claude-code`.
- Built v0 (commit `5b0a6b0`): planner → researcher → extractor → verifier → replanner → writer; checkpointed
  state machine with `resume`; chaos mode; eval harness (12 companies, train/test split); Coach over neatlogs MCP.
- Found the AWS check-in page only approves EC2/Lambda/IAM/LB, not Bedrock → switched LLMs to free Gemini + Groq
  behind a provider fallback chain (commit `56d3dc2`). Gemini 2.5 models are closed to new keys → Gemini 3.x defaults.
- First real run (Razorpay): accurate but thin; found the search budget was spent on 4 of 8 questions. Fixed with
  breadth-first queries + 2 searches reserved for the gap round (commit `ab59efd`). Re-run: 9/9 topics, 12 claims, 92% supported.
- Crustdata record was 4,291 lines (mostly executives' employment history) → curated 34-line summary.
- Memo redesigned as a paper dossier modelled on Sequoia's 1977 Apple evaluation form (commit `e06539d`).
- Security pass: SSRF guard, prompt-injection guard, HTML escaping, credit cap + live balance floor, model cooldowns;
  scanned git history, tracked files and Entire checkpoints for key values: none found (Entire redacts secrets).
- Pushed to GitHub; added website (`docs/`), EC2 nightly runner (`deploy/`), business plan, demo script, post drafts.
- v1 baseline eval running (12 companies).
- Tests: `tests/test_offline.py` 6/6 pass (pipeline, resume after crash, chaos recovery, fact scoring, SSRF, HTML escaping).

### 2026-10-11

- Agent mode (analyst tool loop + skeptic review), watch mode, model-chain waits; agent v1 eval on all 12 companies.
- Coach v1 -> v2 from neatlogs traces/detections/triage over MCP + eval failures: held-out facts right 66.7% -> 80.0%,
  supported by source 82% -> 98%, but coverage 91% -> 83% and train accuracy dipped, so its gate rejected v2
  (`prompts/v2/COACH_NOTES.md`). v1 stays in production.
- Underwrite Live: public web app (`underwrite serve`) on an AWS EC2 t3.small behind Caddy/HTTPS; anyone can type a
  company and watch the agents work. First public-style run: Vercel, 16/16 claims verified, 8 skeptic objections, 5.6 min.

## Demo

- Script: `submission/DEMO_SCRIPT.md` (video pending)

## Evidence checklist (from the hackathon page)

- [x] Before/after run comparison with numbers — README "Results" + `prompts/v2/COACH_NOTES.md`
- [x] neatlogs trace links / screenshots — trace ids printed per run and in each dossier appendix
- [x] Entire checkpoints from the repo — `Entire-Checkpoint:` trailers, refs pushed to GitHub
- [ ] cfo.ai business plan (pricing, costs, revenue, runway) — inputs ready in `business/PLAN.md`
- [x] A run where an action failed and the agent recovered — `[recover]` events in every real run so far
  (Crustdata ConnectError → retry, empty pages → direct fetch, malformed JSON → repair, Gemini 503 → retry)
- [ ] Public posts tagged #neatHack — drafts in `submission/POSTS.md`
- [x] Public repo with commits dated during the hackathon

## Limitations & next steps

- Ground truth covers stable facts only; judgement quality isn't auto-scored.
- Free-tier LLM quotas limit batch size per day.

## Submission status

- Not submitted. Submissions open Mon 12 Oct, 7:00–11:55 PM IST (quote-tweet the official neatlogs post).
