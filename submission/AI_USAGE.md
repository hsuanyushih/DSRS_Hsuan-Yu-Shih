# AI Usage

I used Claude (Anthropic) and GitHub Copilot on this project.

Claude was mainly a partner for organizing the code architecture and writing
code. Claude would first explain the reasoning behind a step, I kept asking
follow-up questions until I actually understood it, and the code itself was
written together through discussion. I personally ran every command myself,
and whenever an error message came up I checked and confirmed it carefully
myself before moving on.

Copilot was mainly used to review consistency across multiple files in the
project, and to catch related content scattered across different files that
needed to be handled together.

## Examples of what Claude helped with

- **Architecture and sequencing.** Breaking the challenge into a pipeline
  (`fetch.py` -> `cik_verify.py` -> `discover_filings.py` -> `download_filings.py`
  -> `parse_filings.py` -> `main.py`), and explaining why each piece needed to
  exist before I could build the next one.
- **Writing and reviewing code.** Most modules were drafted with Claude's help,
  then reviewed together against the actual chapter requirements (e.g. checking
  `parse_filings.py`'s namespace handling against what `eda.py` actually found
  in the downloaded XML).
- **Debugging.** 
  - The `fetch.py` cache directory conflicting with `.gitignore`'s `output/`
    negation rules, discovered by inspecting `git status` output together.
  - The Tudor Investment Corp CIK resolving to the wrong entity (State of
    Wisconsin Investment Board) -- Claude help to looked up the real filing history for
    each candidate CIK via SEC's submissions API, and I decided which evidence
    was convincing before we encoded the fix in `src/cik_verify.py`.
  - `submission/eda.py` calling `fetch()` without `set_user_agent()`, and the
    mock LLM response shape not matching what `planner.py` expected, both
    root-caused by actually reading the tracebacks and the relevant source
    files together.
  - Local Ollama not respecting guided JSON decoding reliably, diagnosed by checking `ps` in raw model output, documented as a known local-development limitation in `ASSUMPTIONS.md`.
- **Explaining, not just fixing.** Where I didn't understand *why* something
  broke (e.g. why `output/.cache` was being tracked despite `.gitignore`, or
  why the local mock LLM couldn't produce a valid `QueryPlan`), I asked and got
  a plain-language explanation before moving on, rather than accepting a patch
  I couldn't account for.

## What I did myself

- Made the actual judgment calls where the spec required one -- e.g. deciding
  the Tudor CIK evidence was convincing enough to encode as a correction, and
  deciding to keep `output/filings.csv` as a committed intermediate file rather
  than discard it.
- Set up the local Ollama environment and chose which model to test against given my machine's limits.