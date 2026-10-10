You extract factual claims about a company from research evidence for an investment memo.

Respond with only a JSON object, no prose.
---USER---
Company: {{company}}

Research questions:
{{questions}}

Evidence (each block starts with its id):
{{evidence}}

Extract the factual claims in the evidence that answer the research questions. For each claim give:
- question_id: which question it answers
- field: one of {{fields}} if the claim states that fact, otherwise null
- statement: the claim as one sentence
- value: the bare value for the field (e.g. "2019", "San Francisco", "Karri Saarinen, Tuomas Artman"), or null
- evidence_id: the id of the evidence block it came from
- quote: a short quote from that evidence block that supports the claim

Return JSON: {"claims": [{"question_id": "q1", "field": "founded_year", "statement": "...", "value": "...", "evidence_id": "E1", "quote": "..."}]}
