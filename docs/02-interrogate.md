# 2 · Interrogate

**5 points** · Produces `submission/eda.py`

---

You have the XML. Before you write a parser, your tech lead wants a conversation about
what you are parsing into — and what you found while looking.

> "Nice work on the download. Before you write the parser, two things — and the second
> one is where the real value is.
>
> First, here's the schema the researcher needs. Give it a proper read, because a few
> columns aren't what you'd guess from their names, and a couple exist specifically
> because this data is messier than it looks. If any of it doesn't make sense, ask —
> better now than after you've built around a wrong assumption.
>
> Second, go and look at the actual files. Not all of them: pick a handful across
> different managers and read the raw XML. What I'm after is what's going to break.
> Somewhere in there a filer has done something perfectly reasonable that our parser
> won't expect, and finding it now is worth a lot more than finding it at two in the
> morning when the pipeline falls over.
>
> Write down whatever you find. If we know about it, we can build for it once instead of
> patching it five times."

---

## 2.1 · Why two tables

The schema asks for `filings.parquet` and `holdings.parquet`, joined on
`accession_number`. It would be simpler to write one flat table, and that simplicity is
exactly the trap.

Some managers in your roster file a **13F-NT** — a notice saying their holdings are
reported inside another manager's filing rather than their own. A notice has a cover
page and no information table. Flatten the two together and that filing produces zero
rows and disappears: your output would show a manager who filed nothing, when in fact
they filed something that said "look elsewhere."

Splitting the grain keeps every filing represented whether or not it carries positions.
That is a general principle worth internalising — *the absence of data is itself data*,
and a schema that cannot represent it will quietly lie.

---

## 2.2 · The filing record

Most of `filings.parquet` comes off the cover page. A few columns are worth flagging
because they are where assumptions go to die.

**`cik` is a string, not an integer.** Zero-padded to ten characters. The moment you
parse it as a number you lose the leading zeros, and every join against a padded source
fails. Same for `crd_number`.

**`report_period` and `filing_date` are different things.** The first is the quarter the
holdings describe; the second is when EDGAR accepted the document. A manager has 45 days
after quarter end to file, and an amendment filed later still carries the original
report period. Confusing them produces a plausible dataset describing the wrong quarters.

**`fund_name` and `filing_manager` will not always agree.** The first is what the
researcher called the fund; the second is the legal entity on the cover page. Keep both —
`fund_name` is how she joins back to her roster, `filing_manager` is what the filing
actually says. Silently replacing one with the other breaks her workflow.

**`amendment_type` carries real semantics.** A `RESTATEMENT` replaces its original in
full; `NEW HOLDINGS` adds to it. Treating those identically double-counts one case and
discards the other. You do not have to resolve amendments in this chapter — but notice
now that the distinction exists, because Chapter 3 will ask you to act on it.

**`table_entry_total` and `table_value_total` are declared, not computed.** They are what
the manager said was in the table. Whether they match what is actually in the table is a
question, not an assumption — and a useful one to check.

**`other_included_managers_count` is the other half of a relationship.** It says how many
managers' holdings are folded into this filing. When it is greater than zero, the cover
page carries a list of those managers, and positions in the information table point back
at that list. This is the mechanism that connects a notice filing to the holdings that
actually represent it — worth understanding now.

The remaining cover-page fields are more direct. `form_type` and `report_type` classify
the filing (`13F-HR` versus `13F-NT`, holdings report versus notice versus combination).
`is_amendment` and `amendment_no` follow from the form type and the cover page.
`form_13f_file_number`, `sec_file_number`, and `crd_number` are regulatory identifiers —
all strings, all with significant leading characters.

**`report_quarter` is derived, not parsed.** Nothing in the filing states `2026Q1`; you
compute it from `report_period`. It appears in both tables — denormalized into
`holdings.parquet` alongside `cik` so the common queries do not need a join. Worth
noticing that the schema does this deliberately: a little redundancy in exchange for a
much easier table to query.

---

## 2.3 · The holdings record

