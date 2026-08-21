# The Challenge

**DSRS Data Curator Challenge** · Data Science Intern screening

A researcher has come to DataHub with a list of twenty investment managers. She wants to
study how their equity positions moved over the last two quarters, and she needs the
holdings in a form she can work with.

Nobody has built that dataset. You are going to.

**Deadline:** Monday, August 24, 2026, 11:59 AM US Central
**Effort:** roughly 10–12 hours. We grade quality, not hours spent.
**Questions:** dsrs@business.illinois.edu. We usually reply within a few hours, and
within a day at the outside. Do not wait on us — make your best judgment call, record it
in `submission/ASSUMPTIONS.md`, and keep working. A documented assumption is worth more
than a stalled submission.

---

## The chapters

Five, all open from day one. The pace is yours, though they are ordered the way the work
flows — you cannot structure data you have not fetched.

| | | Points | Produces |
|---|---|---|---|
| 1 | [Source](01-source.md) | 5 | `output/filers.csv`, `output/filings/` |
| 2 | [Interrogate](02-interrogate.md) | 5 | `submission/eda.py` |
| 3 | [Structure](03-structure.md) | 5 | `output/filings.parquet`, `output/holdings.parquet` |
| 4 | [Serve](04-serve.md) | 10 | `agents/answer.py`, `output/agent_usage.json` |
| 5 | [Show](05-show.md) | 5 | video link in `submission/SUBMISSION.md` |
| | **Core total** | **30** | |

Chapters 1 to 3 build the dataset; 4 makes it answerable; 5 is how you explain it.

### Optional

| | Points | |
|---|---|---|
| [Bonus 1 · Notice attribution](bonus-01-notice-attribution.md) | 5 | recover holdings reported inside another manager's filing |
| [Bonus 2 · CUSIP validation](bonus-02-cusip-validation.md) | 5 | check reported identifiers against SEC's official list |

Attempt these only once the core is complete. They are extra credit on a finished
submission, not a substitute for one, and they are independent of each other.

**Maximum: 40 points.**

---

## Also read

**[SCHEMA.md](SCHEMA.md)** — the expected output schema. Your Parquet files must match it
exactly: column names, types, and nullability as written. Chapter 3 is graded against it
directly.

---

## How grading works

Every submission is evaluated identically.

**Automated first.** Schema conformance, then values against an answer key, then ten
held-out questions put to your agent. Each chapter's rubric is in its own file above.

**Chapters are gated.** Later chapters are not scored if your dataset fails schema
validation. Not because the rest does not matter, but because nothing downstream can be
evaluated against a file we cannot read. Prioritise accordingly: a working agent on top
of a broken pipeline scores nothing.

**Then read.** Code and video, for submissions that clear the automated gates.

**Then interviews.** A technical and behavioural conversation with the DSRS team,
including a walkthrough of your own code — where we will ask about specific decisions and
may ask you to change something on the spot.

---

## Submitting

You submit **one link**: your GitHub repository URL. Everything else lives in the repo.

Your code is not frozen at submission. We take the last commit made before the deadline,
so keep committing and pushing right up to it — and please commit as you work rather than
in one push at the end.

Before you submit:

```bash
python verify.py            # your Parquet matches the schema
python check_submission.py  # everything required is committed and pushed
```

Then work through the checklist in
[../submission/SUBMISSION.md](../submission/SUBMISSION.md).

---

## On AI assistance

We encourage its usage — you are applying to build agentic tooling.

Declare what you used in `submission/AI_USAGE.md`. We are not scoring the amount. We are
checking that you can account for your own work, which is also what the walkthrough is
for.

Commit as you go. A single large commit at the deadline is a flag.

---

## On libraries

Use what you judge appropriate and document each addition in
`submission/DEPENDENCIES.md` with a one-line reason.

Libraries that wrap 13F retrieval and parsing end to end will not, on their own, satisfy
the schema — and we will ask you to explain the edge cases in your output regardless of
how you produced it. If you can explain it, you own it.

---

## Your work

The code is yours, and once results are announced you are welcome to make your repository
public and put it in your portfolio.

We may share your submitted video publicly to show what candidates built. If you would
rather we did not, say so in `submission/SUBMISSION.md`.

---

Start with [1 · Source](01-source.md).
