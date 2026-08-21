# 1 · Source

**5 points** · Produces `output/filers.csv` and `output/filings/`

---

A researcher has come to DataHub with a list of twenty investment managers. She wants to
study how their equity positions moved over the last two quarters, and she needs the
holdings in a form she can actually work with.

She gave us `filers.csv` — the fund names and the CIKs she had on hand. Your tech lead
looked it over and sent you this:

> "Welcome aboard — this one's a good first project, you'll touch the whole pipeline.
>
> Start with the CIKs, and don't trust them. They came from a spreadsheet somebody
> maintained by hand, and I'd bet at least one is wrong. Check them against SEC's own
> lookup file before anything else — if we pull filings for the wrong manager,
> everything downstream is confidently wrong and nothing errors to tell us.
>
> Then find the filings, pull the XML, and cache it locally so you can re-run without
> going back to EDGAR every time. You'll be re-running a lot. Some of these managers
> file notices instead of holdings — we'll get into what that means next chapter, just
> grab them while you're in there.
>
> One thing to read before you start: SEC's access rules. They're reasonable and they're
> enforced, and it's much easier to build for them now than to get unblocked later.
> Shout if anything's unclear."

---

## 1.1 · Verify the CIKs

SEC publishes a complete name-to-CIK mapping:

```
https://www.sec.gov/Archives/edgar/cik-lookup-data.txt
```

A large plain-text file, one record per line, colon-delimited, company names uppercased.
Download it once and store it as a CSV of your own — you will reference it repeatedly,
and re-downloading a file this size on every run is the habit that gets an IP throttled.

Then reconcile it against `filers.csv`.

**When a name and a CIK disagree, the name is right and the CIK is wrong.** Fix the CIK.
Do not rename the fund to match whatever entity the bad CIK points to — that is the
failure mode this task exists to catch. A wrong CIK resolves to a real company, and
every step after it runs cleanly on the wrong manager's data.

Names will not match character for character. Legal suffixes vary, punctuation drifts,
and some managers appear under several spellings. Exact matching will not get you there;
matching too loosely will hand you the wrong entity. Working out where that line sits is
the point of this section.

---

## 1.2 · Find the filings

With correct CIKs, use the submissions API:

```
https://data.sec.gov/submissions/CIK##########.json
```

This returns every filing for a CIK, 13F included. The API documentation discusses only
XBRL forms, but the endpoint is not limited to them.

**Scope.** Only these report periods:

| `reportDate` | Quarter |
|---|---|
| `2026-03-31` | 2026 Q1 |
| `2026-06-30` | 2026 Q2 |

Note these are the two **2026** report periods. A filing accepted in February 2026
reports on Q4 **2025** — it was filed this year, but it is not in scope.

One more filter: **`filingDate` on or before 18 August 2026.** Q2 filings were due
14 August, and late filings and amendments keep arriving after that. Without the cutoff,
two correct pipelines run three days apart produce different output — and only one of
them can match our answer key.

With both filters applied you should find **40 filings**: twenty managers, two quarters
each. If you find more, check your `filingDate` cutoff. If you find fewer, check your
CIKs.

Filter on **`reportDate`**, not `filingDate`. They answer different questions:
`reportDate` is the quarter the holdings describe, `filingDate` is when the document
reached EDGAR. A filing submitted in May reports on March, and an amendment filed months
later still carries the original report date. Filtering on the wrong one silently
produces a different dataset.

**Forms in scope:** `13F-HR` and `13F-HR/A`. Also collect `13F-NT` and `13F-NT/A` — a
notice carries no holdings, but you will need to know which managers filed one.

---

## 1.3 · Download the filings

Filing documents live in EDGAR's archive:

```
https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/
```

This is a static file store, not a documented API. Use `index.json` in that directory to
enumerate a filing's documents and locate the information table.

Three details that will cost you an hour each if you miss them:

**Accession numbers come from the submissions API. Do not construct them.** They are not
sequential, not predictable, and not derivable from anything else you hold.

**CIK format differs between the two endpoints.** The submissions endpoint wants it
zero-padded to ten digits (`CIK0001423053.json`). The archive path wants no leading
zeros (`/edgar/data/1423053/`). Same number, two formats, two URLs you call in sequence.

**Accession numbers carry dashes in API responses but not in archive directory names.**
`0001423053-26-000012` in JSON becomes `000142305326000012` in the path.

Store what you download here:

```
output/filings/{cik}/{accession}.xml
```

CIK directories without leading zeros. One file per filing.

---

## 1.4 · Fetching responsibly

EDGAR is a live public service used by regulators, journalists, and other students.

**Required.** A `User-Agent` header carrying your name and email, in SEC's requested
format:

```
FirstName LastName netid@illinois.edu
```

Requests without one are rejected. A submission whose code does not set one fails this
chapter regardless of its output.

**Required.** Stay within SEC's fair-access limit of **10 requests per second**. Run
well under it. If you are throttled, back off rather than retrying immediately —
hammering a service that has just asked you to stop is how a temporary throttle becomes
a block.

**Expected.** Cache raw responses to disk and resume rather than restart. Your pipeline
will be run twice: the second run must complete substantially faster, produce identical
output, and show cache hits in your manifest. Design for that now rather than bolting it
on later.

---

## What you produce

### `output/filers.csv`

Twenty rows, ordered by CIK ascending, with a third column recording what you did:

```csv
fund_name,cik,cik_source
Renaissance Technologies LLC,1037389,given
Third Point LLC,1040273,corrected
```

| `cik_source` | meaning |
|---|---|
| `given` | the CIK in `filers.csv` matched the lookup |
| `corrected` | it did not; you replaced it |

CIKs without leading zeros. Fund names exactly as given.

The third column is the point. A corrected file alone cannot show whether you verified
all twenty or happened to get lucky — `cik_source` is how you demonstrate you checked.

### `output/filings/`

The XML you downloaded, one directory per CIK:

```
output/filings/
├── 1037389/
│   ├── 000103738926000004.xml
│   └── 000103738926000011.xml
└── 1040273/
    └── 000104027326000003.xml
```

---

## How this chapter is graded

| | Points |
|---|---|
| **CIK verification** — correct fixes, correct `cik_source` values | 2 |
| **Filing discovery** — right forms, right periods, correct accessions | 1 |
| **Fetching conduct** — User-Agent, rate limiting, caching, resumability | 2 |

A missing or malformed `User-Agent` fails the chapter outright. It is not a style
preference — it is the one condition SEC states for access.

---

Next: [2 · Interrogate](02-interrogate.md)
