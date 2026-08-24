# Submission

Fill this in and commit it. A submission missing the video link is incomplete.

## Who

- **Name:** Hsuan-Yu, Shih
- **NetID:** hsuanyu5

## Video

Under 3 minutes, narrated, showing a cold-start pipeline run and your agent answering
a question.

Upload to Illinois MediaSpace: https://mediaspace.illinois.edu/upload/media
Set visibility to **Unlisted**.

- **Link:** https://mediaspace.illinois.edu/media/t/1_z6vbt72v

## Chapters attempted

Mark what you completed. Partial work still gets read.

- [x] 1 · Source
- [x] 2 · Interrogate
- [x] 3 · Structure
- [x] 4 · Serve
- [x] 5 · Show
- [x] Bonus 1 — Notice attribution
- [x] Bonus 2 — CUSIP validation

## Checklist

- [x] `python check_submission.py` passes
- [x] Repo is **private** and `dsrsBOT` is a collaborator with Read access
- [x] Video uploaded to MediaSpace, visibility **Unlisted**, link tested
- [x] Repository URL submitted at <https://ikompete.dsrs.illinois.edu/competition/16>
- [x] `python verify.py` passes
- [x] Pipeline run twice; output is byte-identical
- [x] `output/filings.parquet`, `output/holdings.parquet` committed
- [x] `output/filers.csv`, `output/filings/`, `submission/eda.py` committed
- [x] `DEPENDENCIES.md`, `AI_USAGE.md`, and `ASSUMPTIONS.md` filled in
- [x] No API keys, tokens, or credentials committed
- [x] Frozen files unmodified

## Anything we should know

The Chapter 4 agent was developed and tested against a local Ollama model
(`llama3.2:3b`) rather than the grading endpoint (`google/gemma-4-31B-it`),
since the grading endpoint was not available during development. The
architecture, security model, and honest-null behavior are confirmed
working correctly; however, I observed real non-determinism in the local
model across identical calls (documented with specific evidence in
ASSUMPTIONS.md), and one question type consistently fails locally due to
the small model not reliably following the structured output format. I'd
expect both issues to improve significantly against the actual vLLM
grading endpoint, but was unable to confirm this directly.

The most significant trade-off I'd flag is that I have not been able to verify
answer accuracy end-to-end against the actual grading model, only that the
pipeline is correctly wired, secure, and fails. With more time
I would test against a larger model or the actual grading endpoint to
validate real answer correctness.


## Video sharing

We may share your video publicly to show what candidates built. If you would rather we
did not, write "do not share" here:

- **Preference:**
