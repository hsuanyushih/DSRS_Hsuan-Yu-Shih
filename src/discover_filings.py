"""
discover_filings.py -- uses the verified CIKs in output/filers.csv to query the SEC
submissions API, filtering for 2026 Q1/Q2 (periodOfReport = 2026-03-31 or 2026-06-30)
13F filings.

"""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path

from fetch import fetch

logger = logging.getLogger(__name__)

FILERS_PATH = Path("output/filers.csv")
FILINGS_OUTPUT_PATH = Path("output/filings.csv")
SUBMISSIONS_URL_TMPL = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_PAGE_URL_TMPL = "https://data.sec.gov/submissions/{name}"

TARGET_PERIODS = {"2026-03-31", "2026-06-30"}
FILING_DATE_CUTOFF = "2026-08-18"
TARGET_FORMS = {"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"}


def load_filers(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _rows_from_block(block: dict):
    """Zip the parallel arrays in the submissions JSON into row tuples."""
    forms = block.get("form", [])
    accessions = block.get("accessionNumber", [])
    filing_dates = block.get("filingDate", [])
    report_dates = block.get("reportDate", [])
    primary_docs = block.get("primaryDocument", [])
    return zip(forms, accessions, filing_dates, report_dates, primary_docs)


def iter_all_filings(cik_padded: str, data: dict):
    """
    Yield all filing records for this CIK in order.
    The submissions API's "recent" block only contains the most recent ~1000 entries;
    older filings must be fetched from the paginated JSON files listed in
    filings.files -- only needed when "recent" doesn't already cover both quarters.
    """
    recent = data.get("filings", {}).get("recent", {})
    yield from _rows_from_block(recent)

    for file_info in data.get("filings", {}).get("files", []):
        url = SUBMISSIONS_PAGE_URL_TMPL.format(name=file_info["name"])
        raw = fetch(url)
        yield from _rows_from_block(json.loads(raw))


def find_target_filings(cik: str, fund_name: str) -> list[dict]:
    """
    Find this CIK's 13F-HR / 13F-HR/A / 13F-NT / 13F-NT/A filings that fall in
    2026 Q1/Q2, keeping only the newest one per quarter. A notice (NT) also counts
    as a legitimate result and is not traced back to another manager's CIK.
    """
    cik_padded = cik.zfill(10)
    data = json.loads(fetch(SUBMISSIONS_URL_TMPL.format(cik=cik_padded)))

    best_per_period: dict[str, dict] = {}

    for form, accession, filing_date, report_date, primary_doc in iter_all_filings(cik_padded, data):
        if report_date not in TARGET_PERIODS or filing_date > FILING_DATE_CUTOFF:
            continue
        if form not in TARGET_FORMS:
            continue

        candidate = {
            "fund_name": fund_name,
            "cik": cik,
            "accession": accession,
            "form": form,
            "filingDate": filing_date,
            "periodOfReport": report_date,
            "primaryDocument": primary_doc,
        }

        existing = best_per_period.get(report_date)
        if existing is None or (filing_date, accession) > (existing["filingDate"], existing["accession"]):
            best_per_period[report_date] = candidate

        # once both quarters are found, no need to keep paging through older files
        if len(best_per_period) == len(TARGET_PERIODS):
            break

    return list(best_per_period.values())


def write_output(rows: list[dict], out_path: Path) -> None:
    rows_sorted = sorted(rows, key=lambda r: (int(r["cik"]), r["periodOfReport"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["fund_name", "cik", "accession", "form", "filingDate",
                  "periodOfReport", "primaryDocument"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_sorted:
            writer.writerow(row)
    logger.info("Wrote %d rows to %s", len(rows_sorted), out_path)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not FILERS_PATH.exists():
        logger.error(
            "Cannot find %s -- run cik_verify.py first to produce the verified roster.",
            FILERS_PATH,
        )
        return 1

    filers = load_filers(FILERS_PATH)
    all_rows: list[dict] = []

    for filer in filers:
        cik = filer["cik"].strip()
        fund_name = filer["fund_name"].strip()
        logger.info("Querying filing history for %s (CIK %s)...", fund_name, cik)
        rows = find_target_filings(cik, fund_name)
        if len(rows) < len(TARGET_PERIODS):
            found_periods = {r["periodOfReport"] for r in rows}
            missing = TARGET_PERIODS - found_periods
            logger.warning(
                "%s (CIK %s) is missing a 13F-HR for periodOfReport=%s, please verify manually",
                fund_name, cik, sorted(missing),
            )
        all_rows.extend(rows)

    write_output(all_rows, FILINGS_OUTPUT_PATH)

    if len(all_rows) != 40:
        logger.warning(
            "Total row count is %d, which does not match the expected 40 rows "
            "Need to check the missing-filing warnings above.",
            len(all_rows),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
