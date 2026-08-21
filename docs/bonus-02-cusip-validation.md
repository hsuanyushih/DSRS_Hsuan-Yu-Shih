# Bonus 2 · CUSIP validation

**5 points** · Optional · Produces `output/bonus_cusip_validation.csv`

Attempt this only once chapters 1–5 are done. It builds on the dataset from Chapter 3
and is worth nothing if that does not pass — the bonuses are extra credit on a complete
submission, not a substitute for one.

Independent of Bonus 1. Do either, both, or neither, in whichever order suits you.

---

> "Here's the thing that would keep me up at night if I were handing this dataset to
> someone.
>
> Every CUSIP in there came off a filing, and we took all of them at face value. But
> these are typed in by people. A transposed digit produces a CUSIP that looks completely
> valid — nine characters, right shape, nothing to flag it — and it points at the wrong
> security or at nothing at all. We'd never know.
>
> SEC publishes the actual list of securities reportable on Form 13F, updated quarterly.
> That's our ground truth. Check our Q2 holdings against it and find out which CUSIPs
> don't belong.
>
> Some misses will have innocent explanations, and worth noting those. But what I'm
> really after is the errors — the ones where a filer got it wrong and we've been
> carrying it ever since."

---

## The official list

SEC publishes the Official List of Section 13(f) Securities each quarter — every
security a manager is permitted to report on Form 13F. For 2026 Q2:

```
https://www.sec.gov/files/investment/13flist2026q2-txt.txt
```

A plain-text file. Work out its structure by reading it; that is part of the exercise,
and it is not the format anyone would design today. Pay particular attention to how
CUSIPs are written there, because it is unlikely to match how you stored them.

---

## What to check

Take your **2026 Q2** holdings and check every CUSIP against the official list.

A CUSIP that is not on the list is a reported security that SEC does not recognise as
13F-reportable for that quarter. **The most likely reason is that the filer got it
wrong** — a transposed digit, a dropped character, a stale identifier carried forward
from an old position. Nothing in the filing flags this. The value is well-formed and
points somewhere else, or nowhere.

That is the finding you are looking for.

Other explanations exist, and separating them out is what makes this worth doing:

- **Formatting on your side.** If you and the official list write CUSIPs differently,
  you will manufacture mismatches that are entirely your own. Rule this out first —
  before concluding anything about filers, be certain the comparison is fair.
- **CINS codes.** Foreign securities carry identifiers that look like CUSIPs and are
  constructed differently.
- **Timing.** The list is a snapshot. A security can be added or removed between
  quarters.

Work through those, then say what is left and what you think it is. A candidate who
reports fifty mismatches without checking their own normalisation has found nothing.

---

## What you produce

### `output/bonus_cusip_validation.csv`

One row per **(accession_number, cusip)** pair in your 2026 Q2 holdings.

The accession matters: it identifies which filing reported the value, and therefore
which manager to attribute an error to. The same CUSIP can be correct in one filing and
mistyped in another, and a per-CUSIP summary would average that away.

| Column | Type | Description |
|---|---|---|
| `accession_number` | string | The filing that reported this CUSIP, dashed form |
| `cik` | string | Filing manager's CIK, zero-padded to 10 |
| `fund_name` | string | Fund name from your `filings.parquet` |
| `cusip` | string | As stored in `holdings.parquet` — 9 characters |
| `on_official_list` | bool | Whether it appears on the Q2 2026 list |
| `issuer_from_filing` | string | `name_of_issuer` as filed |
| `issuer_from_list` | string | Issuer name from the official list; null when unmatched |
| `rows` | int | Holdings rows in this filing carrying this CUSIP |
| `assessment` | string | For unmatched CUSIPs, what you concluded. Null when matched. |

Sorted by `accession_number`, then `cusip`.

Suggested values for `assessment` — extend if you find something these do not cover:

| | |
|---|---|
| `LIKELY_FILER_ERROR` | Malformed, or points at something inconsistent with the issuer name filed |
| `CINS_FOREIGN` | A foreign-security identifier rather than a domestic CUSIP |
| `TIMING` | Plausibly added or removed between list publications |
| `UNRESOLVED` | Genuinely unexplained |

`UNRESOLVED` is an acceptable answer. Guessing is not.

### Your write-up

Add a section to `submission/ASSUMPTIONS.md`: how many matched, how many did not, what
the unmatched ones turned out to be, and — for anything you concluded was a filer error
— which filing and what the evidence was.

Close with what you would tell a researcher who asked whether she can trust the CUSIPs
in this dataset. A paragraph is enough.

---

## How this is graded

| | Points |
|---|---|
| **Parsing the list** — read correctly, CUSIPs normalised so the comparison is fair | 1 |
| **The check** — accurate results at the accession level across Q2 holdings | 2 |
| **Error identification** — likely filer errors found, evidenced, and distinguished from innocent mismatches | 2 |

The last row is the point. A match rate is mechanical. Identifying which specific filings
carry a bad identifier — and being able to show why you think so — is the work a
researcher is actually relying on when she cites this dataset.
