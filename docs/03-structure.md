# 3 · Structure

**5 points** · Produces `output/filings.parquet` and `output/holdings.parquet`

---

You know what the data looks like. Now build the thing the researcher asked for.

> "Parser time. You've read the schema and you've seen what's actually in the files, so
> you already know where the two disagree — build for what's there.
>
> One thing worth flagging because it's easy to miss: notices still get a row. A 13F-NT
> has a cover page and no holdings, and the instinct is to skip it since there's nothing
> to parse. But then a manager who filed something looks like a manager who filed
> nothing, which is worse than useless to the researcher.
>
> And run it twice before you call it done. Same input, same bytes out. If the second
> run differs, something in there isn't deterministic — easier to track down now than
> when she asks why last week's numbers moved."

---

## 3.1 · What you are building

Two Parquet files, per **[SCHEMA.md](SCHEMA.md)** — which is the contract, exactly as
written.

| File | Grain | Expected rows |
|---|---|---|
| `output/filings.parquet` | One row per 13F filing | 40 |
| `output/holdings.parquet` | One row per position | thousands |

Joined on `accession_number`. Twenty managers across two quarters is forty filings —
notices included, since every filing gets a row whether or not it carries positions.

If your filing count is not forty, something upstream is wrong. Find it before you
continue; a parser built on the wrong input set produces a clean file full of the wrong
data.

---

## 3.2 · Namespaces

Filers use different namespace prefixes for the same schema. One filing declares a
default namespace; another binds the identical namespace URI to a prefix such as `ns1:`.
Both are correct XML.

**Match elements on namespace and local name, not on the literal tag string.** Matching
on the string is the single most common way a 13F parser silently returns zero positions
for a subset of filers — it does not error, it just finds nothing.

---

## 3.3 · Duplicate entries

**`cusip` is not unique within a filing.** Do not deduplicate, aggregate, or collapse
rows on it, or on any combination of columns.

A single filing may legitimately contain several entries sharing a CUSIP — different
lots, different discretion, different managers within the same platform. Every entry is
its own row. A pipeline that "cleans" these away has destroyed information the researcher
needs, and done so invisibly: the output looks tidier and is wrong.

**Row order within a filing follows the order of the source information table.** Do not
sort before writing.

---

## 3.4 · Notice filings

A **13F-NT** is a notice: a cover page stating that the manager's holdings are reported
in another manager's filing. It carries no information table.

For this chapter, a notice produces **a row in `filings.parquet` and nothing in
`holdings.parquet`**. Its `table_entry_total` and `table_value_total` are null, and its
`report_type` records that it is a notice.

Do not drop it. This is why the schema splits filings from holdings — a notice that
vanishes from your output misrepresents a manager as having filed nothing, when they
filed something that said "look elsewhere."

Recovering the holdings those notices point at is
**[Bonus Challenge 1](bonus-01-notice-attribution.md)**.

### A note on the amendment columns

`filings.parquet` carries `is_amendment`, `amendment_no`, and `amendment_type`. No
manager in your roster amended a filing inside the report periods and cutoff you are
working with, so these columns exist and stay unexercised: `is_amendment` is false,
the other two null.

Populate them from the filing rather than hard-coding the constant. The schema is
written for 13F data generally, not just this slice, and a pipeline that assumes no
amendments exist is one that breaks the first quarter someone files one.

---

## 3.5 · File conventions

- **Format:** Parquet, Snappy compression
- **Paths:** `output/filings.parquet` and `output/holdings.parquet`
- **Partitioning:** optional; `report_quarter` is the sensible key if you do
- **Column names:** exactly as specified, lowercase snake_case
- **Types:** the Arrow types in SCHEMA.md. Where a column is nullable, write a genuine
  null — not `""`, `0`, or `"N/A"`

Two failure modes worth naming, because they account for most rejected submissions:

**Numeric columns written as floats.** A float64 cannot represent every integer above
2^53, and grading compares exact integers. Cast to `int64` before writing.

**A pandas index leaking into the file.** Write with `index=False`, or you will ship an
extra column that fails schema validation.

Check your output before you move on:

```bash
python verify.py
```

This is the same structural validator we run: it checks that both files exist, that every
required column is present with the specified type, and that non-nullable columns contain
no nulls. Passing means your submission can be read and graded. It does not mean your
values are correct.

---

## 3.6 · Run it twice

Your pipeline is executed twice during grading, and the second run must produce
**byte-identical Parquet files**. Same input, same output — every time.

That is the requirement. If you cached your EDGAR responses in Chapter 1, the second run
will also be much faster, because it reads from disk instead of re-fetching. We look at
that as evidence the cache works, but speed is the side effect; determinism is the point.

Non-determinism usually comes from one of a few places: iteration over a set or dict
whose order varies between runs, timestamps written into the data, an unstable sort where
keys tie, or re-fetching and picking up a filing that arrived in between. If your second
run differs, one of those is why.

---

## How this chapter is graded

| | Points |
|---|---|
| **Schema conformance** — 40 filing rows, correct columns, correct types, valid nulls | 2 |
| **Parsing correctness** — namespaces handled, duplicates preserved, values accurate against the answer key | 2 |
| **Notice handling** — the notice filing represented, holdings tables absent | 1 |

Schema validation is a gate. A submission whose Parquet files do not conform is not
scored further — not because the rest does not matter, but because nothing downstream
can be evaluated against a file we cannot read.

---

Next: [4 · Serve](04-serve.md)

Optional, once the core is done:
[Bonus 1 · Notice attribution](bonus-01-notice-attribution.md) · [Bonus 2 · CUSIP validation](bonus-02-cusip-validation.md)
