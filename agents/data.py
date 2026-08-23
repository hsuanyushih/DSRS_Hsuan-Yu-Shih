"""Read-only data access layer -- loads Chapter 3's two Parquet tables and
resolves manager / issuer / quarter names.

This layer only does two things: read files, and do string comparison. All
actual filtering/aggregation happens in executor.py via pandas -- nothing
here executes a model or user-supplied code string. name_of_issuer and
title_of_class are free text filed by third parties (see the Namespaces
section of docs/SCHEMA.md); they are only ever used for local string
matching and are never passed into a prompt sent to the LLM.
"""

from __future__ import annotations

import difflib
import functools
import re
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cik_verify import split_core_and_suffix, strip_punctuation  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[1] / "output"
FILINGS_PATH = OUTPUT / "filings.parquet"
HOLDINGS_PATH = OUTPUT / "holdings.parquet"

QUARTER_RE = re.compile(r"(?P<year>20\d{2})\D{0,4}Q(?P<q>[1-4])", re.IGNORECASE)
CUSIP_RE = re.compile(r"^[A-Z0-9]{9}$")


def _cusip_char_value(c: str) -> int:
    """Map a CUSIP character to its numeric value: digits 0-9, letters A=10..Z=35, *=36, @=37, #=38."""
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return ord(c.upper()) - ord("A") + 10
    if c == "*":
        return 36
    if c == "@":
        return 37
    if c == "#":
        return 38
    return 0


def is_valid_cusip(cusip: str) -> bool:
    """Validate a 9-character CUSIP's check digit (standard weighted mod-10
    algorithm). The 9th character is a check digit computed from the first
    8: every even (1-indexed) position is doubled before summing digit-by-
    digit. A well-formed-but-invalid-checksum CUSIP -- a single transposed
    or mistyped digit -- looks completely valid by shape alone; this is
    what catches it before it's used as a filter value."""
    if not cusip or len(cusip) != 9:
        return False
    total = 0
    for i, c in enumerate(cusip[:8]):
        val = _cusip_char_value(c)
        if i % 2 == 1:
            val *= 2
        total += val // 10 + val % 10
    expected = str((10 - (total % 10)) % 10)
    return cusip[8] == expected


# Common suffixes/words in filing text that carry no matching value --
# stripped before comparison so "Apple Inc" and a user-typed "apple" match
# the same issuer.
ISSUER_NOISE_WORDS = {
    "INC", "CORP", "CO", "LTD", "PLC", "LLC", "LP", "SA", "AG", "NV", "SE",
    "CLASS", "CL", "COM", "SPONSORED", "ADS", "ADR", "US", "USA",
}


def _normalize_issuer(name: str) -> str:
    n = strip_punctuation(name)
    tokens = [t for t in n.split(" ") if t not in ISSUER_NOISE_WORDS]
    return " ".join(tokens)


@functools.lru_cache(maxsize=1)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load both Parquet tables, read-only (pyarrow.read_table neither writes
    back nor can be made to)."""
    filings = pq.read_table(FILINGS_PATH).to_pandas()
    holdings = pq.read_table(HOLDINGS_PATH).to_pandas()
    return filings, holdings


@functools.lru_cache(maxsize=1)
def _manager_index() -> list[dict]:
    """One entry per CIK, with normalized fund_name / filing_manager core
    names for matching."""
    filings, _ = load_data()
    seen: dict[str, dict] = {}
    for cik, group in filings.groupby("cik"):
        fund_name = group["fund_name"].iloc[0]
        filing_manager = group["filing_manager"].iloc[0]
        fund_core, _ = split_core_and_suffix(fund_name)
        mgr_core, _ = split_core_and_suffix(filing_manager)
        seen[cik] = {
            "cik": cik,
            "fund_name": fund_name,
            "filing_manager": filing_manager,
            "fund_core": fund_core,
            "manager_core": mgr_core,
        }
    return list(seen.values())


def resolve_manager(query: str | None) -> list[dict]:
    """Resolve a manager-name fragment from a question back to a roster CIK.

    Returns candidates ranked by confidence; an empty list means the caller
    should treat this as "cannot answer" rather than guessing one.
    """
    if not query:
        return []
    query_core, _ = split_core_and_suffix(query)
    if not query_core:
        return []

    index = _manager_index()
    exact = [row for row in index
             if row["fund_core"] == query_core or row["manager_core"] == query_core]
    if exact:
        return exact

    # No exact match: fall back to substring containment, then to a
    # fuzzy-match score ranking as a last resort.
    contains = [row for row in index
                if query_core in row["fund_core"] or query_core in row["manager_core"]]
    if contains:
        return contains

    scored = []
    for row in index:
        score = max(
            difflib.SequenceMatcher(None, query_core, row["fund_core"]).ratio(),
            difflib.SequenceMatcher(None, query_core, row["manager_core"]).ratio(),
        )
        if score >= 0.72:
            scored.append((score, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _score, row in scored]


@functools.lru_cache(maxsize=1)
def _issuer_index() -> list[tuple[str, str]]:
    """List of (normalized name, original name_of_issuer); one entry per
    distinct original spelling."""
    _, holdings = load_data()
    names = holdings["name_of_issuer"].unique()
    return [(_normalize_issuer(n), n) for n in names]


def resolve_issuer(query: str | None) -> list[str]:
    """Resolve a security/company-name fragment from a question back to the
    original name_of_issuer strings that actually appear in holdings.

    Returns the matching original name_of_issuer strings (the same company
    may appear under several spellings in the data).
    """
    if not query:
        return []
    if CUSIP_RE.match(query.strip().upper()):
        return [query.strip().upper()]  # let the caller compare this as a CUSIP directly

    query_norm = _normalize_issuer(query)
    if not query_norm:
        return []

    index = _issuer_index()
    exact = [orig for norm, orig in index if norm == query_norm]
    if exact:
        return exact

    contains = [orig for norm, orig in index
                if query_norm in norm or norm in query_norm]
    if contains:
        return contains

    # Word-subset match: every word in the query must appear in the
    # candidate name, to avoid an overly loose false match.
    query_words = set(query_norm.split(" "))
    word_match = [orig for norm, orig in index
                  if query_words and query_words.issubset(set(norm.split(" ")))]
    if word_match:
        return word_match

    scored = []
    for norm, orig in index:
        score = difflib.SequenceMatcher(None, query_norm, norm).ratio()
        if score >= 0.8:
            scored.append((score, orig))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [orig for _score, orig in scored]


def resolve_quarters(texts: list[str] | None) -> list[str]:
    """Normalize spellings like "2026 Q2" / "Q2 2026" / "2026Q2" into the
    "2026Q2" form used by report_quarter.

    Only returns quarters that actually exist in the dataset; a quarter the
    dataset doesn't have (e.g. 2026Q3) is treated the same as no data found.
    """
    if not texts:
        return []
    filings, _ = load_data()
    known = set(filings["report_quarter"].unique())
    result = []
    for text in texts:
        m = QUARTER_RE.search(text or "")
        if not m:
            continue
        q = f"{m.group('year')}Q{m.group('q')}"
        if q in known and q not in result:
            result.append(q)
    return result