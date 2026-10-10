# How Entire was used to build Underwrite

Underwrite was built with a coding agent (Claude Code) inside an Entire-enabled repository, from the first commit.

## 1. Every coding session is checkpointed and tied to its commit

`entire enable --agent claude-code` installed Entire's hooks before any code was written. Every commit since carries an
`Entire-Checkpoint:` trailer, and the prompts, transcript and metadata of the session that produced it are stored as a git
ref (`refs/entire/checkpoints/<shard>/<id>`), pushed to GitHub with the code. Secrets are redacted before storage: we
scanned all checkpoint blobs for our real API key values and found none (and 8–18 redaction markers per checkpoint).

```text
$ entire checkpoint list
  branch       main
  checkpoints  10

● 01M4K8CZ4C9NY7AD7HTPG2Q9DH  feat: watch mode (detect changes, re-investigate only what changed) …
  10-10 21:25 (e2a3dcb)
● 01M4K7SZB7WK210FHF4PG7VZCG  feat: agent mode: analyst tool loop + skeptic review (pipeline kept as baseline)
  10-10 21:14 (e473e38)
● 01M4JHTCFHBY6B7Q1J59S8GQBY  feat: eval --resume finishes an interrupted eval run …
  10-10 14:50 (b0aa1e5)
● 01M4JGPDW65VMH0FPPVVY38WB2  docs: build log + v0.1.0 release notes
● 01M4JGM2YFTVRTGQMCG7ZZPXZ7  docs+site+deploy: detailed README, GitHub Pages site, EC2 nightly runner …
● 01M4JFDGBJFKW3Y01PWNBVAHEJ  feat: paper-dossier memo (evaluation form + typed memo + appendix …) ; security hardening
● 01M4JE7YX1W334MJWM9SDF0CKB  chore: keep raw run state (copied web page text) out of git
  …
```

Try it in a clone: `entire checkpoint list`, `entire checkpoint explain <id>`, `entire why <file>:<line>`.

## 2. entire-graph guided the biggest refactor

The biggest change of the hackathon was turning a fixed pipeline into an agent (analyst tool loop + skeptic). We installed
the official **entire-graph** plugin (`entire plugin install graph`), indexed the repo (68 files, 491 symbols, 1,584
relations), and installed its coding-agent guide (`entire graph init-agents` → `CLAUDE.md`, `AGENTS.md`), so the coding
agent searched the graph before touching code:

```text
$ entire graph search --repo . --profile full --query "pipeline state machine that runs researcher extractor verifier per company"
  1. underwrite/pipeline.py:77  _run          (the per-company state machine to extend)
  2. underwrite/pipeline.py:126 run_company
  3. underwrite/models.py:101   CompanyState  (43 usages in 12 files)

$ entire graph impact --repo . --symbol research
  Blast radius: 0 callers, 5 callees (_host, _add, _search, _fetch, emit), 4 type consumers, 5 co-change files
```

That told us the research helpers (`_search`, `_fetch`, `_add`) could be reused as the agent's tools unchanged, and that
`CompanyState` changes ripple into 12 files, so new state fields were added with defaults (old runs stay loadable).

## 3. entire-graph reviewed the result, per checkpoint

```text
$ entire graph checkpoint 01M4K7SZB7WK210FHF4PG7VZCG     # the "agent mode" commit
underwrite/agents/analyst.py (Python)
  + class Toolbox added
  + method Toolbox.t_company_profile / t_web_search / t_read_page / t_record_claim /
           t_update_question / t_add_question / t_finish added
  + function _compact added
  + function investigate added
underwrite/agents/skeptic.py (Python)
  + function review added
  + function as_tasks added
underwrite/agents/verifier.py (Python)
  + function ground added
  ~ function check_grounding body changed (1 dependent)
underwrite/llm.py (Python)
  + function _run_chain / _for_provider / _call_tools / chat added
  ~ function complete body changed (6 dependents)
underwrite/models.py (Python)
  + class Objection, Review added
  ~ class CompanyState body changed (35 dependents)
underwrite/pipeline.py (Python)
  + function _step_agent added
  ~ function run_company signature changed (5 dependents)
tests/test_offline.py (Python)
  + function test_agent_mode_end_to_end / test_agent_finish_refused_while_priority_questions_open /
             test_context_compaction added
```

The dependents counts are what we checked against before keeping the change: `complete` (6 dependents) kept its
signature; `CompanyState` (35 dependents) only gained defaulted fields; and the 9 offline tests passed.
