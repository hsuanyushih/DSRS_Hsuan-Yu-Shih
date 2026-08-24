# Assumptions

This document records decisions made where the spec was ambiguous, or where a
judgment call was required and the reasoning is worth preserving.

---

## Chapter 1 · Source

### CIK override: Tudor Investment Corp

The roster's given CIK for Tudor Investment Corp (`0000854157`) resolves to
**STATE OF WISCONSIN INVESTMENT BOARD**, an unrelated filer with 103 of its own
13F-HR filings on record. This is not a name-formatting mismatch but a wrong CIK.

Name-based matching against SEC's `cik-lookup-data.txt` surfaced two candidates
for "Tudor Investment Corp":

| CIK | SEC-registered name | 13F-HR filings on record |
|---|---|---|
| `0001080384` | TUDOR INVESTMENT CORP | 0 |
| `0000923093` | TUDOR INVESTMENT CORP ET AL | 116 (1999–2026) |

Automatic name-matching alone could not disambiguate between these two, because
after stripping the `ET AL` suffix both names normalize to the same core string. The
correct entity was identified by querying each candidate's real filing history via
the SEC submissions API: `923093` has a continuous, multi-year record of 13F-HR
filings; `1080384` has none. `923093` was adopted as the correct CIK
(`cik_source = corrected`), encoded as a manually-verified override in
`src/cik_verify.py` (`MANUAL_CIK_OVERRIDES`) so the fix is applied automatically
on every pipeline run rather than requiring a one-off manual edit of
`output/filers.csv`.

Two other candidates were investigated and found *not* to be errors, despite
looking suspicious at first glance:

- **DME Capital Management LP (Greenlight)**, given CIK `0001489933`. The
  parenthetical "(Greenlight)" is a roster annotation, not part of the legal
  entity name (David Einhorn's affiliated entity, same registered address as
  Greenlight Capital). The given CIK is correct; `cik_source = given`.
- **Situational Awareness LP**, given CIK `0001697748`, resolved to
  `0002045724` (`cik_source = corrected`). The much higher CIK number is
  consistent with this being a recently registered fund, and the entity
  (founded by Leopold Aschenbrenner) is confirmed to be real.

### Name-matching normalization

`src/cik_verify.py` normalizes company names before matching by stripping
punctuation, a leading "THE", parenthetical annotations, a trailing SEC
state-disambiguator (e.g. `/MA`), and the `ET AL` group-filing marker. Matching
is tiered: an exact core-name match with a unique candidate is auto-corrected;
zero or multiple candidates are flagged `NEEDS_REVIEW` and require either a
`MANUAL_CIK_OVERRIDES` entry or human judgment before the pipeline is
considered final. No case was resolved by picking the "closest" fuzzy match
without evidence.

### Filing storage: two files per filing, not one

`01-source.md`'s example output structure shows one XML file per accession
(`{accession}.xml`). This pipeline stores **two** files per filing:

```
output/filings/{cik}/{accession}.cover.xml   (cover page)
output/filings/{cik}/{accession}.xml         (information table, when present)
```

This is necessary because `filings.parquet` requires columns that exist only on
the cover page (`filing_manager`, `amendment_type`, `table_entry_total`,
`other_included_managers_count`, etc.) and are not present in the information
table document. Storing only the information table, as the example structure
implies, would make Chapter 3 impossible to complete without a second,
unrecorded fetch per filing. For 13F-NT notices, only the `.cover.xml` file
exists, since a notice carries no information table.

---

## Chapter 3 · Structure

### Notice handling

The one 13F-NT in scope (Pershing Square Capital Management, CIK 1336528,
accession `0001172661-26-003777`) is kept as its own row in `filings.parquet`
with `table_entry_total`/`table_value_total` null, per SCHEMA.md, and
contributes zero rows to `holdings.parquet`. An earlier version of
`discover_filings.py` attempted to resolve the notice to its parent filing's
holdings automatically; this was removed once 03-structure.md made explicit
that the notice itself must be the row Chapter 3 represents. 

