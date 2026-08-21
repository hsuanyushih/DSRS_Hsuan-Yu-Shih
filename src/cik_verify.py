"""
cik_verify.py -- verify the CIKs in filers.csv and write output/filers.csv.

Process:
    1. Download the official SEC CIK lookup table (cik-lookup-data.txt) and save it
       as a local CSV. This happens once; later runs reuse the local file.
    2. Build a lookup index: normalized core name -> [(original name, cik), ...]
    3. Reconcile each row in filers.csv:
         - given CIK is among the candidates -> cik_source = "given"
         - given CIK is not a candidate, but the core name has one candidate
           -> cik_source = "corrected"
         - no candidates or multiple candidates -> log it for manual review
    4. Write output/filers.csv sorted by ascending CIK.

Usage (always run from the project root):
    python3 src/cik_verify.py
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sys
from pathlib import Path

from fetch import fetch

logger = logging.getLogger(__name__)

CIK_LOOKUP_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
# cik-lookup-data.txt is only a static name lookup; one name may map to several real CIKs.
# Use the live API below to determine which CIK actually files 13F reports.
SUBMISSIONS_URL_TMPL = "https://data.sec.gov/submissions/CIK{cik}.json"
LOOKUP_CSV_PATH = Path("output/cik_lookup.csv")
FILERS_INPUT_PATH = Path("filers.csv")          # original roster
FILERS_OUTPUT_PATH = Path("output/filers.csv")   # chapter output

# Common legal suffixes. Matching uses the core name without these suffixes.
SUFFIX_WORDS = {"LLC", "LP", "LLP", "INC", "CORP", "CO", "LTD", "PLC"}

# Common formatting quirks in the SEC lookup table:
#   1. A "/state abbreviation" disambiguates companies with the same name, e.g.
#      "BAUPOST GROUP LLC/MA".
#   2. Our roster occasionally contains parenthetical notes, e.g.
#      "DME Capital Management LP (Greenlight)". These are human-facing notes,
#      not part of the legal name, so remove them before matching.
STATE_SUFFIX_RE = re.compile(r"/[A-Z]{2}$")
PAREN_RE = re.compile(r"\([^)]*\)")
# SEC uses "ET AL" to indicate that a CIK files for an affiliated group,
# e.g. "TUDOR INVESTMENT CORP ET AL". It is not part of the company name.
ET_AL_RE = re.compile(r"\bET AL\b")

# ---------------------------------------------------------------------------
# Step 1: download and parse the official CIK lookup table
# ---------------------------------------------------------------------------

def download_and_cache_lookup() -> Path:
    """
    Download cik-lookup-data.txt through fetch() and parse it into
    output/cik_lookup.csv. If the CSV already exists, skip parsing to speed up reruns.
    """
    if LOOKUP_CSV_PATH.exists():
        logger.info("cik_lookup.csv already exists, skipping re-parse: %s",
                    LOOKUP_CSV_PATH)
        return LOOKUP_CSV_PATH

    logger.info("Fetching CIK lookup file from SEC...")
    raw = fetch(CIK_LOOKUP_URL)
    text = raw.decode("latin-1")  # SEC's file is not UTF-8; latin-1 avoids decode errors

    LOOKUP_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOOKUP_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "cik"])
        count = 0
        for line in text.splitlines():
            line = line.rstrip()
            if not line:
                continue
            # Format: "COMPANY NAME:CIK:"
            parts = line.split(":")
            if len(parts) < 2:
                continue
            name, cik = parts[0], parts[1]
            if not cik.strip().isdigit():
                continue
            writer.writerow([name, cik.strip().zfill(10)])
            count += 1

    logger.info("Parsed %d rows into %s", count, LOOKUP_CSV_PATH)
    return LOOKUP_CSV_PATH


# ---------------------------------------------------------------------------
# Step 2: name normalization and layered matching
# ---------------------------------------------------------------------------

def strip_punctuation(name: str) -> str:
    n = name.upper().strip()
    n = STATE_SUFFIX_RE.sub("", n)   # remove SEC disambiguation suffixes such as "/MA"
    n = PAREN_RE.sub("", n)          # remove parenthetical notes such as "(Greenlight)"
    n = ET_AL_RE.sub("", n)          # remove the group-filing marker "ET AL"
    n = n.replace("&", "AND")
    n = re.sub(r"[^\w\s]", "", n)    # remove punctuation, preserve letters/numbers/spaces
    n = re.sub(r"\s+", " ", n).strip()
    return n


def split_core_and_suffix(name: str) -> tuple[str, str | None]:
    """
    'Balyasny Asset Management L.P.' -> ('BALYASNY ASSET MANAGEMENT', 'LP')
    'The Baupost Group LLC' -> ('BAUPOST GROUP', 'LLC')  # leading THE is not part of the core
    If no known suffix is found, suffix is None and core is the full normalized name.
    """
    tokens = strip_punctuation(name).split(" ")
    if tokens and tokens[0] == "THE":
        tokens = tokens[1:]
    if tokens and tokens[-1] in SUFFIX_WORDS:
        return " ".join(tokens[:-1]), tokens[-1]
    return " ".join(tokens), None

def fetch_filer_summary(cik: str) -> dict | None:
    """
    Query the live SEC submissions API and return this CIK's registered name plus
    its 13F-HR filing count/date range. This is practical evidence for choosing the
    correct candidate CIK instead of relying only on static lookup text.
    """
    url = SUBMISSIONS_URL_TMPL.format(cik=cik)
    try:
        raw = fetch(url)
    except Exception as exc:
        logger.warning("Failed to query %s: %s", url, exc)
        return None

    data = json.loads(raw)
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    thirteen_f_dates = [d for f, d in zip(forms, dates) if f.startswith("13F")]

    return {
        "name": data.get("name"),
        "thirteen_f_count": len(thirteen_f_dates),
        "thirteen_f_earliest": min(thirteen_f_dates, default=None),
        "thirteen_f_latest": max(thirteen_f_dates, default=None),
    }


def build_core_index(lookup_csv: Path) -> dict[str, list[tuple[str, str]]]:
    """
    Read output/cik_lookup.csv and build a core_name -> [(original SEC name, cik)] index.
    The index may be large, so build it once as a dict for O(1) lookups later.
    """
    index: dict[str, list[tuple[str, str]]] = {}
    with open(lookup_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            core, _suffix = split_core_and_suffix(row["name"])
            if not core:
                continue
            index.setdefault(core, []).append((row["name"], row["cik"]))
    return index


# ---------------------------------------------------------------------------
# Step 3: reconcile each roster row
# ---------------------------------------------------------------------------

def reconcile(filers_path: Path, core_index: dict) -> list[dict]:
    """
    Find matching core-name candidates for each filers.csv row, determine cik_source,
    and separately mark uncertain cases for manual review.
    """
    results = []
    needs_review = []

    with open(filers_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fund_name = row["fund_name"].strip()
            given_cik = row["cik"].strip().zfill(10)

            core, suffix = split_core_and_suffix(fund_name)
            candidates = core_index.get(core, [])
            candidate_ciks = {cik for _name, cik in candidates}

            if given_cik in candidate_ciks:
                cik_source = "given"
                final_cik = given_cik
            elif len(candidate_ciks) == 1:
                # The core name maps to one CIK, and it differs from the given value.
                final_cik = next(iter(candidate_ciks))
                cik_source = "corrected"
            else:
                # Zero or multiple candidates are not reliable for automatic resolution.
                final_cik = given_cik
                cik_source = "NEEDS_REVIEW"
                needs_review.append({
                    "fund_name": fund_name,
                    "given_cik": given_cik,
                    "core": core,
                    "candidates": candidates,
                })

            results.append({
                "fund_name": fund_name,
                "cik": final_cik.lstrip("0") or "0",  # output without leading zeros per Chapter 1
                "cik_source": cik_source,
            })

    if needs_review:
        logger.warning(
            "%d row(s) need manual review (candidate count != 1); querying the SEC submissions API for evidence:",
            len(needs_review),
        )
        for item in needs_review:
            logger.warning(
                "  fund_name=%r given_cik=%s core=%r candidates=%s",
                item["fund_name"], item["given_cik"], item["core"],
                item["candidates"],
            )
            # Also check the given CIK because it may not be in the candidate list.
            ciks_to_check = {cik for _name, cik in item["candidates"]}
            ciks_to_check.add(item["given_cik"])
            for cik in sorted(ciks_to_check):
                summary = fetch_filer_summary(cik)
                if summary is None:
                    continue
                logger.warning(
                    "    CIK %s -> name=%r, %d 13F-HR filing(s) (%s ~ %s)",
                    cik, summary["name"], summary["thirteen_f_count"],
                    summary["thirteen_f_earliest"], summary["thirteen_f_latest"],
                )

    return results


# ---------------------------------------------------------------------------
# Step 4: output
# ---------------------------------------------------------------------------

def write_output(results: list[dict], out_path: Path) -> None:
    # Sort CIKs in ascending order as required by the specification.
    results_sorted = sorted(results, key=lambda r: int(r["cik"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["fund_name", "cik", "cik_source"])
        writer.writeheader()
        for row in results_sorted:
            writer.writerow({
                "fund_name": row["fund_name"],
                "cik": row["cik"],
                "cik_source": row["cik_source"],
            })
    logger.info("Wrote %d rows to %s", len(results_sorted), out_path)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not FILERS_INPUT_PATH.exists():
        logger.error(
            "Cannot find %s -- place the original filers.csv in the project root and run again.",
            FILERS_INPUT_PATH,
        )
        return 1

    lookup_csv = download_and_cache_lookup()
    core_index = build_core_index(lookup_csv)
    results = reconcile(FILERS_INPUT_PATH, core_index)

    review_count = sum(1 for r in results if r["cik_source"] == "NEEDS_REVIEW")
    if review_count:
        logger.warning(
            "%d row(s) are marked NEEDS_REVIEW; this is not a final answer -- "
            "manually verify them, change each to given or corrected, and document "
            "your reasoning in submission/ASSUMPTIONS.md.",
            review_count,
        )

    write_output(results, FILERS_OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())