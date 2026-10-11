# Underwrite: business plan (inputs for cfo.ai)

This is the plan we model in cfo.ai. Numbers marked **measured** come from real runs (`runs/*/state.json`,
`runs/eval-*/eval.json`). Numbers marked **assumption** are ours to defend and are the levers to play with in cfo.ai.

## The product

A due-diligence analyst that runs unattended: a watchlist of startups goes in, cited and verified first-pass memos
come out every morning, as a web page and a PDF dossier. Buyers: angel investors, micro-VCs and seed funds, accelerator
selection teams, and corp-dev / M&A teams screening targets.

**Why they pay:** a first-pass memo costs an analyst 2–4 hours (at $60–120/hour fully loaded that is $120–480 per
company). Underwrite produces one in about 4 minutes, with every fact sourced and checked, for well under $1 of cost.

## Unit economics per memo

Measured on the 12-company agent eval (`runs/eval-v1-agent-all-20261010-211950/eval.json`), the agent version:

| Item | Value | Source |
|---|---|---|
| Crustdata credits per memo | ~10 | **measured** (9.83 average: company record, web searches, page fetches, minus cache hits) |
| Price per Crustdata credit | $0.02 | **assumption**: Crustdata doesn't publish a self-serve rate; replace with the rate on your plan |
| Data cost per memo | ~$0.20 | 10 × $0.02 |
| LLM cost per memo (paid list price) | ~$0.057 | **measured** (0.0569 average) at paid-tier list prices; $0 on the free tiers we ran on |
| Compute per memo | ~$0.003 | t3.small at $0.0208/h, ~5.5 min per memo |
| **Total cost per memo** | **~$0.26** | |
| Time per memo | ~5.5 min | **measured** (330 s average) |
| Facts correct vs answer key | 81.5% | **measured** (fact accuracy; 96% precision, 0 invalid citations) |

## Pricing (assumption)

| Plan | Price | Includes | Cost to serve | Gross margin |
|---|---|---|---|---|
| Angel | $49 / month | 25 memos, PDF export | 25 × $0.26 = $6.50 | ~87% |
| Fund | $399 / month | 300 memos, nightly watchlist, 5 seats, Slack digest | 300 × $0.26 = $78 | ~80% |
| Enterprise | from $2,000 / month | custom sources, private deployment, SSO, SLA | ~$500 | ~75% |
| Overage | $1.50 / memo | | $0.26 | ~83% |

## Fixed monthly costs (assumption)

| Item | Month 1–6 | Month 7–12 |
|---|---|---|
| Hosting (EC2 + storage + backups) | $60 | $250 |
| Tooling (neatlogs Pro, GitHub, email, domain) | $150 | $300 |
| Founder salary | $0 (bootstrapped) | $4,000 |
| First hire (engineer, from month 7) | – | $6,000 |
| Marketing | $300 | $1,500 |
| **Total** | **~$510** | **~$12,050** |

## Revenue scenario (assumption, to stress-test in cfo.ai)

| Month | Angel | Fund | Enterprise | MRR |
|---|---|---|---|---|
| 1 | 5 | 0 | 0 | $245 |
| 3 | 25 | 3 | 0 | $2,422 |
| 6 | 60 | 10 | 1 | $8,930 |
| 9 | 110 | 22 | 2 | $18,168 |
| 12 | 160 | 35 | 4 | $29,805 |

Starting cash: $5,000 (founder) + $10,000 assumed pre-seed/grant in month 6.

## Questions to ask Ari (cfo.ai)

Paste these after entering the numbers above:

1. "Build a 12-month model from these plans, costs and the revenue scenario. Show MRR, gross margin, burn and ending cash per month."
2. "What is my runway if growth is 50% slower than the scenario? At what month do I run out of cash?"
3. "What is the break-even month, and how many Fund customers do I need to cover the month-7 hire?"
4. "If Crustdata costs $0.05 per credit instead of $0.02 (data cost $0.50 per memo), how do gross margin and break-even change?"
5. "Should the Angel plan be $49 or $79? Compare 12-month revenue assuming 30% fewer Angel signups at $79."

Export or screenshot the model, the runway chart and Ari's answers into `business/` for the submission.

> Remember: the hackathon's cfo.ai access needs a card. Cancel the subscription right after signup in
> **Settings → Billing** so nothing is charged.
