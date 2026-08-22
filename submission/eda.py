"""
eda.py — Chapter 2 interrogation of the Chapter 1 downloads.

Runs against output/filings/{cik}/{accession}.xml (information table) and
output/filings/{cik}/{accession}.cover.xml (cover page) — the 40 filings
downloaded in Chapter 1, one of which (Pershing Square's Q2 2026 filing) is a
13F-NT notice with a cover page but no information table — plus one
supplementary example fetched live (through fetch()'s cache) for a case the
curated 40 does not contain: a real 13F-HR/A amendment pair.

Run:
    python3 submission/eda.py

FINDINGS
--------

1. Two-table split is not optional. Pershing Square Capital Management, L.P.
   (CIK 1336528) filed a 13F-NT for periodOfReport 2026-06-30 — a notice with
   a cover page and *zero* information-table rows, whose otherManager points
   at PERSHING SQUARE INC. (CIK 2026053) as the entity that actually reports
   the holdings. A flat join on accession_number would make this filer
   vanish for Q2 2026 instead of showing "filed, reported nothing, see other
   manager." (Chapter 1's discover_filings.py originally resolved this
   notice to the parent's real holdings; that was reverted once Chapter 3's
   schema made clear the notice itself must be the row — see
   submission/ASSUMPTIONS.md.)

2. The common-address namespace uses three different prefixes across our 40
   cover pages: `ns1:` (28 files), `com:` (9 files), `common:` (3 files) — all
   bound to the same URI, http://www.sec.gov/edgar/common. A parser that
   matches the literal string "com:street1" silently drops address fields on
   28/40 filings. Must resolve by namespace URI, never by prefix text.

3. `crdNumber` is missing entirely (not empty) on 5/40 cover pages; `isAmendment`
   is missing entirely on 12/40. Both are legitimate omissions, not filing
   errors — code must use dict-style `.get(..., default)` access, never
   assume the key exists.

4. There are two, easily-conflated "other manager" lists on the cover page:
   `otherManagersInfo` (singular reporting relationship — e.g. Millennium's
   filing names WORLDQUANT MILLENNIUM ADVISORS LLC here) and
   `otherManagers2Info` inside `summaryPage` (the numbered list that pairs
   with `otherIncludedManagersCount` and that positions in the information
   table point back into via their own `otherManager` sequence number).
   Confusing the two breaks the notice -> holdings linkage the spec describes.

5. `otherManager` entries do not always carry a CIK. Balyasny Asset
   Management's Q2 2026 filing lists "Longaeva Partners L.P." with only a
   `crdNumber`, no `cik`. Any lookup keyed purely on CIK will fail silently
   for entries like this.

6. Per-position `otherManager` (in the information table) is handled two
   different ways across filers: 13/40 filings populate it with a real
   sequence number (1, 2, ...); the rest either omit the element entirely, or
   — as with Renaissance Technologies, whose cover page declares
   `otherIncludedManagersCount=0` — fill every row with the literal text "0".
   Missing-element and explicit-zero both mean "no other manager," but a
   parser that only checks for element absence will miss the explicit-zero
   filers, and one that does `int(otherManager)` unconditionally will crash
   on the filers that omit it.

7. `tableEntryTotal` (declared) matches the actual `infoTable` row count
   exactly in all 40 filings examined — a properly namespace-aware XML count
   agrees every time. (An early, string-regex version of this same check
   silently double-counted by matching both opening and closing tags — a
   reminder that even the *validation* code needs to parse XML properly, not
   pattern-match it.)

8. 38 of the 39 filings that carry an information table contain CINS-style
   CUSIPs (a letter-leading 9-character identifier for a foreign issuer) —
   11,137 of 134,650 positions system-wide (~8.3%), with observed prefixes
   across the full alphabet-ish range (G, H, M, N, Y and more). The one
   filing with zero CINS positions is Pershing Square's own small,
   concentrated Q1 portfolio (11 positions total) — the absence tracks
   portfolio size, not a rule that CINS never appears. Coercing `cusip` to a
   number would corrupt roughly 1 in 12 rows across nearly every filer.

9. The voting-authority "none" column is a literal XML element named `None`
   (`<None>0</None>`), colliding with Python's `None` keyword/sentinel if a
   parser maps tag names directly onto identifiers or uses the tag string
   interchangeably with the Python singleton. Within our 40 filings, `Sole` /
   `Shared` / `None` are consistently title-cased and always ordinary
   integers — but that consistency is observed, not guaranteed by the schema.

10. `putCall` is present (has actual PUT/CALL positions) in 21/40 filings and
    entirely absent — not empty — in the other 19. Where present, both the
    element name (`putCall`) and values (`Put`/`Call`) are consistently
    cased in our sample of 20 managers; the spec's warning that filers
    disagree on capitalisation should still be treated as a live risk once
    the roster grows past these 20.

11. `figi` is present in only 7/40 filings, confirming it is the exception,
    not the rule, even post-2023.

12. `name_of_issuer` carries raw XML entities in the source — e.g.
    "S&amp;P GLOBAL INC" and "ABERCROMBIE &amp; FITCH CO" — that a proper XML
    parser decodes to "&" automatically. Treating the file as plain text
    (e.g. regex-scraping instead of parsing) leaves the literal "&amp;" in
    the data.

13. A real amendment pair proves `amendment_type` is not cosmetic: Tudor
    Investment Corp (CIK 923093, periodOfReport 2025-09-30) filed two
    amendments on the same day — amendmentNo 1 is a RESTATEMENT, amendmentNo
    2 is NEW HOLDINGS. A parser that treats both the same way either
    double-counts positions (NEW HOLDINGS on top of the original) or silently
    drops the restated numbers.

14. `fund_name` vs `filing_manager` really do diverge, not just in theory:
    our own roster calls CIK 923093 "Tudor Investment Corp"; the cover page's
    `filingManager.name` is "TUDOR INVESTMENT CORP ET AL". Joining back to
    the researcher's roster on `filing_manager` instead of `fund_name` would
    fail this row.

15. Our own Chapter 1 output is never zero-padded, which is exactly the trap
    the schema note warns about: every `cik` in `output/filings.csv` is a raw
    6-7 digit string straight from the roster (e.g. `923093`), with no
    padding at all. Chapter 3's parser must call `.zfill(10)` unconditionally
    on every row on the way in — the source format can never be trusted as-is,
    regardless of how it looked in the source column.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from fetch import fetch, set_user_agent  # noqa: E402

# Required by SEC on every request, including the supplementary live fetch
# below. Filled in here (not a placeholder) so this script runs end-to-end
# with no manual editing, per the Chapter 2 spec.
set_user_agent("Hsuan-Yu Shih hsuanyu5@illinois.edu")

FILINGS_DIR = Path(__file__).resolve().parent.parent / "output" / "filings"

# Supplementary examples outside the curated 40 (which deliberately excludes
# notices/amendments): a real 13F-NT (Pershing Square, Q2 2026) and a real
# amendment pair (Tudor, 2025 Q3).
NOTICE_EXAMPLE = ("1336528", "0001172661-26-003777")
AMENDMENT_EXAMPLES = [
    ("923093", "0000902664-25-005239"),  # amendmentNo 1: RESTATEMENT
    ("923093", "0000902664-25-005240"),  # amendmentNo 2: NEW HOLDINGS
]
ARCHIVE_DOC_URL_TMPL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{doc}"


def _archive_url(cik: str, accession: str, doc: str) -> str:
    return ARCHIVE_DOC_URL_TMPL.format(
        cik_int=int(cik), accession_nodash=accession.replace("-", ""), doc=doc,
    )


def localname(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def find_local(elem: ET.Element, name: str) -> ET.Element | None:
    """Find the first descendant (recursive) whose local name matches, regardless of namespace/prefix."""
    for child in elem.iter():
        if localname(child.tag) == name:
            return child
    return None


def findall_local(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in elem.iter() if localname(child.tag) == name]


def direct_children_local(elem: ET.Element, name: str) -> list[ET.Element]:
    """
    Only match direct children with this local name -- no recursion.
    Both otherManagersInfo/otherManager and
    otherManagers2Info/otherManager2/otherManager contain elements named
    otherManager; elem.iter() would conflate the two lists. This stays
    scoped to one level so the two lists are kept separate.
    """
    return [child for child in elem if localname(child.tag) == name]


def text_of(elem: ET.Element, name: str, default: str | None = None) -> str | None:
    found = find_local(elem, name)
    if found is None or found.text is None:
        return default
    return found.text


def iter_filing_pairs():
    """Yield the 40 (cik, accession, cover_path, info_path) tuples downloaded in Chapter 1, in order."""
    for cover_path in sorted(FILINGS_DIR.glob("*/*.cover.xml")):
        accession = cover_path.name[: -len(".cover.xml")]
        info_path = cover_path.parent / f"{accession}.xml"
        yield cover_path.parent.name, accession, cover_path, info_path


def section_schema_mapping() -> None:
    print("=" * 78)
    print("1. Schema mapping — one filing, every filings.parquet column traced to source")
    print("=" * 78)

    cik, accession, cover_path, info_path = next(iter_filing_pairs())
    root = ET.parse(cover_path).getroot()

    cik_text = text_of(root, "cik")
    report_period = text_of(root, "periodOfReport")
    filing_manager = text_of(root, "name")  # first <name> is filingManager.name
    form_type = text_of(root, "submissionType")
    is_amendment = text_of(root, "isAmendment", "(element absent -> not an amendment)")
    table_entry_total = text_of(root, "tableEntryTotal")
    table_value_total = text_of(root, "tableValueTotal")
    other_included = text_of(root, "otherIncludedManagersCount")

    print(f"file: {cover_path.relative_to(FILINGS_DIR.parent.parent)}")
    print(f"  cik                          <- headerData/filerInfo/filer/credentials/cik = {cik_text!r} (string, keep leading zeros)")
    print(f"  report_period                <- filerInfo/periodOfReport               = {report_period!r}")
    print(f"  report_quarter               <- DERIVED from report_period, not parsed from any element")
    print(f"  filing_manager               <- coverPage/filingManager/name           = {filing_manager!r}")
    print(f"  form_type / report_type      <- headerData/submissionType, coverPage/reportType = {form_type!r}")
    print(f"  is_amendment                 <- coverPage/isAmendment                  = {is_amendment!r}")
    print(f"  table_entry_total/value_total<- summaryPage/tableEntryTotal,tableValueTotal = {table_entry_total!r} / {table_value_total!r}")
    print(f"  other_included_managers_count<- summaryPage/otherIncludedManagersCount = {other_included!r}")
    print(f"  filing_date                  <- NOT on the cover page at all; only known from the")
    print(f"                                   EDGAR index/submissions API (output/filings.csv), not this XML")
    print()


def section_namespace_prefixes() -> None:
    print("=" * 78)
    print("2. Cover-page namespace prefixes used for the same common-address URI")
    print("=" * 78)

    prefix_counts: Counter[str] = Counter()
    common_uri = "http://www.sec.gov/edgar/common"
    for _cik, _accession, cover_path, _info_path in iter_filing_pairs():
        text = cover_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(rf'xmlns:(\w+)="{re.escape(common_uri)}"', text)
        prefix_counts[m.group(1) if m else "(no explicit prefix found)"] += 1

    for prefix, count in prefix_counts.most_common():
        print(f"  prefix {prefix!r:>10} used in {count} cover pages (all bind to {common_uri})")
    print("  -> a parser keyed on a literal prefix string (e.g. 'com:street1') breaks on the others.")
    print()


def section_optional_cover_fields() -> None:
    print("=" * 78)
    print("3. Optional cover-page fields: present vs entirely absent")
    print("=" * 78)

    total = 0
    missing_crd = missing_is_amendment = 0
    for _cik, _accession, cover_path, _info_path in iter_filing_pairs():
        total += 1
        root = ET.parse(cover_path).getroot()
        if find_local(root, "crdNumber") is None:
            missing_crd += 1
        if find_local(root, "isAmendment") is None:
            missing_is_amendment += 1

    print(f"  crdNumber   absent on {missing_crd}/{total} cover pages")
    print(f"  isAmendment absent on {missing_is_amendment}/{total} cover pages")
    print("  -> both are legitimate omissions; code must use .get(default), never assume the key exists.")
    print()


def section_other_manager_lists() -> None:
    print("=" * 78)
    print("4/5. otherManagersInfo vs otherManagers2Info, and missing CIKs on otherManager entries")
    print("=" * 78)

    for cik, accession, cover_path, _info_path in iter_filing_pairs():
        root = ET.parse(cover_path).getroot()
        cover_info = find_local(root, "otherManagersInfo")
        cover_others = direct_children_local(cover_info, "otherManager") if cover_info is not None else []
        summary_info = find_local(root, "otherManagers2Info")
        summary_others = direct_children_local(summary_info, "otherManager2") if summary_info is not None else []
        if not cover_others and not summary_others:
            continue

        print(f"  CIK {cik} accession {accession}:")
        for om in cover_others:
            name = text_of(om, "name")
            has_cik = find_local(om, "cik") is not None
            print(f"    otherManagersInfo/otherManager      name={name!r} has_cik={has_cik}")
        for om2 in summary_others:
            inner = find_local(om2, "otherManager")
            name = text_of(inner, "name") if inner is not None else None
            seq = text_of(om2, "sequenceNumber")
            print(f"    summaryPage/otherManagers2Info/[{seq}] name={name!r}")
    print("  -> these are two different lists; conflating them breaks the notice -> holdings link.")
    print()


def section_table_entry_total_check() -> None:
    print("=" * 78)
    print("6/7. Declared tableEntryTotal vs actual infoTable row count (proper XML parse)")
    print("=" * 78)

    mismatches = 0
    zero_other_manager_examples: list[tuple[str, str]] = []
    populated_other_manager_files = 0
    total = 0
    notices_without_info_table = 0

    for cik, accession, cover_path, info_path in iter_filing_pairs():
        total += 1
        cover_root = ET.parse(cover_path).getroot()
        declared = text_of(cover_root, "tableEntryTotal")
        other_included = text_of(cover_root, "otherIncludedManagersCount")

        if not info_path.exists():
            # A 13F-NT notice has no information table by design, so
            # download_filings.py never wrote this file. Consistent with
            # declared=None (table_entry_total should be null) -- not a failure.
            notices_without_info_table += 1
            assert declared is None, f"CIK {cik} accession {accession}: expected null tableEntryTotal on a notice, got {declared!r}"
            continue

        info_root = ET.parse(info_path).getroot()
        rows = findall_local(info_root, "infoTable")
        actual = len(rows)
        if declared is not None and int(declared) != actual:
            mismatches += 1
            print(f"  MISMATCH CIK {cik} accession {accession}: declared={declared} actual={actual}")

        other_manager_values = {text_of(r, "otherManager") for r in rows}
        other_manager_values.discard(None)
        if other_manager_values and other_manager_values != {"0"}:
            populated_other_manager_files += 1
        elif other_manager_values == {"0"} and other_included == "0":
            zero_other_manager_examples.append((cik, accession))

    print(f"  tableEntryTotal mismatches: {mismatches}/{total - notices_without_info_table} filings with an info table "
          f"(0 means declared counts were reliable in this sample)")
    print(f"  notices with no local info-table file at all: {notices_without_info_table} "
          f"(expected — a 13F-NT has none; its table_entry_total is null, matching)")
    print(f"  filings with real per-position otherManager sequence numbers: {populated_other_manager_files}/{total - notices_without_info_table}")
    if zero_other_manager_examples:
        cik, accession = zero_other_manager_examples[0]
        print(f"  example of explicit-zero otherManager + otherIncludedManagersCount=0: CIK {cik} accession {accession}")
    print()


def section_cusip_cins() -> None:
    print("=" * 78)
    print("8. CUSIP vs CINS (letter-leading identifiers for foreign issuers)")
    print("=" * 78)

    total_rows = 0
    letter_rows = 0
    files_with_letter = 0
    prefixes: Counter[str] = Counter()

    for _cik, _accession, _cover_path, info_path in iter_filing_pairs():
        if not info_path.exists():
            continue  # a 13F-NT notice has no information table
        root = ET.parse(info_path).getroot()
        cusips = [text_of(row, "cusip") for row in findall_local(root, "infoTable")]
        cusips = [c for c in cusips if c]
        total_rows += len(cusips)
        letters = [c for c in cusips if c[0].isalpha()]
        letter_rows += len(letters)
        if letters:
            files_with_letter += 1
            prefixes.update(c[0] for c in letters)

    print(f"  {letter_rows}/{total_rows} positions ({letter_rows / total_rows:.1%}) have a letter-leading CUSIP (CINS)")
    print(f"  present in {files_with_letter}/39 filings that carry an information table "
          f"(the 40th is the 13F-NT notice, which has none)")
    print(f"  observed leading letters: {dict(prefixes)}")
    print("  -> coercing cusip to a numeric type corrupts roughly 1 in 12 rows, in every filer.")
    print()


def section_voting_and_putcall() -> None:
    print("=" * 78)
    print("9/10/11. voting 'None' tag, putCall presence & casing, figi presence")
    print("=" * 78)

    voting_value_variants: Counter[str] = Counter()
    putcall_files_present = putcall_files_absent = 0
    putcall_values: Counter[str] = Counter()
    figi_files_present = 0
    files_with_info_table = 0

    for _cik, _accession, _cover_path, info_path in iter_filing_pairs():
        if not info_path.exists():
            continue  # a 13F-NT notice has no information table
        files_with_info_table += 1
        root = ET.parse(info_path).getroot()
        rows = findall_local(root, "infoTable")

        for row in rows:
            for tag in ("Sole", "Shared", "None"):
                el = find_local(row, tag)
                if el is not None:
                    voting_value_variants[tag] += 1

        putcalls = [text_of(row, "putCall") for row in rows]
        putcalls = [p for p in putcalls if p]
        if putcalls:
            putcall_files_present += 1
            putcall_values.update(putcalls)
        else:
            putcall_files_absent += 1

        if any(find_local(row, "figi") is not None for row in rows):
            figi_files_present += 1

    print(f"  voting element tags seen (should be exactly Sole/Shared/None once, per row): {dict(voting_value_variants)}")
    print(f"  putCall present in {putcall_files_present}/{files_with_info_table} filings, entirely absent in {putcall_files_absent}/{files_with_info_table}")
    print(f"  putCall value casing observed: {dict(putcall_values)}")
    print(f"  figi present in {figi_files_present}/{files_with_info_table} filings")
    print()


def section_entities() -> None:
    print("=" * 78)
    print("12. Raw XML entities in name_of_issuer")
    print("=" * 78)

    example_found = False
    for cik, accession, _cover_path, info_path in iter_filing_pairs():
        if not info_path.exists():
            continue  # a 13F-NT notice has no information table
        raw_text = info_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"nameOfIssuer>([^<]*&amp;[^<]*)<", raw_text)
        if m and not example_found:
            root = ET.parse(info_path).getroot()
            parsed_name = next(
                (text_of(row, "nameOfIssuer") for row in findall_local(root, "infoTable")
                 if text_of(row, "nameOfIssuer") and "&" in text_of(row, "nameOfIssuer")),
                None,
            )
            print(f"  CIK {cik} accession {accession}:")
            print(f"    raw XML text:   {m.group(1)!r}")
            print(f"    ET-parsed text: {parsed_name!r}")
            example_found = True
    print("  -> regex/text scraping leaves '&amp;' literal; a real XML parser decodes it to '&'.")
    print()


def section_cik_padding_in_our_own_output() -> None:
    print("=" * 78)
    print("15. Our own output/filings.csv cik column is never zero-padded")
    print("=" * 78)

    filings_csv = FILINGS_DIR.parent / "filings.csv"
    if not filings_csv.exists():
        print("  output/filings.csv not found — run discover_filings.py first.")
        return

    import csv
    with open(filings_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    lengths = Counter(len(r["cik"]) for r in rows)
    print(f"  cik string length distribution across {len(rows)} rows: {dict(lengths)}")
    print("  -> every cik here comes straight from the roster (6-7 raw digits, no padding")
    print("     at all) yet SCHEMA.md requires a zero-padded 10-character string. Chapter 3's")
    print("     parser must call .zfill(10) unconditionally on every row, not assume the")
    print("     source is already correctly formatted.")
    print()


def section_notice_example() -> None:
    print("=" * 78)
    print("A real 13F-NT notice, now part of our own 40 (Chapter 3 keeps it, unresolved)")
    print("=" * 78)
    cik, accession = NOTICE_EXAMPLE
    cover_path = FILINGS_DIR / cik / f"{accession}.cover.xml"
    info_path = FILINGS_DIR / cik / f"{accession}.xml"

    root = ET.parse(cover_path).getroot()
    submission_type = text_of(root, "submissionType")
    report_type = text_of(root, "reportType")
    table_entry_total = text_of(root, "tableEntryTotal")
    other_manager = find_local(root, "otherManager")
    other_manager_name = text_of(other_manager, "name") if other_manager is not None else None

    print(f"  CIK {cik} accession {accession}: submissionType={submission_type!r} report_type={report_type!r}")
    print(f"    tableEntryTotal element text: {table_entry_total!r} (empty/self-closed -> null, not zero)")
    print(f"    otherManager referenced: {other_manager_name!r}")
    print(f"    local info-table file exists: {info_path.exists()}")
    print("  -> this filing gets a filings.parquet row (table_entry_total/table_value_total")
    print("     null) and zero holdings.parquet rows. Chapter 1 originally resolved this")
    print("     notice to its parent's real holdings (CIK 2026053); Chapter 3's schema is")
    print("     explicit that the notice itself must be the row, so that resolution was")
    print("     removed from discover_filings.py (see submission/ASSUMPTIONS.md).")
    print()


def section_supplementary_amendment_example() -> None:
    print("=" * 78)
    print("Supplementary (live-fetched, cached) — a real 13F-HR/A amendment pair")
    print("=" * 78)
    for cik, accession in AMENDMENT_EXAMPLES:
        try:
            raw = fetch(_archive_url(cik, accession, "primary_doc.xml"))
        except Exception as exc:
            print(f"  could not fetch {accession} ({exc}); skipping.")
            continue
        root = ET.fromstring(raw)
        amendment_no = text_of(root, "amendmentNo")
        amendment_type = text_of(root, "amendmentType")
        report_period = text_of(root, "periodOfReport")
        print(f"  CIK {cik} accession {accession}: periodOfReport={report_period!r} "
              f"amendmentNo={amendment_no!r} amendmentType={amendment_type!r}")
    print("  -> same filer, same period, same day: one RESTATEMENT, one NEW HOLDINGS.")
    print("     Treating them identically double-counts one and discards the other.")
    print()


def main() -> int:
    if not FILINGS_DIR.exists() or not any(FILINGS_DIR.glob("*/*.cover.xml")):
        print(f"No filings found under {FILINGS_DIR} -- run Chapter 1's scripts first.", file=sys.stderr)
        return 1

    section_schema_mapping()
    section_namespace_prefixes()
    section_optional_cover_fields()
    section_other_manager_lists()
    section_table_entry_total_check()
    section_cusip_cins()
    section_voting_and_putcall()
    section_entities()
    section_cik_padding_in_our_own_output()
    section_notice_example()
    section_supplementary_amendment_example()

    print("=" * 78)
    print("See the FINDINGS block in this file's module docstring for the full write-up.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())