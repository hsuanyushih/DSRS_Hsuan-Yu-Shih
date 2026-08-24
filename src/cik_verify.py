"""cik_verify.py

Verifies the CIKs in filers.csv against SEC's official name->CIK lookup
file and writes output/filers.csv.

Pipeline:
    1. Download SEC's CIK lookup file (cik-lookup-data.txt) once and cache
       it locally as CSV.
    2. Build a lookup index: normalized "core" company name -> list of
       (original SEC name, CIK) candidates.
    3. Reconcile each row in filers.csv against that index:
         - given CIK matches a candidate       -> cik_source = "given"
         - given CIK doesn't match, but exactly
           one candidate exists                -> cik_source = "corrected"
         - zero or multiple candidates          -> flagged for manual review
    4. Write output/filers.csv, sorted by CIK ascending.

"""

from __future__ import annotations

import csv
import logging
import re
import sys
from pathlib import Path

from fetch import fetch

logger = logging.getLogger(__name__)

CIK_LOOKUP_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
LOOKUP_CSV_PATH = Path("output/cik_lookup.csv")
FILERS_INPUT_PATH = Path("filers.csv")
FILERS_OUTPUT_PATH = Path("output/filers.csv")

# Common legal suffixes. The "core" name used for matching excludes these;
# the suffix is compared separately.
SUFFIX_WORDS = {"LLC", "LP", "LLP", "INC", "CORP", "CO", "LTD", "PLC"}

# Known quirks in SEC's lookup file / our own roster:
#   1. A trailing "/XX" state-abbreviation disambiguator, e.g.
#      "BAUPOST GROUP LLC/MA".
#   2. Parenthetical annotations in the roster that aren't part of the
#      legal name, e.g. "DME Capital Management LP (Greenlight)".
STATE_SUFFIX_RE = re.compile(r"/[A-Z]{2}$")
PAREN_RE = re.compile(r"\([^)]*\)")
# SEC uses "ET AL" to mark a CIK that reports on behalf of an affiliated
# group, e.g. "TUDOR INVESTMENT CORP ET AL" -- not part of the entity name.
ET_AL_RE = re.compile(r"\bET AL\b")


# ---------------------------------------------------------------------------
# Step 1: download and parse the official CIK lookup file
# ---------------------------------------------------------------------------

def download_and_cache_lookup() -> Path:
    """
    Download cik-lookup-data.txt (via fetch(), which caches on its own)
    and parse it into output/cik_lookup.csv. If that CSV already exists,
    skip re-parsing to speed up repeat runs.
    """
    if LOOKUP_CSV_PATH.exists():
        logger.info("cik_lookup.csv already exists, skipping re-parse: %s",
                    LOOKUP_CSV_PATH)
        return LOOKUP_CSV_PATH

    logger.info("Fetching CIK lookup file from SEC...")
    raw = fetch(CIK_LOOKUP_URL)
    text = raw.decode("latin-1")  # not UTF-8; latin-1 avoids decode errors

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
# Step 2: name normalization + tiered matching
# ---------------------------------------------------------------------------

