"""唯讀資料存取層 — 載入 Chapter 3 的兩張 Parquet，並提供 manager/issuer/quarter 的名字解析。

這一層只做兩件事：讀檔案、做字串比對。所有實際的聚合/篩選都在 executor.py 裡用
pandas 做，這裡完全不執行任何模型或使用者提供的程式碼字串 —— name_of_issuer 和
title_of_class 是申報者自己填的自由文字（見 docs/SCHEMA.md 的 Namespaces 段），
只拿來做本地字串比對，絕不會被塞進送給 LLM 的 prompt 裡當指令。
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

# 申報文字裡常見、對比對沒有意義的字尾/後綴，比對前先拿掉，
# 這樣 "Apple Inc" 和使用者打的 "apple" 才會配到同一個 issuer。
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
    """讀入兩張 Parquet，唯讀（pyarrow.read_table 不會、也無法寫回檔案）。"""
    filings = pq.read_table(FILINGS_PATH).to_pandas()
    holdings = pq.read_table(HOLDINGS_PATH).to_pandas()
    return filings, holdings


@functools.lru_cache(maxsize=1)
def _manager_index() -> list[dict]:
    """每個 cik 一筆，帶正規化後的 fund_name / filing_manager 核心名字，供比對用。"""
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
    """把使用者問題裡的經理人名字片段，比對回名冊上的 cik。

    回傳依信心排序的候選清單；找不到任何候選就回傳空清單（呼叫端要把這當成
    "無法回答"，而不是硬選一個）。
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

    # 完全比對不到就退而求其次：子字串包含，再退而求其次用模糊比對分數排序。
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
    """(正規化後名字, 原始 name_of_issuer) 的清單，一個原始名字只留一筆。"""
    _, holdings = load_data()
    names = holdings["name_of_issuer"].unique()
    return [(_normalize_issuer(n), n) for n in names]


def resolve_issuer(query: str | None) -> list[str]:
    """把使用者問題裡的證券/公司名字片段，比對回 holdings 裡實際出現過的 name_of_issuer。

    回傳符合的原始 name_of_issuer 字串清單（同一家公司在資料裡可能有好幾種拼法）。
    """
    if not query:
        return []
    if CUSIP_RE.match(query.strip().upper()):
        return [query.strip().upper()]  # 交給呼叫端當 cusip 直接比對

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

    # 逐字比對：查詢字串的每個詞都要出現在候選名字裡，避免太寬鬆誤配。
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
    """把 "2026 Q2" / "Q2 2026" / "2026Q2" 這類寫法統一成 report_quarter 用的 "2026Q2"。

    只回傳資料集裡真的存在的季度；問到資料集沒有的季度（例如 2026Q3）視同查無資料。
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
