Below are {{COUNT}} property news candidates from the last 7 days (id, title, source, date, snippet).

TASK
Pick the {{N}} stories that would make the best Instagram posts for Rumah123 this week.

SELECTION CRITERIA
- Relevant to Indonesian home buyers, first-time buyers or KPR borrowers (age 25-40).
- Contains at least one concrete, checkable fact (a number, a rule change, a date).
- Prefer official or established sources (Bank Indonesia, OJK, ministries, major business media).
- Pick DIFFERENT angles. Aim for: (1) a market data update, (2) a practical KPR/finance education angle, (3) an engagement-friendly angle (a this-or-that style dilemma).
- Skip: pure corporate PR, promos from a single bank, paywalled items with no usable snippet, anything about competitors, anything where the snippet is too thin to extract a fact.

FOR EACH PICK return
- "id": the candidate id
- "format": "carousel" or "single"
- "angle": one sentence on the angle in Bahasa Indonesia
- "facts": 2-5 short factual statements copied or closely paraphrased from the snippet ONLY. Keep every number exactly as written. Do not add anything from your own knowledge.

If fewer than {{N}} candidates have enough substance, return fewer picks. Never pad with weak stories.

CANDIDATES
{{CANDIDATES}}

Return JSON only:
{"picks": [{"id": 0, "format": "carousel", "angle": "...", "facts": ["..."]}]}
