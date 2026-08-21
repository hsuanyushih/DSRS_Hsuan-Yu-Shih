"""
download_filings.py -- downloads the XML for the 40 filings in output/filings.csv,
saving to output/filings/{cik}/{accession}.xml (information table) and
output/filings/{cik}/{accession}.cover.xml (cover page).

Background:
    Each filing folder actually contains two XML documents:
        - primary_doc.xml            the cover page (filing_manager, amendment_type,
                                      table_entry_total, and other Ch2 schema fields live here)
        - another XML with an unpredictable filename   the actual information table (holdings)
    This script uses index.json to find "the XML that is not primary_doc.xml" as the
    information table, and downloads both, since later chapters need both.

Usage (always run from the project root):
    python3 src/download_filings.py
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path

from fetch import fetch

logger = logging.getLogger(__name__)

FILINGS_INPUT_PATH = Path("output/filings.csv")
FILINGS_DIR = Path("output/filings")
INDEX_JSON_URL_TMPL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/index.json"
DOC_URL_TMPL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{doc}"

COVER_PAGE_NAME = "primary_doc.xml"
NOTICE_FORMS = {"13F-NT", "13F-NT/A"}


def load_filings(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_info_table_doc(cik: str, accession: str) -> str | None:
    """
    Look up this filing's index.json to find the actual information-table filename --
    exclude the cover page primary_doc.xml, the full submission .txt, and the -index
    html file; the one remaining .xml file is the information table.
    """
    accession_nodash = accession.replace("-", "")
    url = INDEX_JSON_URL_TMPL.format(cik_int=int(cik), accession_nodash=accession_nodash)
    data = json.loads(fetch(url))
    items = data.get("directory", {}).get("item", [])

    xml_docs = [
        item["name"] for item in items
        if item["name"].lower().endswith(".xml") and item["name"] != COVER_PAGE_NAME
    ]

    if len(xml_docs) == 1:
        return xml_docs[0]

    if not xml_docs:
        logger.warning("CIK %s accession %s: no information-table XML found", cik, accession)
        return None

    # more than one candidate, pick the largest file (the info table is usually much
    # bigger than the cover page/summary documents)
    logger.warning(
        "CIK %s accession %s has %d candidate XML files %s, taking the largest, please verify manually",
        cik, accession, len(xml_docs), xml_docs,
    )
    sizes = {item["name"]: int(item.get("size") or 0) for item in items}
    return max(xml_docs, key=lambda name: sizes.get(name, 0))


def download_filing(cik: str, accession: str, doc_name: str, out_path: Path) -> None:
    accession_nodash = accession.replace("-", "")
    url = DOC_URL_TMPL.format(cik_int=int(cik), accession_nodash=accession_nodash, doc=doc_name)
    raw = fetch(url)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not FILINGS_INPUT_PATH.exists():
        logger.error(
            "Cannot find %s -- run discover_filings.py first to produce the filing list.",
            FILINGS_INPUT_PATH,
        )
        return 1

    filings = load_filings(FILINGS_INPUT_PATH)
    ok_count = 0

    for filing in filings:
        cik = filing["cik"].strip()
        accession = filing["accession"].strip()
        fund_name = filing["fund_name"].strip()
        form = filing["form"].strip()

        cover_path = FILINGS_DIR / cik / f"{accession}.cover.xml"
        if not cover_path.exists():
            logger.info("Downloading cover page %s (CIK %s) accession %s", fund_name, cik, accession)
            download_filing(cik, accession, COVER_PAGE_NAME, cover_path)

        if form in NOTICE_FORMS:
            # a notice (NT) has no information table by definition; the cover page is
            # the entire content of this filing
            logger.info("%s (%s) is a 13F-NT notice, no information table to download, skipping", fund_name, accession)
            ok_count += 1
            continue

        out_path = FILINGS_DIR / cik / f"{accession}.xml"
        if out_path.exists():
            logger.info("%s (%s) information table already exists, skipping: %s", fund_name, accession, out_path)
            ok_count += 1
            continue

        doc_name = find_info_table_doc(cik, accession)
        if doc_name is None:
            continue

        logger.info("Downloading %s (CIK %s) accession %s -> %s", fund_name, cik, accession, doc_name)
        download_filing(cik, accession, doc_name, out_path)
        ok_count += 1

    logger.info("Done, successfully downloaded/confirmed %d / %d filings", ok_count, len(filings))
    if ok_count != len(filings):
        logger.warning("%d filing(s) failed to download, check the warnings above.", len(filings) - ok_count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
