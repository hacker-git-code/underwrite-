## Underwrite v0.1.0: first hackathon build

An autonomous due-diligence agent you can leave running overnight. It researches a startup, writes a cited
investment memo, rejects every claim its sources don't support, and flags where sources disagree.

### Highlights

- **Five-agent pipeline**: planner → researcher (Crustdata company record + web search + page fetch) → extractor →
  verifier → writer, with a replanner that runs a second research round for unanswered questions.
- **Verification you can audit**: every claim quotes one source; code checks the quote really exists there; an
  independent judge rules supported / partial / unsupported; cross-source conflicts are flagged; citations to
  unverified claims are stripped.
- **Recovery**: backoff with jitter, model fallback chains across providers, data-source fallbacks, JSON repair,
  per-phase checkpoints with `underwrite resume`, and `--chaos` fault injection to demo it.
- **Paper dossier**: a three-page memo modelled on Sequoia's 1977 Apple evaluation form, as HTML, PDF and PNG.
- **Observability**: every run is a neatlogs trace (agents, tools, prompt templates + versions, costs, recovery log spans).
- **Coach**: reads neatlogs traces, detections and triage fixes over the neatlogs MCP server, rewrites prompts, and
  keeps a new version only if the eval improves (train/test split, 12 companies with hand-checked facts).
- **Unattended mode**: `batch --new-only`, a static GitHub Pages site, and an EC2 nightly runner (`deploy/`).
- **Safety**: SSRF guard on direct fetches, prompt-injection guard, HTML escaping of all model/web text, credit caps
  and a live balance floor, secrets kept out of git (scanned, and redacted in Entire checkpoints).

### Measured on real runs

About 3–5 minutes, ~18 Crustdata credits and ~20k LLM tokens (≈ $0.013 at list price, $0 on free tiers) per memo.

### Try it

```bash
uv sync && cp .env.example .env   # add keys
uv run underwrite doctor
uv run underwrite run "Linear" --domain linear.app --open
```