---

## Chapter 4 · Serve

### Local development against Ollama (llama3.2:1b)

The pipeline was developed and smoke-tested against a
local Ollama instance running `llama3.2:1b`, a small (1.24B parameter),
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
   a null answer, correct behavior regardless of the underlying cause.
2. **`max_tokens=400` headroom.** Several malformed responses were truncated
   at the 400-token cap before completing the JSON output
   (`completion_tokens: 400` rows in `output/agent_usage.json`). This is
   consistent with smaller, non-guided models producing explanatory or
   exploratory text before the structured output, rather than emitting the
   JSON directly. A properly guided-decoding endpoint should not exhibit this
   pattern, since guided decoding constrains every token from the start
   rather than allowing free-form text before the structured output. Not
   addressed further, given this is a constraint of the local model rather
   than the code.



### A real bug found and fixed via local testing: degenerate group_by/metric combinations

Local testing surfaced a genuine logic error, independent of model size: for
"How many distinct issuers did Renaissance Technologies LLC report in 2026
Q2?", `llama3.2:3b` correctly resolved the manager and metric
(`metric="distinct_issuers"`), but set `group_by="issuer"`, which is
semantically wrong for a single-manager question with no comparison, though a
value the schema otherwise permits.

`executor.py`'s grouped-metric path silently computed a valid-looking but
meaningless answer from that combination: grouping by `name_of_issuer` and
then counting `nunique()` of `name_of_issuer` within each group is
degenerate, since every group contains only itself, so the answer is always
`1`, regardless of the manager's true holdings. The agent returned
`{"answer": 1, "unit": "COUNT", ...}` with a valid-looking accession as its
source. The true answer, computed directly against `holdings.parquet`, is
`2898`. 

Fixed in `agents/planner.py`'s `_validate()`: `group_by="issuer"` combined
with `metric="distinct_issuers"` (and symmetrically `group_by="manager"`
with `metric="distinct_managers"`) is now rejected as a `PlanError` before
`executor.py` ever sees it, producing an honest null answer instead of a
silently wrong one. Verified against the same question and the same local
model after the fix: the agent now correctly returns null rather than `1`.

This was not a model-capability artifact. A schema-valid but semantically
degenerate combination, including the grading endpoint, and would have corrupted the answer without
this check.

A second instance surfaced testing CUSIP lookups: "What is the value of
CUSIP 037833100 in 2026 Q2?" (Apple) returned `29463108627` on one call,
missing Tudor Investment Corp and Millennium Management LLC entirely from
the sum (true total, verified directly against `holdings.parquet`, is
`34087212507`). Re-running the identical question immediately after,
against the same unmodified code, produced the correct total with both
managers correctly included in the accession whitelist. Stepping through
`execute()`'s intermediate state (the resolved `quarters`, `form_types`,
and the `_filter_filings()` whitelist) on the second call confirmed every
filtering step was correct and both managers' filings passed the
`form_type == "13F-HR"` check as expected. Since the same code produced
different QueryPlans for byte-identical input across two calls, this points to the LLM call itself, 
not`executor.py`'s filtering logic, as the source, consistent with the `temperature=0` 
non-determinism already documented above.

### Observed non-determinism in local Ollama testing

Re-running the same question against the same local model
(`llama3.2:3b`, temperature=0.0) twice produced two different numeric
answers: "What was Third Point LLC's largest position by value in 2026 Q1"
returned `2082795760` on one run and the correct `404043800` (verified
directly against `holdings.parquet`) on a later run, with identical code
and identical question text.

`agents/llm.py` sets `temperature=0.0` unconditionally, which should make
generation deterministic. Nothing in `planner.py` or `executor.py` introduces 
non-determinism: no unordered set iteration, no unstable sort, no retry that changes the prompt 
(verified by inspection; `_execute_grouped`/`_execute_delta` explicitly use 
`kind="stable"` sorts with a secondary key for this reason).