def strip_punctuation(name: str) -> str:
    n = name.upper().strip()
    n = STATE_SUFFIX_RE.sub("", n)
    n = PAREN_RE.sub("", n)
    n = ET_AL_RE.sub("", n)
    n = n.replace("&", "AND")
    n = re.sub(r"[^\w\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def split_core_and_suffix(name: str) -> tuple[str, str | None]:
    """
    'Balyasny Asset Management L.P.' -> ('BALYASNY ASSET MANAGEMENT', 'LP')
    'The Baupost Group LLC' -> ('BAUPOST GROUP', 'LLC')  # leading "THE" excluded
    Returns (name, None) if no recognized suffix is found.
    """
    tokens = strip_punctuation(name).split(" ")
    if tokens and tokens[0] == "THE":
        tokens = tokens[1:]
    if tokens and tokens[-1] in SUFFIX_WORDS:
        return " ".join(tokens[:-1]), tokens[-1]
    return " ".join(tokens), None


def build_core_index(lookup_csv: Path) -> dict[str, list[tuple[str, str]]]:
    """
    Build core_name -> [(original SEC name, CIK), ...] from
    output/cik_lookup.csv. Built once as a dict for O(1) lookups against
    a multi-million-row source file.
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

# Manually verified overrides for cases where the name-matching logic
# surfaces multiple candidates and automatic disambiguation is not safe.
# Each entry was resolved by checking real 13F-HR filing activity via the
# SEC submissions API, not by name-matching alone. Evidence is documented
# in submission/ASSUMPTIONS.md.
#
# Tudor Investment Corp: the roster's given CIK (854157) resolves to
# STATE OF WISCONSIN INVESTMENT BOARD, an unrelated filer with its own
# 103 13F-HR filings. The correct entity is CIK 923093 (TUDOR INVESTMENT
# CORP ET AL), confirmed via 116 13F-HR filings spanning 1999-2026. The
# other candidate, CIK 1080384 (TUDOR INVESTMENT CORP, no "ET AL"), has
# zero 13F-HR filings on record.
MANUAL_CIK_OVERRIDES = {
    "0000854157": "0000923093",
}


def reconcile(filers_path: Path, core_index: dict) -> list[dict]:
    """
    Match each row in filers.csv against the SEC lookup index, decide
    cik_source, and flag ambiguous cases for manual review.
    """
    results = []
    needs_review = []

    with open(filers_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fund_name = row["fund_name"].strip()
            given_cik = row["cik"].strip().zfill(10)

            if given_cik in MANUAL_CIK_OVERRIDES:
                final_cik = MANUAL_CIK_OVERRIDES[given_cik]
                cik_source = "corrected"
                results.append({
                    "fund_name": fund_name,
                    "cik": final_cik.lstrip("0") or "0",
                    "cik_source": cik_source,
                })
                continue

            core, suffix = split_core_and_suffix(fund_name)
            candidates = core_index.get(core, [])
            candidate_ciks = {cik for _name, cik in candidates}

            if given_cik in candidate_ciks:
                cik_source = "given"
                final_cik = given_cik
            elif len(candidate_ciks) == 1:
                # Unique candidate under the normalized core name, and it
                # differs from what was given -> correct it.
                final_cik = next(iter(candidate_ciks))
                cik_source = "corrected"
            else:
                # Zero or multiple candidates: automatic disambiguation is
                # unreliable here, flag for manual review instead of guessing.
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
                "cik": final_cik.lstrip("0") or "0",
                "cik_source": cik_source,
            })

    if needs_review:
        logger.warning(
            "%d row(s) need manual review (candidate count != 1):",
            len(needs_review),
        )
        for item in needs_review:
            logger.warning(
                "  fund_name=%r given_cik=%s core=%r candidates=%s",
                item["fund_name"], item["given_cik"], item["core"],
                item["candidates"],
            )

    return results


# ---------------------------------------------------------------------------
# Step 4: write output
# ---------------------------------------------------------------------------

def write_output(results: list[dict], out_path: Path) -> None:
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
            "%s not found -- place the roster CSV at the repo root before running.",
            FILERS_INPUT_PATH,
        )
        return 1

    lookup_csv = download_and_cache_lookup()
    core_index = build_core_index(lookup_csv)
    results = reconcile(FILERS_INPUT_PATH, core_index)

    review_count = sum(1 for r in results if r["cik_source"] == "NEEDS_REVIEW")
    if review_count:
        logger.warning(
            "%d row(s) still marked NEEDS_REVIEW -- this is not a final "
            "answer. Verify manually, add a MANUAL_CIK_OVERRIDES entry, "
            "and document the evidence in submission/ASSUMPTIONS.md.",
            review_count,
        )

    write_output(results, FILERS_OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())