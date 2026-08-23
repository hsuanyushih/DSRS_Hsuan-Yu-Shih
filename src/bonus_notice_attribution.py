"""bonus_notice_attribution.py

Bonus 1: recover the holdings behind a 13F-NT notice.

Pershing Square Capital Management L.P. (CIK 1336528) filed a 13F-NT for
2026 Q2 -- a notice with no information table of its own. Its cover page's
otherManagersInfo/otherManager block names the parent filer directly:
CIK 0002026053, "PERSHING SQUARE INC." That parent is not one of the 20
roster managers, so its filing has to be fetched separately (same
User-Agent/rate-limit rules as Chapter 1).

The parent's cover page declares an otherManagers2Info list -- other
managers whose positions are folded into this one filing, each with a
sequence number. Rows in the parent's information table that carry that
sequence number in otherManager belong to that manager, not to the parent
itself. Rows with no otherManager reference are the parent's own positions
and are excluded, per bonus-01-notice-attribution.md.

Run (from the repo root, after Chapter 1-3 have produced output/*.parquet):
    python3 src/bonus_notice_attribution.py
"""

from __future__ import annotations

import logging
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from fetch import fetch, set_user_agent

logger = logging.getLogger(__name__)

FILINGS_CSV_PATH = Path("output/filings.csv")
FILINGS_DIR = Path("output/filings")
HOLDINGS_PATH = Path("output/holdings.parquet")
OUTPUT_PATH = Path("output/bonus_attributed.parquet")

SUBMISSIONS_URL_TMPL = "https://data.sec.gov/submissions/CIK{cik}.json"
INDEX_JSON_URL_TMPL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/index.json"
DOC_URL_TMPL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{doc}"
COVER_PAGE_NAME = "primary_doc.xml"

# The notice this bonus is attributing, found via Chapter 2's eda.py.
NOTICE_CIK = "1336528"
NOTICE_ACCESSION = "0001172661-26-003777"
TARGET_QUARTER = "2026Q2"

# The 20-manager roster's own fund_name, so the attributed output uses the
# same name the researcher's roster does.
NOTICE_FUND_NAME = "Pershing Square Capital Management L.P."


def localname(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def child(elem: ET.Element, name: str) -> ET.Element | None:
    for c in elem:
        if localname(c.tag) == name:
            return c
    return None


def children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if localname(c.tag) == name]


def text_of(elem: ET.Element | None, name: str) -> str | None:
    if elem is None:
        return None
    found = child(elem, name)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def find_recursive(root: ET.Element, name: str) -> ET.Element | None:
    for el in root.iter():
        if localname(el.tag) == name:
            return el
    return None


def findall_recursive(root: ET.Element, name: str) -> list[ET.Element]:
    return [el for el in root.iter() if localname(el.tag) == name]


# ---------------------------------------------------------------------------
# Step 1: read the notice's cover page to get the parent's identity
# ---------------------------------------------------------------------------

def get_parent_identity() -> tuple[str, str]:
    """Return (parent_cik, parent_name) from the notice's cover page."""
    cover_path = FILINGS_DIR / NOTICE_CIK / f"{NOTICE_ACCESSION}.cover.xml"
    root = ET.parse(cover_path).getroot()
    other_manager = find_recursive(root, "otherManager")
    if other_manager is None:
        raise RuntimeError(f"no otherManager block found on {cover_path}")
    parent_cik = text_of(other_manager, "cik")
    parent_name = text_of(other_manager, "name")
    if not parent_cik:
        raise RuntimeError(f"otherManager block on {cover_path} has no cik")
    return parent_cik.zfill(10), parent_name or ""


# ---------------------------------------------------------------------------
# Step 2: find the parent's 2026 Q2 13F-HR filing via the submissions API
# ---------------------------------------------------------------------------

def find_parent_filing(parent_cik_padded: str) -> tuple[str, str]:
    """Return (accession_number, form_type) of the parent's 2026 Q2 13F-HR/HR-A."""
    import json

    raw = fetch(SUBMISSIONS_URL_TMPL.format(cik=parent_cik_padded))
    data = json.loads(raw)
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    report_dates = recent.get("reportDate", [])

    candidates = [
        (acc, form) for form, acc, rd in zip(forms, accessions, report_dates)
        if form in {"13F-HR", "13F-HR/A"} and rd == "2026-06-30"
    ]
    if not candidates:
        raise RuntimeError(
            f"no 2026 Q2 13F-HR/HR-A found for parent CIK {parent_cik_padded}"
        )
    # If more than one (e.g. an amendment), take the last one returned --
    # the submissions API lists most recent first, matching Chapter 1's
    # "keep the latest" convention for a given report period.
    return candidates[0]