`holdings.parquet` is one row per position, and the fields are mostly what they sound
like. The ones that are not:

**`cusip` is a nine-character string.** Leading zeros are significant and must survive.
Not all CUSIPs are numeric — a value starting with a letter is a CINS code identifying a
foreign issuer, and it is valid. Anything that coerces this field to a number is wrong
in two directions at once.

**`value` is whole dollars.** Before Q1 2023, Form 13F reported values in thousands.
Everything in your scope is post-change, so this is one trap you have been spared — but
it is worth knowing the boundary exists if you ever extend this dataset backwards.

**`ssh_prnamt` means two different things.** A share count or a principal amount,
depending on `ssh_prnamt_type`. Summing across both without checking the type adds
shares to dollars.

**`put_call` is absent, not empty, for ordinary positions.** The element simply is not
there. And filers do not agree on how to capitalise it when it is.

**`other_manager` is a reference, not a name.** It points at something the cover page
defines. Working out what it points at, and what that implies for a position's ownership,
is the thread that connects notice filings to the holdings that actually represent them.

**`voting_none` comes from an XML element named `None`.** In some languages that is a
reserved word or a null-like literal, and naive handling turns a legitimate zero into a
missing value. Its siblings `voting_sole` and `voting_shared` are ordinary integers.

**`name_of_issuer` and `title_of_class` are free text, filed as typed.** No manager
standardises against any registry, so the same issuer appears under several spellings
across filings, and the class field ranges from `COM` to a full bond description. XML
entities in these fields need decoding — `&amp;` is an ampersand, not four characters.

**`figi` is usually absent.** An optional identifier added to Form 13F in 2023. Present
in some filings, missing in most.

**`investment_discretion`** records who decides: `SOLE`, `DFND`, or `OTR`. Read it
alongside `other_manager` and the voting columns — together they describe who actually
controls a position, which is not always the manager whose name is on the filing.

---

## 2.4 · Go and look

Now open the files.

Pick filings across several managers — a large multi-manager platform, a small
concentrated fund, an amendment, a notice — and read the raw XML. You are looking for
two things:

**Can you map every schema column to something in the source?** Where a column has no
obvious source, say so. Some are derived rather than parsed.

**What will break?** This is the part that matters. Filers using different namespace
prefixes for the same schema. Fields present in one filing and absent in another.
Encodings, entities, formatting that differs between filers. Values that are technically
valid and will still break a reasonable parser. Counts that disagree with what the cover
page declares.

You are not fixing any of it yet. You are finding it, so that Chapter 3 can be written
once rather than patched repeatedly.

---

## What you produce

### `submission/eda.py`

A runnable script — the exploration you actually did, not a cleaned-up retelling. It
should run against the filings you downloaded in Chapter 1 and print what it found.

Structure is yours. What we look for:

- **It runs.** Against `output/filings/`, without manual editing.
- **It shows the evidence.** A claim about the data should be backed by output — counts,
  examples, the specific filing where you saw it.
- **The findings are stated.** In a module docstring, a `FINDINGS` block, or printed at
  the end. Somewhere a reader gets your conclusions without reverse-engineering them
  from the code.

A worked observation looks like this, not like a checklist item:

> Cover page `tableEntryTotal` disagrees with the number of `infoTable` elements in
> N of the filings examined — for example accession X declares 412 and contains 411.
> Treating the declared count as authoritative would silently drop a position; treating
> it as a validation check surfaces the discrepancy instead.

That paragraph tells a colleague what you found, how much it happens, where to look, and
what it means for the parser. That is the standard.

---

## How this chapter is graded

| | Points |
|---|---|
| **Schema comprehension** — every column mapped to a source, derived fields identified as derived, ambiguous fields correctly interpreted | 2 |
| **Data understanding** — real discrepancies found, evidenced, and explained in terms of what they mean for a parser | 3 |

The weighting is deliberate. Mapping a schema is careful reading. Finding the thing that
will break your parser three days from now is the harder skill, and the one this role
runs on.

---

Next: [3 · Structure](03-structure.md)
