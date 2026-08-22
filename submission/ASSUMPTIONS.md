# Assumptions

This document records decisions made where the spec was ambiguous, or where a
judgment call was required and the reasoning is worth preserving.

---

## Chapter 1 · Source

### CIK override: Tudor Investment Corp

The roster's given CIK for Tudor Investment Corp (`0000854157`) resolves to
**STATE OF WISCONSIN INVESTMENT BOARD**, an unrelated filer with 103 of its own
13F-HR filings on record. This is not a name-formatting mismatch -- it is a
genuinely wrong CIK.

Name-based matching against SEC's `cik-lookup-data.txt` surfaced two candidates
for "Tudor Investment Corp":

| CIK | SEC-registered name | 13F-HR filings on record |
|---|---|---|
| `0001080384` | TUDOR INVESTMENT CORP | 0 |
| `0000923093` | TUDOR INVESTMENT CORP ET AL | 116 (1999–2026) |

Automatic name-matching alone could not disambiguate between these two, because
after stripping the `ET AL` suffix (a SEC convention marking a CIK that files on
behalf of an affiliated group) both names normalize to the same core string. The
correct entity was identified by querying each candidate's real filing history via
the SEC submissions API: `923093` has a continuous, multi-year record of 13F-HR
filings; `1080384` has none. `923093` was adopted as the correct CIK
(`cik_source = corrected`), encoded as a manually-verified override in
`src/cik_verify.py` (`MANUAL_CIK_OVERRIDES`) so the fix is applied automatically
on every pipeline run rather than requiring a one-off manual edit of
`output/filers.csv`.

Two other candidates were investigated and found *not* to be errors, despite
looking suspicious at first glance:

- **DME Capital Management LP (Greenlight)**, given CIK `0001489933` — the
  parenthetical "(Greenlight)" is a roster annotation, not part of the legal
  entity name (David Einhorn's affiliated entity, same registered address as
  Greenlight Capital). The given CIK is correct; `cik_source = given`.
- **Situational Awareness LP**, given CIK `0001697748` — resolved to
  `0002045724` (`cik_source = corrected`). The much higher CIK number is
  consistent with this being a recently registered fund, and the entity
  (founded by Leopold Aschenbrenner) is confirmed to be real.

### Name-matching normalization

`src/cik_verify.py` normalizes company names before matching by stripping:
punctuation, a leading "THE", parenthetical annotations, a trailing SEC
state-disambiguator (e.g. `/MA`), and the `ET AL` group-filing marker. Matching
is tiered: an exact core-name match with a unique candidate is auto-corrected;
zero or multiple candidates are flagged `NEEDS_REVIEW` and require either a
`MANUAL_CIK_OVERRIDES` entry (with documented evidence, as above) or human
judgment before the pipeline is considered final. No case was resolved by
picking the "closest" fuzzy match without evidence.

### Filing storage: two files per filing, not one

`01-source.md`'s example output structure shows one XML file per accession
(`{accession}.xml`). This pipeline stores **two** files per filing:

```
output/filings/{cik}/{accession}.cover.xml   (cover page)
output/filings/{cik}/{accession}.xml         (information table, when present)
```

This is necessary because `filings.parquet` requires columns that exist only on
the cover page (`filing_manager`, `amendment_type`, `table_entry_total`,
`other_included_managers_count`, etc. -- see SCHEMA.md) and are not present in
the information table document. Storing only the information table, as the
example structure implies, would make Chapter 3 impossible to complete without
a second, unrecorded fetch per filing. For 13F-NT notices, only the `.cover.xml`
file exists, since a notice carries no information table.

---

## Chapter 3 · Structure

### Notice handling

The one 13F-NT in scope (Pershing Square Capital Management, CIK 1336528,
accession `0001172661-26-003777`) is kept as its own row in `filings.parquet`
with `table_entry_total`/`table_value_total` null, per SCHEMA.md, and
contributes zero rows to `holdings.parquet`. An earlier version of
`discover_filings.py` attempted to resolve the notice to its parent filing's
holdings automatically; this was removed once 03-structure.md made explicit
that the notice itself must be the row Chapter 3 represents. Recovering the
actual holdings behind this notice is Bonus 1's task, not Chapter 3's.

---

## Chapter 4 · Serve

### Local development against Ollama (llama3.2:1b)

The grading endpoint (`google/gemma-4-31B-it` via vLLM) was not available
during development. The pipeline was developed and smoke-tested against a
local Ollama instance running `llama3.2:1b` -- a small (1.24B parameter),
non-guided-decoding-optimized model, used only to validate wiring, not to
produce correct answers.

Two behaviors observed locally are attributed to this substitution rather than
to defects in `planner.py` or `executor.py`:

1. **Guided decoding reliability.** Ollama's support for
   `extra_body={"guided_json": ...}` is inconsistent: some calls correctly
   constrained output to `QUERY_PLAN_SCHEMA`; others ignored the constraint and
   produced a self-invented JSON Schema *document* instead of a plan instance
   (observed on 3 of the 10 example questions in `output/agent_usage.json`,
   e.g. "Which manager added the most Nvidia shares..."). vLLM enforces guided
   decoding via token masking during generation, a stronger guarantee than
   Ollama currently provides. `planner.py`'s `_validate()` treats any
   malformed or incomplete plan as a `PlanError`, which `answer.py` converts to
   a null answer -- correct behavior regardless of the underlying cause.
2. **`max_tokens=400` headroom.** Several malformed responses were truncated
   at the 400-token cap before finishing (`completion_tokens: 400` rows in
   `output/agent_usage.json`), consistent with a small, non-guided model
   producing a verbose preamble before its JSON. A properly guided-decoding
   endpoint should not exhibit this pattern, since guided decoding constrains
   every token from the start rather than allowing free-form text before the
   structured output. Left unchanged pending behavior against the real grading
   model; revisit if the same truncation appears at grading time.

`output/agent_usage.json` still demonstrates the properties Chapter 4 grades on
independent of answer correctness: exactly one LLM call per question (no retry
loops), and full null-answer handling with no crashes across all 10 example
questions, including the intentionally out-of-scope one (2026 Q3).

### Architecture

```
question -> planner.plan_query()   LLM, schema-constrained -> QueryPlan
         -> executor.execute()     pure pandas over read-only Parquet files
         -> answer.main()          formats {"answer", "unit", "sources"}
```

The LLM only ever sees the user's question text and a fixed system prompt; it
never sees filing-sourced free text (`name_of_issuer` / `title_of_class`), and
its output is never executed as code or SQL -- only whitelisted enum/string
fields that `planner.py` validates before `executor.py` touches the data.
Manager and issuer name resolution happens locally in `data.py` via string
normalization and matching (reusing `src/cik_verify.py`'s name-normalization
logic), not through the model, since filing-sourced issuer names are
third-party free text and therefore untrusted input.