# ---------------------------------------------------------------------------
# Step 3: download the parent filing's cover page + information table
# ---------------------------------------------------------------------------

def download_parent_filing(parent_cik_padded: str, accession: str) -> tuple[Path, Path]:
    cik_nodash = parent_cik_padded.lstrip("0") or "0"
    accession_nodash = accession.replace("-", "")
    out_dir = FILINGS_DIR / cik_nodash
    out_dir.mkdir(parents=True, exist_ok=True)

    cover_path = out_dir / f"{accession}.cover.xml"
    if not cover_path.exists():
        raw = fetch(DOC_URL_TMPL.format(
            cik_int=int(cik_nodash), accession_nodash=accession_nodash, doc=COVER_PAGE_NAME,
        ))
        cover_path.write_bytes(raw)

    index_raw = fetch(INDEX_JSON_URL_TMPL.format(
        cik_int=int(cik_nodash), accession_nodash=accession_nodash,
    ))
    import json
    items = json.loads(index_raw).get("directory", {}).get("item", [])
    xml_docs = [
        item["name"] for item in items
        if item["name"].lower().endswith(".xml") and item["name"] != COVER_PAGE_NAME
    ]
    if not xml_docs:
        raise RuntimeError(f"no information table found for {cik_nodash}/{accession}")
    if len(xml_docs) > 1:
        sizes = {item["name"]: int(item.get("size") or 0) for item in items}
        xml_docs.sort(key=lambda name: sizes.get(name, 0), reverse=True)
    doc_name = xml_docs[0]

    info_path = out_dir / f"{accession}.xml"
    if not info_path.exists():
        raw = fetch(DOC_URL_TMPL.format(
            cik_int=int(cik_nodash), accession_nodash=accession_nodash, doc=doc_name,
        ))
        info_path.write_bytes(raw)

    return cover_path, info_path


# ---------------------------------------------------------------------------
# Step 4: match the notice filer's sequence number in otherManagers2Info,
# then pull the information-table rows that reference it.
# ---------------------------------------------------------------------------

def find_sequence_number(cover_root: ET.Element, target_cik: str, target_name: str) -> str | None:
    """
    Find the sequence number assigned to `target_cik`/`target_name` in the
    parent's otherManagers2Info list.

    Each otherManager2 block nests its own otherManager sub-block one level
    deeper than sequenceNumber -- cik/name live at
    otherManager2 > otherManager > {cik, name}, not directly under
    otherManager2 (confirmed by inspecting the fetched parent cover page).
    Matched by CIK first (exact); falls back to a case-insensitive
    substring match on name if no CIK match is found, since some
    otherManager2 blocks omit cik.
    """
    target_cik_stripped = target_cik.lstrip("0")

    for entry in findall_recursive(cover_root, "otherManager2"):
        seq = text_of(entry, "sequenceNumber")
        inner = child(entry, "otherManager")
        cik = text_of(inner, "cik") if inner is not None else None
        name = text_of(inner, "name") if inner is not None else None
        name = name or ""
        if cik and cik.lstrip("0") == target_cik_stripped:
            return seq
        if not cik and target_name.upper() in name.upper():
            return seq
    return None