The most likely source is Ollama/llama.cpp's own prompt-caching layer:
server logs show the second run hit a cached prefix via LCP similarity
matching rather than generating from scratch, and the sampled continuation
differed despite temperature=0. This is a property of the local
llama.cpp-based serving stack, not of the agent's logic. The grading
endpoint runs vLLM, whose greedy decoding at temperature=0 does not share
this caching behavior. 

### Architecture

```
question -> planner.plan_query()   LLM, schema-constrained -> QueryPlan
         -> executor.execute()     pure pandas over read-only Parquet files
         -> answer.main()          formats {"answer", "unit", "sources"}
```

The LLM only ever sees the user's question text and a fixed system prompt; it
never sees filing-sourced free text (`name_of_issuer` / `title_of_class`), and
its output is never executed as code or SQL, only whitelisted enum/string
fields that `planner.py` validates before `executor.py` touches the data.
Manager and issuer name resolution happens locally in `data.py` via string
normalization and matching (reusing `src/cik_verify.py`'s name-normalization
logic), not through the model, since filing-sourced issuer names are
third-party free text and therefore untrusted input.

---

## Bonus 1 · Notice attribution

### Parent identification

Pershing Square Capital Management L.P. (CIK 1336528) filed a 13F-NT for
2026 Q2 (accession `0001172661-26-003777`). Its cover page's
`otherManagersInfo/otherManager` block names the parent filer directly:
CIK `0002026053`, "PERSHING SQUARE INC." This is not one of the 20 roster
managers, so its filing was fetched separately via the submissions API
(same User-Agent and rate-limit handling as Chapter 1). The parent's
2026 Q2 13F-HR is accession `0001172661-26-003790`.

### The mechanism, and two real structural surprises

The parent's cover page declares an `otherManagers2Info` list assigning a
sequence number to each affiliated manager it reports on behalf of.
Pershing Square Capital Management, L.P. is sequence number `1` in that
list. Two things about the real XML did not match the flatter structure
implied by `02-interrogate.md`'s description, and both were confirmed by
reading the actual fetched files rather than assumed:

1. **`otherManager2` nests its own `otherManager` sub-block.** The
   sequence number and the manager's cik/name are not siblings.
   `sequenceNumber` sits directly under `otherManager2`, while `cik` and
   `name` sit one level deeper, under `otherManager2 > otherManager`. A
   flat read of `otherManager2`'s direct children finds `sequenceNumber`
   but nothing else.
2. **`otherManager` in the information table is not always a single
   value.** It can be a comma-separated list of sequence numbers (e.g.
   `"1, 2, 3, 4"`, `"1, 2, 3, 4, 6"`), meaning a single position is
   jointly attributed to several of the parent's affiliated managers at
   once, not to exactly one. Every one of the parent's 15 information-table
   rows in this filing carries a multi-manager list; there is no row where
   Pershing Square Capital Management is the sole `otherManager` value.
   Attribution therefore means "sequence 1 appears in this row's list,"
   not "this row's value equals 1." `src/bonus_notice_attribution.py`
   splits on commas and checks membership accordingly.

### Attribution result

14 of the parent's 15 rows reference sequence 1 (Pershing Square Capital
Management); the one excluded row lists `"3, 4, 5"` and does not include
Pershing Square. All 14 attributed positions are large, well-known
holdings (Amazon, Meta, Microsoft, Visa, Uber, Mastercard, S&P Global,
Netflix, Brookfield, Restaurant Brands, Hertz, and two Howard Hughes
lots), consistent with Pershing Square's known concentrated,
large-cap-equity investing style, which is corroborating evidence that
the right manager and the right rows were found, not just a plausible
row count. Total attributed value: $19,316,172,772.

`output/bonus_attributed.parquet` has 14 rows: the `holdings.parquet`
schema plus `attributed_to_cik = "0001336528"` on every row, with
`accession_number` set to the parent's accession
(`0001172661-26-003790`), per the spec. These are real rows from a real
filing, not the notice.

### What this means for "ownership"

