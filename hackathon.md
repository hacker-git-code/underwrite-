# neatHack 2026 — Underwrite

## Project

**Underwrite** — an autonomous due-diligence agent you can leave running overnight.
Give it a list of startups; it plans the research, pulls company data from Crustdata,
searches and reads the web, extracts every factual claim with a source, has an
independent verifier check each claim against the source text, flags contradictions
(e.g. "website says 50 people, Crustdata says 18"), and writes a cited investment memo.

A **Coach** loop reads the agent's own neatlogs traces, detections and triage fixes
over the neatlogs MCP server, patches the agent's prompts/tools, re-runs the eval set,
and only keeps a change if the numbers improve.

- Challenge: "Build agents you'd trust to run without you watching." (single track)
- Required tools: neatlogs (tracing + Coach loop), Entire (checkpointed build sessions), cfo.ai (business plan)

## Team

- Rehan Momin

## Stack

- Python 3.12, uv
- LLM: OpenAI-compatible client → Google Gemini free tier (primary), Groq free tier (fallback); Bedrock-ready
- Data: Crustdata (company enrich, web search, web fetch)
- Observability: neatlogs Python SDK + neatlogs MCP (Coach)
- Build provenance: Entire CLI (checkpoints on every commit)

## Build log

### 2026-10-10

- Read hackathon page, neatlogs SDK/MCP docs, Entire CLI README, Crustdata API docs.
- Chose idea: due-diligence agent + self-improving Coach loop.
- Installed Entire CLI 0.11.4, `git init`, `entire enable --agent claude-code`.

## Demo

- pending

## Evidence checklist (from the hackathon page)

- [ ] Before/after run comparison with numbers
- [ ] neatlogs trace links / screenshots
- [ ] Entire checkpoints from the repo
- [ ] cfo.ai business plan (pricing, costs, revenue, runway)
- [ ] A run where an action failed and the agent recovered
- [ ] Public posts tagged #neatHack
- [ ] Public repo with commits dated during the hackathon

## Limitations & next steps

- pending

## Submission status

- Not submitted. Submissions open Mon 12 Oct, 7:00–11:55 PM IST (quote-tweet the official neatlogs post).
