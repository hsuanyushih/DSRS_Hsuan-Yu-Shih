"""
parse_filings.py — Chapter 3: parse the Chapter 1 XML downloads into
output/filings.parquet and output/holdings.parquet, per docs/SCHEMA.md.

Reads only local files (output/filings.csv + output/filings/{cik}/*.xml),
never the network — required for the "run it twice, byte-identical" contract
in SCHEMA.md/03-structure.md: no re-fetch means no chance of picking up a
filing that changed between runs.

Every filing in output/filings.csv gets exactly one row in filings.parquet,
notices included. A 13F-NT has a cover page and no information table, so it
contributes zero rows to holdings.parquet — see ASSUMPTIONS.md for why this
pipeline keeps the notice itself (CIK 1336528) rather than resolving it to
the entity its otherManager points at.

Run:
    python3 src/parse_filings.py
Then:
    python verify.py
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

FILINGS_CSV_PATH = Path("output/filings.csv")
FILINGS_DIR = Path("output/filings")
FILINGS_OUT_PATH = Path("output/filings.parquet")
HOLDINGS_OUT_PATH = Path("output/holdings.parquet")

NOTICE_FORMS = {"13F-NT", "13F-NT/A"}


# ---------------------------------------------------------------------------
# Namespace-agnostic XML helpers — filers use different prefixes (or none)
# for the identical namespace URI; match on local name, never the literal tag.
# ---------------------------------------------------------------------------

def localname(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def child(elem: ET.Element, name: str) -> ET.Element | None:
    """First direct child with this local name (not a recursive search)."""
    for c in elem:
        if localname(c.tag) == name:
            return c
    return None


def children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if localname(c.tag) == name]


def path(root: ET.Element, *names: str) -> ET.Element | None:
    """Walk a chain of direct-child local names from root; None if any step is missing."""
    node: ET.Element | None = root
    for name in names:
        if node is None:
            return None
        node = child(node, name)
    return node


def text_at(root: ET.Element, *names: str) -> str | None:
    """Text of the element at this path, or None if missing or empty (self-closed)."""
    el = path(root, *names)
    if el is None or el.text is None:
        return None
    stripped = el.text.strip()
    return stripped or None


def parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    # Whole-dollar/share values shouldn't carry decimals in our scope, but
    # tolerate them defensively rather than crash on a stray "1234.00".
    return int(float(text)) if "." in text else int(text)


def parse_cover_date(text: str | None) -> dt.date | None:
    """Cover-page dates are 'MM-DD-YYYY'; not the same format as filingDate."""
    if text is None:
        return None
    return dt.datetime.strptime(text, "%m-%d-%Y").date()


def report_quarter_of(report_period: dt.date) -> str:
    quarter = (report_period.month - 1) // 3 + 1
    return f"{report_period.year}Q{quarter}"


# ---------------------------------------------------------------------------
# Reading the Chapter 1 output
# ---------------------------------------------------------------------------

def load_filing_index() -> list[dict]:
    """
    output/filings.csv is the roster-driven list of what to parse: it is the
    only place filing_date lives (the cover page XML does not carry it at
    all — confirmed in Chapter 2's eda.py), and its row order is already
    deterministic, so we parse in that same order.
    """
    with open(FILINGS_CSV_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_filing(entry: dict) -> tuple[dict, list[dict]]:
    """
    Parse one filing's cover page (+ information table, if it has one) into
    (filings_row, holdings_rows).
    """
    raw_cik = entry["cik"].strip()
    accession = entry["accession"].strip()
    fund_name = entry["fund_name"].strip()
    cik = raw_cik.zfill(10)  # SCHEMA.md: string, zero-padded to 10 chars, always

    cover_path = FILINGS_DIR / raw_cik / f"{accession}.cover.xml"
    info_path = FILINGS_DIR / raw_cik / f"{accession}.xml"

    cover_root = ET.parse(cover_path).getroot()

    form_type = text_at(cover_root, "headerData", "submissionType")
    if form_type != entry["form"].strip():
        raise ValueError(
            f"{accession}: cover page submissionType {form_type!r} disagrees with "
            f"discover_filings.py's recorded form {entry['form']!r}"
        )

    report_period = parse_cover_date(text_at(cover_root, "headerData", "filerInfo", "periodOfReport"))
    filing_date = dt.date.fromisoformat(entry["filingDate"].strip())

    filing_manager = text_at(cover_root, "formData", "coverPage", "filingManager", "name")
    report_type = text_at(cover_root, "formData", "coverPage", "reportType")
    amendment_no_text = text_at(cover_root, "formData", "coverPage", "amendmentNo")
    amendment_type = text_at(cover_root, "formData", "coverPage", "amendmentInfo", "amendmentType")
    form_13f_file_number = text_at(cover_root, "formData", "coverPage", "form13FFileNumber")
    crd_number = text_at(cover_root, "formData", "coverPage", "crdNumber")
    sec_file_number = text_at(cover_root, "formData", "coverPage", "secFileNumber")
    other_included_managers_count = parse_int(
        text_at(cover_root, "formData", "summaryPage", "otherIncludedManagersCount")
    )
    table_entry_total = parse_int(text_at(cover_root, "formData", "summaryPage", "tableEntryTotal"))
    table_value_total = parse_int(text_at(cover_root, "formData", "summaryPage", "tableValueTotal"))

    filings_row = {
        "accession_number": accession,
        "cik": cik,
        "fund_name": fund_name,
        "filing_manager": filing_manager,
        "form_type": form_type,
        "report_period": report_period,
        "report_quarter": report_quarter_of(report_period),
        "filing_date": filing_date,
        "is_amendment": form_type.endswith("/A"),
        "amendment_no": int(amendment_no_text) if amendment_no_text is not None else None,
        "amendment_type": amendment_type,
        "report_type": report_type,
        "form_13f_file_number": form_13f_file_number,
        "crd_number": crd_number,
        "sec_file_number": sec_file_number,
        "other_included_managers_count": other_included_managers_count,
        "table_entry_total": table_entry_total,
        "table_value_total": table_value_total,
    }

    holdings_rows: list[dict] = []
    if form_type not in NOTICE_FORMS:
        if not info_path.exists():
            raise FileNotFoundError(f"{accession}: expected an information table at {info_path}")
        holdings_rows = parse_holdings(info_path, accession, cik, filings_row["report_quarter"])
    elif info_path.exists():
        raise ValueError(f"{accession}: form_type {form_type!r} is a notice but an information table exists on disk")

    return filings_row, holdings_rows


def parse_holdings(info_path: Path, accession: str, cik: str, report_quarter: str) -> list[dict]:
    """
    One row per <infoTable> entry, in source document order. cusip is not
    unique within a filing and rows are never deduplicated or aggregated.
    """
    root = ET.parse(info_path).getroot()
    rows: list[dict] = []

    for entry in children(root, "infoTable"):
        shrs = child(entry, "shrsOrPrnAmt")
        voting = child(entry, "votingAuthority")

        other_manager = text_at(entry, "otherManager")
        # "0" is not a valid 1-based sequence number in otherManagers2Info (see
        # eda.py finding #6) — some filers (e.g. Renaissance) write it as an
        # explicit placeholder instead of omitting the element. Both mean the
        # same thing: no other manager, so both become a genuine null here.
        if other_manager == "0":
            other_manager = None

        rows.append({
            "accession_number": accession,
            "cik": cik,
            "report_quarter": report_quarter,
            "name_of_issuer": text_at(entry, "nameOfIssuer"),
            "title_of_class": text_at(entry, "titleOfClass"),
            "cusip": text_at(entry, "cusip"),
            "figi": text_at(entry, "figi"),
            "value": parse_int(text_at(entry, "value")),
            "ssh_prnamt": parse_int(text_at(shrs, "sshPrnamt")) if shrs is not None else None,
            "ssh_prnamt_type": text_at(shrs, "sshPrnamtType") if shrs is not None else None,
            "put_call": text_at(entry, "putCall"),
            "investment_discretion": text_at(entry, "investmentDiscretion"),
            "other_manager": other_manager,
            "voting_sole": parse_int(text_at(voting, "Sole")) if voting is not None else None,
            "voting_shared": parse_int(text_at(voting, "Shared")) if voting is not None else None,
            "voting_none": parse_int(text_at(voting, "None")) if voting is not None else None,
        })

    return rows


# ---------------------------------------------------------------------------
# Writing Parquet — built directly with pyarrow (no pandas) so there is no
# pandas index to leak and no risk of numeric columns silently landing as
# float64 instead of int64/int32.
# ---------------------------------------------------------------------------

FILINGS_SCHEMA = pa.schema([
    pa.field("accession_number", pa.string(), nullable=False),
    pa.field("cik", pa.string(), nullable=False),
    pa.field("fund_name", pa.string(), nullable=False),
    pa.field("filing_manager", pa.string(), nullable=False),
    pa.field("form_type", pa.string(), nullable=False),
    pa.field("report_period", pa.date32(), nullable=False),
    pa.field("report_quarter", pa.string(), nullable=False),
    pa.field("filing_date", pa.date32(), nullable=False),
    pa.field("is_amendment", pa.bool_(), nullable=False),
    pa.field("amendment_no", pa.int32(), nullable=True),
    pa.field("amendment_type", pa.string(), nullable=True),
    pa.field("report_type", pa.string(), nullable=False),
    pa.field("form_13f_file_number", pa.string(), nullable=True),
    pa.field("crd_number", pa.string(), nullable=True),
    pa.field("sec_file_number", pa.string(), nullable=True),
    pa.field("other_included_managers_count", pa.int32(), nullable=True),
    pa.field("table_entry_total", pa.int64(), nullable=True),
    pa.field("table_value_total", pa.int64(), nullable=True),
])

HOLDINGS_SCHEMA = pa.schema([
    pa.field("accession_number", pa.string(), nullable=False),
    pa.field("cik", pa.string(), nullable=False),
    pa.field("report_quarter", pa.string(), nullable=False),
    pa.field("name_of_issuer", pa.string(), nullable=False),
    pa.field("title_of_class", pa.string(), nullable=False),
    pa.field("cusip", pa.string(), nullable=False),
    pa.field("figi", pa.string(), nullable=True),
    pa.field("value", pa.int64(), nullable=False),
    pa.field("ssh_prnamt", pa.int64(), nullable=False),
    pa.field("ssh_prnamt_type", pa.string(), nullable=False),
    pa.field("put_call", pa.string(), nullable=True),
    pa.field("investment_discretion", pa.string(), nullable=False),
    pa.field("other_manager", pa.string(), nullable=True),
    pa.field("voting_sole", pa.int64(), nullable=False),
    pa.field("voting_shared", pa.int64(), nullable=False),
    pa.field("voting_none", pa.int64(), nullable=False),
])


def write_table(rows: list[dict], schema: pa.Schema, out_path: Path) -> None:
    columns = {
        field.name: pa.array([row[field.name] for row in rows], type=field.type)
        for field in schema
    }
    table = pa.Table.from_arrays([columns[f.name] for f in schema], schema=schema)
    pq.write_table(table, out_path, compression="snappy")
    logger.info("Wrote %d rows to %s", table.num_rows, out_path)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not FILINGS_CSV_PATH.exists():
        logger.error("Cannot find %s -- run the three Chapter 1 scripts first.", FILINGS_CSV_PATH)
        return 1

    entries = load_filing_index()
    filings_rows: list[dict] = []
    holdings_rows: list[dict] = []

    for entry in entries:
        filing_row, position_rows = parse_filing(entry)
        filings_rows.append(filing_row)
        holdings_rows.extend(position_rows)

    if len(filings_rows) != 40:
        logger.warning("filings row count is %d, expected 40 (20 managers x 2 quarters)", len(filings_rows))

    FILINGS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_table(filings_rows, FILINGS_SCHEMA, FILINGS_OUT_PATH)
    write_table(holdings_rows, HOLDINGS_SCHEMA, HOLDINGS_OUT_PATH)

    return 0


if __name__ == "__main__":
    sys.exit(main())