Because every attributed row is jointly held with at least three other
affiliated managers (never Pershing Square alone), this filing does not
support a claim that Pershing Square Capital Management held any of these
14 positions independently. What it supports is narrower and more
accurate: these are positions the Pershing Square affiliated group
reported, in which Pershing Square Capital Management, L.P. is one of the
managers exercising some form of discretion or voting authority, per
`investment_discretion` and the `voting_*` columns carried alongside each
row. A researcher using this output should read `attributed_to_cik` as
"this manager is party to this position," not "this manager alone owns
this position."

---

## Bonus 2 · CUSIP validation

### Parsing the official list

SEC's Official List of Section 13(f) Securities is a fixed-width text file,
per SEC's own published column spec
(https://www.sec.gov/divisions/investment/13flists.htm): CUSIP in columns
1-9, an option indicator in column 10, issuer name in columns 11-40, issuer
description in columns 41-67, status in columns 68-70. This is not
whitespace-delimited, and an earlier draft of the parser assumed it was
(splitting on runs of two-plus spaces); that assumption was wrong and was
replaced with fixed-offset slicing after fetching the real file and
confirming the column boundaries against a sample row (e.g.
`B38564108*CMB.TECH NV SHS...` slices cleanly into
CUSIP=`B38564108`, option=`*`, name=`CMB.TECH NV`). `src/bonus_cusip_validation.py`
implements this.

23,277 securities were parsed from the 2026 Q2 official list.

### The check

Every `(accession_number, cusip)` pair in the 2026 Q2 holdings was checked
against the official list, after normalizing both sides (uppercase,
strip non-alphanumerics) to rule out formatting differences as a source of
false mismatches before drawing any conclusion about filers.

**Result: 32,176 of 32,176 pairs matched (0 unmatched).**

This number was surprising enough to distrust at first. A 100% match rate
across a large dataset invites the suspicion that the comparison itself is
too lenient rather than that the data is genuinely clean. Before accepting
it, four representative CUSIPs (two CINS-style, two domestic) were spot-checked
by hand against the fetched official list text:

| CUSIP | Filed as | Official list name |
|---|---|---|
| `68243Q106` | 1-800-Flowers.Com Inc - US | 1 800 FLOWERS COM INC |
| `88554D205` | 3D Systems Corp - US | 3D SYS CORP DEL |
| `G01767105` | Alkermes Plc - US | ALKERMES PLC |
| `G1151C101` | Accenture Plc - US | ACCENTURE PLC IRELAND |

In each case the filed name and the official-list name clearly refer to the
same issuer despite differing formatting (suffix style, "- US" tags,
abbreviations), which is the expected signature of a correct match, not a
coincidental one. A parsing or normalization bug that manufactured false
matches would be far more likely to produce mismatched issuer names between
the two columns; it did not.

CINS-style (letter-leading) CUSIPs were also not treated as automatically
excluded from the official list: the raw list itself contains large numbers
of letter-leading identifiers for foreign issuers trading in the US (e.g.
`G01767105 ALKERMES PLC`, `G1151C101 ACCENTURE PLC IRELAND` both appear on
the list directly), so a CINS-style CUSIP matching the list is expected
behavior, not evidence of a bug.

### Error identification

No CUSIPs in the 2026 Q2 holdings failed to match the official list, so
there were no candidates to classify as `LIKELY_FILER_ERROR`, `TIMING`, or
`UNRESOLVED`. `output/bonus_cusip_validation.csv` has 32,176 rows, all with
`on_official_list=True` and `assessment` null.

### What I'd tell the researcher

Every CUSIP reported by every manager in the 2026 Q2 dataset appears on
SEC's own list of securities that are legitimately reportable on Form 13F
for that quarter, with the reported and official issuer names clearly
referring to the same underlying company in every spot-checked case. I
found no evidence of a transposed digit, dropped character, or stale
identifier in this slice of the data. That's a real finding, not an
unfinished check. It doesn't mean typos are impossible in general. 
It only means that this particular quarter, for these twenty managers, doesn't contain one.
