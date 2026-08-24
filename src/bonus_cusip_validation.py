"""bonus_cusip_validation.py

Bonus 2: check every CUSIP reported in the 2026 Q2 holdings against SEC's
Official List of Section 13(f) Securities for that quarter, and produce
output/bonus_cusip_validation.csv.

The official list is a plain-text file, not the same format as our stored
CUSIPs -- normalizing both sides before comparing is the first thing this
script does, and it's the step most likely to manufacture false mismatches
if skipped. See docs/bonus-02-cusip-validation.md.

Run (from the repo root, after Chapter 1-3 have produced output/*.parquet):
    python3 src/bonus_cusip_validation.py
"""

from __future__ import annotations

import csv
import logging
import re
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from fetch import fetch, set_user_agent

logger = logging.getLogger(__name__)

OFFICIAL_LIST_URL = "https://www.sec.gov/files/investment/13flist2026q2-txt.txt"
FILINGS_PATH = Path("output/filings.parquet")
HOLDINGS_PATH = Path("output/holdings.parquet")
OUTPUT_PATH = Path("output/bonus_cusip_validation.csv")

TARGET_QUARTER = "2026Q2"

# A CINS (foreign-security identifier) starts with a letter rather than a
# digit -- see docs/SCHEMA.md and submission/eda.py's finding #8. These are
# valid identifiers that simply aren't domestic CUSIPs, so they legitimately
# won't appear on SEC's list of 13(f)-reportable securities the same way.
CINS_LEADING_LETTER_RE = re.compile(r"^[A-Z]")


def _normalize_cusip(raw: str) -> str:
    """
    Strip everything but alphanumerics and uppercase. The official list is
    known to use inconsistent spacing/punctuation around the 9-character
    identifier; our own stored CUSIPs (SCHEMA.md) are already clean 9-char
    strings, but we run both sides through the same normalizer rather than
    assuming that.
    """
    return re.sub(r"[^A-Z0-9]", "", raw.upper())


def parse_official_list(raw_text: str) -> dict[str, str]:
    """
    Parse SEC's Official List of 13(f) Securities into {cusip: issuer_name}.

    This is a fixed-width column format, per SEC's own published spec
    (https://www.sec.gov/divisions/investment/13flists.htm):

        CUSIP Number         columns  1-9
        Option Indicator     column   10   ('*' or blank)
        Issuer Name          columns 11-40
        Issuer Description   columns 41-67
        Status               columns 68-70 ('A' additions, 'D' deletions, blank)

    Not whitespace-delimited -- splitting on runs of spaces silently breaks
    on any issuer name padded with fewer than two spaces, or on a name that
    happens to be immediately followed by a short description. Every row is
    sliced by fixed character offset instead. The file also carries several
    header/title lines before the data starts; any line whose first 9
    characters don't look like a CUSIP token is skipped rather than assumed
    to be a data row.
    """
    result: dict[str, str] = {}
    cusip_token_re = re.compile(r"^[A-Z0-9]{9}$")

    for line in raw_text.splitlines():
        if len(line) < 40:
            continue
        cusip_field = line[0:9]
        issuer_field = line[10:40]

        candidate_cusip = _normalize_cusip(cusip_field)
        if not cusip_token_re.match(candidate_cusip):
            continue

        issuer_name = issuer_field.strip()
        result[candidate_cusip] = issuer_name

    return result


def classify_unmatched(cusip: str, issuer_from_filing: str) -> str:
    """
    Best-effort classification for a CUSIP that didn't match the official
    list, after normalization has already been ruled out as the cause.
    This is a heuristic starting point, not a verdict -- see
    submission/ASSUMPTIONS.md for the manual review of each case.
    """
    if CINS_LEADING_LETTER_RE.match(cusip):
        return "CINS_FOREIGN"
    return "UNRESOLVED"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not HOLDINGS_PATH.exists() or not FILINGS_PATH.exists():
        logger.error(
            "output/*.parquet not found -- run Chapter 1-3 before this bonus."
        )
        return 1

    set_user_agent("Hsuan-Yu Shih hsuanyu5@illinois.edu")

    logger.info("Fetching official 13(f) securities list for %s...", TARGET_QUARTER)
    raw = fetch(OFFICIAL_LIST_URL).decode("latin-1")
    official = parse_official_list(raw)
    logger.info("Parsed %d securities from the official list", len(official))

    filings = pq.read_table(FILINGS_PATH).to_pandas()
    holdings = pq.read_table(HOLDINGS_PATH).to_pandas()

    q2_holdings = holdings[holdings["report_quarter"] == TARGET_QUARTER].copy()
    if q2_holdings.empty:
        logger.error("No holdings found for %s", TARGET_QUARTER)
        return 1

    q2_holdings["cusip_norm"] = q2_holdings["cusip"].map(_normalize_cusip)

    cik_to_name = filings.drop_duplicates("cik").set_index("cik")["fund_name"].to_dict()

    # One row per (accession_number, cusip) pair, per the bonus spec --
    # not one row per unique cusip, since the same CUSIP can be correct in
    # one filing and mistyped in another.
    grouped = (
        q2_holdings
        .groupby(["accession_number", "cusip", "cusip_norm"])
        .agg(
            cik=("cik", "first"),
            rows=("cusip", "size"),
            name_of_issuer=("name_of_issuer", "first"),
        )
        .reset_index()
    )

    output_rows = []
    matched = 0
    unmatched = 0

    for _, row in grouped.iterrows():
        cusip_norm = row["cusip_norm"]
        on_list = cusip_norm in official
        issuer_from_list = official.get(cusip_norm)

        if on_list:
            matched += 1
            assessment = None
        else:
            unmatched += 1
            assessment = classify_unmatched(row["cusip"], row["name_of_issuer"])

        output_rows.append({
            "accession_number": row["accession_number"],
            "cik": str(row["cik"]).zfill(10),
            "fund_name": cik_to_name.get(row["cik"], ""),
            "cusip": row["cusip"],
            "on_official_list": on_list,
            "issuer_from_filing": row["name_of_issuer"],
            "issuer_from_list": issuer_from_list,
            "rows": int(row["rows"]),
            "assessment": assessment,
        })

    output_rows.sort(key=lambda r: (r["accession_number"], r["cusip"]))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "accession_number", "cik", "fund_name", "cusip", "on_official_list",
        "issuer_from_filing", "issuer_from_list", "rows", "assessment",
    ]
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in output_rows:
            writer.writerow(row)

    logger.info(
        "Wrote %d rows to %s (%d matched, %d unmatched)",
        len(output_rows), OUTPUT_PATH, matched, unmatched,
    )

    # Print a summary of unmatched CUSIPs by assessment, so the console
    # output itself is usable evidence for ASSUMPTIONS.md.
    unmatched_rows = [r for r in output_rows if not r["on_official_list"]]
    by_assessment: dict[str, int] = {}
    for r in unmatched_rows:
        by_assessment[r["assessment"]] = by_assessment.get(r["assessment"], 0) + 1
    logger.info("Unmatched breakdown: %s", by_assessment)

    if by_assessment.get("UNRESOLVED"):
        logger.info(
            "UNRESOLVED CUSIPs (candidates for filer-error write-up in ASSUMPTIONS.md):"
        )
        for r in unmatched_rows:
            if r["assessment"] == "UNRESOLVED":
                logger.info(
                    "  %s | cusip=%s | issuer=%r | accession=%s",
                    r["fund_name"], r["cusip"], r["issuer_from_filing"],
                    r["accession_number"],
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())