# DSRS Data Curator Challenge

Fetch SEC 13F filings from EDGAR, structure them into a dataset a researcher can trust,
and make it accessible through an agent.

**Start with [docs/CHALLENGE.md](docs/CHALLENGE.md)** — what to build, how it is scored,
and what to submit.

---

## Getting your repo

1. **Sign in to GitHub**, then
   [create your repository from this template](https://github.com/GiesDSRS/dsrs-curator/generate)
2. Name it, set visibility to **Private**, and create it
3. **Settings → Collaborators → Add people → `dsrsBOT`**, Read access
4. Clone it and start

Use the link above rather than the **Fork** button — a fork of a public repository is
always public, and your work needs to stay private until results are announced.

Step 3 is the one people forget. Without it we cannot read your repository, and there is
no submission to grade.

---

## Setup

Python 3.12.

```bash
pip install -r requirements.txt -r requirements-extra.txt
cp .env.example .env          # then fill in your model endpoint
python -m agents.llm          # confirms the connection works
```

Or build the image we grade in:

```bash
docker build -f Dockerfile.base -t curator-base .
docker build -t curator-submission .
docker run --rm -v "$PWD/output:/app/output" -v "$PWD/.cache:/app/.cache" \
  curator-submission --user-agent "FirstName LastName netid@illinois.edu"
```

Building in Docker at least once before you submit is worth the ten minutes. Most
grading failures are environment differences rather than logic errors.

---

## Commands

```bash
python main.py --user-agent "FirstName LastName netid@illinois.edu"
python -m agents.answer "which manager held the most Nvidia in 2026 Q2?"
python verify.py
python check_submission.py
```

`main.py` and `agents/answer.py` are how we run your submission. They must work from a
clean checkout.

---

## Layout

```
main.py               your pipeline — the entry point we call
agents/
  llm.py              model access (frozen)
  answer.py           your agent — main(question) -> dict
docs/                 read these before you start
submission/           fill these in before you submit
filers.csv            the roster: twenty managers, CIKs not all trustworthy
output/               your outputs land here, and are committed
verify.py             checks your Parquet against the schema (frozen)
check_submission.py   checks your submission is complete (frozen)
tests/                yours
```

---

## Frozen files

Do not edit these. Modifications are detected and the original is restored before
grading, so changes are discarded rather than penalised — but your code then runs
against the original.

```
verify.py  check_submission.py  agents/llm.py
filers.csv  requirements.txt  Dockerfile.base
```

Add your dependencies to `requirements-extra.txt`, pinned, and justify each in
`submission/DEPENDENCIES.md`.

If something in a frozen file looks broken, email dsrs@business.illinois.edu rather than
working around it locally.

---

## What you commit

| Path | Chapter |
|---|---|
| `output/filers.csv` | 1 · Source |
| `output/filings/` | 1 · Source |
| `submission/eda.py` | 2 · Interrogate |
| `output/filings.parquet`, `output/holdings.parquet` | 3 · Structure |
| `agents/answer.py`, `output/agent_usage.json` | 4 · Serve |
| `submission/SUBMISSION.md` (with video link) | 5 · Show |
| `submission/ASSUMPTIONS.md`, `AI_USAGE.md`, `DEPENDENCIES.md` | required |

`output/` is committed — it is the submission. `.cache/` and `.env` are not.

---

## EDGAR

You fetch from live EDGAR. A `User-Agent` carrying your name and email is required, and
SEC caps clients at 10 requests per second. Cache what you download and resume rather
than restart: your pipeline is run twice, and the second run must produce byte-identical
output.

Details in [docs/01-source.md](docs/01-source.md).

---

## Before you submit

```bash
python verify.py            # your Parquet matches the schema
python check_submission.py  # everything required is committed and pushed
```

Then work through the checklist in
[submission/SUBMISSION.md](submission/SUBMISSION.md).

**Deadline: Monday, August 24, 2026, 11:59 AM US Central.** Your code is not frozen at
submission — we take the last commit before the deadline, so keep pushing until then.