def extract_attributed_rows(info_path: Path, sequence_number: str) -> list[dict]:
    """One row per infoTable entry whose otherManager references sequence_number.

    otherManager is not always a single value: SEC allows a comma-separated
    list of sequence numbers when a position is jointly attributed to
    several of the parent's other managers (confirmed directly against
    this filing -- e.g. otherManager='1, 2, 3, 4'). A row belongs to the
    target manager if its sequence number appears anywhere in that list,
    not only when the field is that single value.
    """
    root = ET.parse(info_path).getroot()
    rows: list[dict] = []
    target = str(sequence_number).strip()

    for entry in children(root, "infoTable"):
        other_manager = text_of(entry, "otherManager")
        if other_manager is None:
            continue
        referenced = {part.strip() for part in other_manager.split(",")}
        if target not in referenced:
            continue

        shrs = child(entry, "shrsOrPrnAmt")
        voting = child(entry, "votingAuthority")

        rows.append({
            "name_of_issuer": text_of(entry, "nameOfIssuer"),
            "title_of_class": text_of(entry, "titleOfClass"),
            "cusip": text_of(entry, "cusip"),
            "figi": text_of(entry, "figi"),
            "value": text_of(entry, "value"),
            "ssh_prnamt": text_of(shrs, "sshPrnamt") if shrs is not None else None,
            "ssh_prnamt_type": text_of(shrs, "sshPrnamtType") if shrs is not None else None,
            "put_call": text_of(entry, "putCall"),
            "investment_discretion": text_of(entry, "investmentDiscretion"),
            "other_manager": other_manager,
            "voting_sole": text_of(voting, "Sole") if voting is not None else None,
            "voting_shared": text_of(voting, "Shared") if voting is not None else None,
            "voting_none": text_of(voting, "None") if voting is not None else None,
        })

    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

SCHEMA = pa.schema([
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
    pa.field("attributed_to_cik", pa.string(), nullable=False),
])


def write_output(rows: list[dict], accession: str, parent_cik_padded: str, notice_cik_padded: str) -> None:
    records = []
    for r in rows:
        records.append({
            "accession_number": accession,
            "cik": parent_cik_padded,
            "report_quarter": TARGET_QUARTER,
            "name_of_issuer": r["name_of_issuer"],
            "title_of_class": r["title_of_class"],
            "cusip": r["cusip"],
            "figi": r["figi"],
            "value": int(r["value"]) if r["value"] is not None else 0,
            "ssh_prnamt": int(r["ssh_prnamt"]) if r["ssh_prnamt"] is not None else 0,
            "ssh_prnamt_type": r["ssh_prnamt_type"] or "",
            "put_call": r["put_call"],
            "investment_discretion": r["investment_discretion"] or "",
            "other_manager": r["other_manager"],
            "voting_sole": int(r["voting_sole"]) if r["voting_sole"] is not None else 0,
            "voting_shared": int(r["voting_shared"]) if r["voting_shared"] is not None else 0,
            "voting_none": int(r["voting_none"]) if r["voting_none"] is not None else 0,
            "attributed_to_cik": notice_cik_padded,
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    columns = {
        field.name: pa.array([rec[field.name] for rec in records], type=field.type)
        for field in SCHEMA
    }
    table = pa.Table.from_arrays([columns[f.name] for f in SCHEMA], schema=SCHEMA)
    pq.write_table(table, OUTPUT_PATH, compression="snappy")
    logger.info("Wrote %d rows to %s", table.num_rows, OUTPUT_PATH)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    set_user_agent("Hsuan-Yu Shih hsuanyu5@illinois.edu")

    notice_cik_padded = NOTICE_CIK.zfill(10)

    logger.info("Reading notice cover page to find the parent filer...")
    parent_cik_padded, parent_name = get_parent_identity()
    logger.info("Parent identified: CIK %s (%s)", parent_cik_padded, parent_name)

    logger.info("Looking up the parent's 2026 Q2 13F-HR filing...")
    accession, form_type = find_parent_filing(parent_cik_padded)
    logger.info("Parent filing: %s (%s)", accession, form_type)

    logger.info("Downloading parent filing...")
    cover_path, info_path = download_parent_filing(parent_cik_padded, accession)

    cover_root = ET.parse(cover_path).getroot()
    seq = find_sequence_number(cover_root, NOTICE_CIK, NOTICE_FUND_NAME)
    if seq is None:
        logger.warning(
            "Could not find a sequence number for %s (CIK %s) in the parent's "
            "otherManagers2Info list. This is a real finding, not a bug -- "
            "see submission/ASSUMPTIONS.md.",
            NOTICE_FUND_NAME, NOTICE_CIK,
        )
        write_output([], accession, parent_cik_padded, notice_cik_padded)
        return 0

    logger.info("Sequence number for %s: %s", NOTICE_FUND_NAME, seq)

    rows = extract_attributed_rows(info_path, seq)
    logger.info("Extracted %d attributed rows", len(rows))

    write_output(rows, accession, parent_cik_padded, notice_cik_padded)
    return 0


if __name__ == "__main__":
    sys.exit(main())