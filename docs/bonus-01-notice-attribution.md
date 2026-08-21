# Bonus 1 · Notice attribution

**5 points** · Optional · Produces `output/bonus_attributed.parquet`

Attempt this only once chapters 1–5 are done. It builds on the dataset from Chapter 3
and is worth nothing if that does not pass — the bonuses are extra credit on a complete
submission, not a substitute for one.

Independent of Bonus 2. Do either, both, or neither, in whichever order suits you.

---

> "One of the funds on the researcher's list filed a notice for a quarter. That means
> their holdings exist, they're just sitting inside another manager's filing. She still
> wants those positions.
>
> Have a look at how the parent's filing identifies whose holdings are whose. It's on
> the cover page. Pull out the rows that belong to our fund — and only those. The
> parent's own book is not what she asked for."

---

## What a notice means

A **13F-NT** is a cover page stating that the manager's holdings are reported in another
manager's filing. It carries no information table of its own.

This happens where several affiliated managers file together — a platform reports on
behalf of its subsidiaries, or one entity in a group files for the group. The holdings
are on record; they are attributed inside somebody else's document.

## The mechanism

Chapter 2 pointed at this. A filing that includes other managers' holdings declares them
on its cover page: `other_included_managers_count` says how many, and the cover page
lists them, each with a sequence number. Rows in the information table reference those
sequence numbers through `other_manager`.

That reference is how you tell which positions belong to which manager.

Two things to expect:

**Rows the parent holds on its own account carry no reference.** Absence means the
parent, not "unknown."

**Attribution may be incomplete.** A manager can resolve to few rows, or none. That is a
real finding about how the data is reported, not a bug to code around. Whatever you
conclude, record it in `submission/ASSUMPTIONS.md` with the evidence.

## Finding the parent filing

The notice does not link to the filing that reports the holdings. You will have to work
out which filing that is, from what the notice tells you and what is on record for the
managers involved.

The parent may not be one of the twenty funds on the roster. If it is not, you will need
to fetch it — the same rate limits and User-Agent requirements from Chapter 1 apply.

## What you produce

`output/bonus_attributed.parquet` — the `holdings.parquet` schema plus one column:

| Column | Type | Description |
|---|---|---|
| `attributed_to_cik` | `string` | CIK of the notice-filing manager these rows belong to, zero-padded to 10 characters |

`accession_number` remains the accession of the filing the rows were actually filed in,
not the notice. The rows are real positions from a real filing; `attributed_to_cik`
records who they belong to.

## How this is graded

| | Points |
|---|---|
| **Parent identification** — the right filing located, by a method you can explain | 2 |
| **Attribution** — the correct rows extracted, the parent's own holdings excluded | 2 |
| **Reasoning** — what you concluded and why, documented with evidence | 1 |

Getting zero rows and explaining convincingly why scores better than getting plausible
rows you cannot justify. If the data does not support attribution, saying so with
evidence is the correct answer.
