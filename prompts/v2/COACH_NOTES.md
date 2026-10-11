# Coach notes: v1 -> v2

Decision: **rejected**  
Baseline eval: `eval-v1-agent-all-20261010-211950/eval.json`  
neatlogs evidence used: whoami, list_detections, triage_list, triage_get x3, search_traces: 'unsupported quote not found in cited source', search_traces: 'invalid JSON repairing fallback'

## Diagnosis
- (The coach's own diagnosis text was lost: its run was interrupted while the v2 eval was running, before these notes are written. The evidence it read and the changes it made are recorded below; the changes are taken from the prompt diff v1 -> v2.)
- Local evidence from the v1 agent eval (train split): 4 wrong facts, 2 rejected claims, 7 unanswered questions.
- Core facts that sit in the Crustdata record (founders, CEO, funding) were sometimes recorded late or not at all, and some numbers came from search snippets or secondary blogs.
- Questions were sometimes marked answered without an accepted claim, and extra questions were added when the budget was nearly spent, which left open questions.
- The verifier and writer sometimes returned JSON that failed validation (verdict labels, fact-sheet types), costing repair calls.

## Changes
### analyst
Record every core fact from company_profile immediately, tagged with its exact field and listing all co-founders; never rely on search snippets or secondary aggregators for key numbers or team details, read the primary page instead; a question can only be marked answered with an accepted claim; add new questions only when budget remains.

_Evidence:_ 4 wrong facts and 7 unanswered questions in the v1 eval; neatlogs triage items and the 'unsupported quote not found in cited source' trace search.

### verifier
The verdict must be exactly one of supported / partial / unsupported, always with a short reason.

_Evidence:_ neatlogs trace search 'invalid JSON repairing fallback'; Judgements validation failures.

### writer
Explicit fact-sheet types in the output example (year as a number, founders as a list of names).

_Evidence:_ MemoOut fact_sheet validation errors and repairs in the v1 traces.

## Result (train split)

| metric | before | after | change |
|---|---|---|---|
| companies | 8 | 8 | +0 |
| completed | 8 | 8 | +0 |
| fact_accuracy | 0.887 | 0.855 | -0.032 |
| fact_precision | 0.982 | 0.946 | -0.036 |
| supported_rate | 0.844 | 0.934 | +0.09 |
| grounded_rate | 1 | 1 | +0 |
| unsupported_per_memo | 0.25 | 0.125 | -0.125 |
| coverage | 0.913 | 0.812 | -0.101 |
| must_coverage | 0.935 | 0.95 | +0.015 |
| conflicts_per_memo | 0.125 | 0.25 | +0.125 |
| invalid_citations_per_memo | 0 | 0 | +0 |
| recoveries | 16 | 29 | +13 |
| usd_per_memo | 0.0625 | 0.0624 | -0.0001 |
| credits_per_memo | 10.75 | 12.25 | +1.5 |
| seconds_per_memo | 395.625 | 188.65 | -207 |

## Result (test split)

| metric | before | after | change |
|---|---|---|---|
| companies | 4 | 4 | +0 |
| completed | 4 | 4 | +0 |
| fact_accuracy | 0.667 | 0.8 | +0.133 |
| fact_precision | 0.909 | 0.923 | +0.014 |
| supported_rate | 0.821 | 0.979 | +0.158 |
| grounded_rate | 1 | 1 | +0 |
| unsupported_per_memo | 0.25 | 0 | -0.25 |
| coverage | 0.9 | 0.85 | -0.05 |
| must_coverage | 1 | 1 | +0 |
| conflicts_per_memo | 0.25 | 0.5 | +0.25 |
| invalid_citations_per_memo | 0 | 0 | +0 |
| recoveries | 11 | 8 | -3 |
| usd_per_memo | 0.0456 | 0.0613 | +0.0157 |
| credits_per_memo | 8 | 12.25 | +4.25 |
| seconds_per_memo | 198.2 | 171.675 | -26.5 |
