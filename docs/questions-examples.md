# Example questions

Run `agents/answer.py` over these to produce `output/agent_usage.json` (see
[04-serve.md](04-serve.md)). They are illustrative, not the held-out set — the ten
questions used for grading are different from these, but drawn from the same kind of
thing a researcher would actually ask.

A few are deliberately outside what the dataset can support. An honest `null` on those
is the correct answer, not a bug.

```
Which manager held the largest Apple position in 2026 Q2?
Which manager added the most Nvidia shares between 2026 Q1 and 2026 Q2?
How many distinct issuers did Renaissance Technologies LLC report in 2026 Q2?
What was the total reported value of Citadel Advisors LLC's holdings in 2026 Q1?
Which managers in the roster filed a 13F-NT instead of a 13F-HR for 2026 Q2?
Did Pershing Square Capital Management report any Microsoft holdings directly in 2026 Q2?
Which manager reported the most call options in 2026 Q2?
What was Third Point LLC's largest position by value in 2026 Q1, and what was it?
Which manager held Tesla in both 2026 Q1 and 2026 Q2, and did the position grow or shrink?
What was the average portfolio value across all managers in 2026 Q3?
```

The last one is out of scope on purpose — 2026 Q3 is not in this dataset. It should come
back `null` with a reason on stderr, not a guess built from Q1/Q2 data.

Run:

```bash
python -m agents.answer "Which manager held the largest Apple position in 2026 Q2?"
```

for each, and write the aggregated token/call counts to `output/agent_usage.json` per
the shape in [04-serve.md](04-serve.md#45--scalable).
