"""QueryPlan to deterministic computation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from agents import data
from agents.planner import QueryPlan

FORM_TYPES_KNOWN = {"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"}


@dataclass
class Result:
    answer: Any
    unit: str
    sources: list[str]
    note: str | None = None  


def _null(reason: str) -> Result:
    natural_reason = reason
    if "not in dataset" in reason.lower() or "out of scope" in reason.lower():
        natural_reason = "This dataset only includes 2026 Q1 and Q2, so that quarter isn't available."
    return Result(answer=None, unit="NONE", sources=[], note=natural_reason)


def _cik_to_name(filings: pd.DataFrame) -> dict[str, str]:
    return filings.drop_duplicates("cik").set_index("cik")["fund_name"].to_dict()


def _resolve_single_manager(query: str) -> tuple[str | None, str | None]:
    candidates = data.resolve_manager(query)
    ciks = {c["cik"] for c in candidates}
    if not ciks:
        return None, f"no manager in the dataset matches {query!r}"
    if len(ciks) > 1:
        return None, f"manager query {query!r} is ambiguous: matches {sorted(ciks)}"
    return next(iter(ciks)), None


def _resolve_issuer_filter(query: str) -> tuple[str | None, list[str] | None, str | None]:
    """Return (cusip_or_None, name_list_or_None, error_reason_or_None)."""
    names = data.resolve_issuer(query)
    if not names:
        return None, None, f"no issuer in the dataset matches {query!r}"
    if len(names) == 1 and data.CUSIP_RE.match(names[0]) and names[0] not in _known_issuer_names():
        if not data.is_valid_cusip(names[0]):
            return None, None, f"CUSIP {names[0]!r} has an invalid check digit"
        return names[0], None, None
    return None, names, None


def _known_issuer_names() -> set[str]:
    _, holdings = data.load_data()
    return set(holdings["name_of_issuer"].unique())


_METRIC_COLUMN = {"value": "value", "shares": "ssh_prnamt"}
_GROUP_COLUMN = {"manager": "cik", "issuer": "name_of_issuer", "quarter": "report_quarter"}
_METRIC_UNIT = {
    "value": "USD",
    "shares": "SHARES",
    "distinct_issuers": "COUNT",
    "distinct_managers": "COUNT",
    "filing_count": "COUNT",
    "position_count": "COUNT",
}


def execute(plan: QueryPlan) -> Result:
    if not plan.answerable:
        return _null(plan.reason or "the question is outside the dataset's scope")

    filings, holdings = data.load_data()

    quarters = data.resolve_quarters(plan.quarter_texts) if plan.quarter_texts else []
    if plan.quarter_texts and not quarters:
        return _null(f"requested quarter(s) not in dataset: {plan.quarter_texts}")

    form_types = [f for f in plan.form_types if f in FORM_TYPES_KNOWN]

    manager_cik: str | None = None
    if plan.manager_query:
        manager_cik, err = _resolve_single_manager(plan.manager_query)
        if err:
            return _null(err)

    issuer_cusip: str | None = None
    issuer_names: list[str] | None = None
    if plan.issuer_query:
        issuer_cusip, issuer_names, err = _resolve_issuer_filter(plan.issuer_query)
        if err:
            return _null(err)

    if plan.metric == "filing_count":
        return _execute_filing_count(plan, filings, quarters, form_types, manager_cik)

    return _execute_holdings_metric(
        plan, filings, holdings, quarters, form_types, manager_cik, issuer_cusip, issuer_names,
    )


def _filter_filings(
    filings: pd.DataFrame, quarters: list[str], form_types: list[str], manager_cik: str | None,
) -> pd.DataFrame:
    f = filings
    if quarters:
        f = f[f["report_quarter"].isin(quarters)]
    if form_types:
        f = f[f["form_type"].isin(form_types)]
    if manager_cik:
        f = f[f["cik"] == manager_cik]
    return f


def _execute_filing_count(
    plan: QueryPlan, filings: pd.DataFrame, quarters: list[str],
    form_types: list[str], manager_cik: str | None,
) -> Result:
    f = _filter_filings(filings, quarters, form_types, manager_cik)
    if f.empty:
        return _null("no filings match the requested manager/quarter/form-type filters")

    cik_to_name = _cik_to_name(filings)

    if plan.group_by == "manager" or plan.answer_format in {"list_names", "boolean"}:
        by_manager = f.groupby("cik").size().sort_index()
        names = sorted((cik_to_name.get(cik, cik) for cik in by_manager.index))
        sources = sorted(f["accession_number"].unique().tolist())
        if plan.answer_format == "boolean":
            return Result(answer=("yes" if len(names) else "no"), unit="NONE", sources=sources)
        return Result(answer=names, unit="NAME", sources=sources)

    count = int(len(f))
    return Result(answer=count, unit="COUNT", sources=sorted(f["accession_number"].unique().tolist()))


def _apply_holdings_filters(
    holdings: pd.DataFrame, quarters: list[str], manager_cik: str | None,
    issuer_cusip: str | None, issuer_names: list[str] | None,
    option_type: str | None, direct_only: bool, accession_whitelist: set[str] | None,
) -> pd.DataFrame:
    h = holdings
    if quarters:
        h = h[h["report_quarter"].isin(quarters)]
    if manager_cik:
        h = h[h["cik"] == manager_cik]
    if accession_whitelist is not None:
        h = h[h["accession_number"].isin(accession_whitelist)]
    if issuer_cusip:
        h = h[h["cusip"] == issuer_cusip]
    elif issuer_names:
        h = h[h["name_of_issuer"].isin(issuer_names)]
    if option_type:
        h = h[h["put_call"].str.upper() == option_type]
    if direct_only:
        other = h["other_manager"]
        h = h[other.isna() | (other.astype(str).str.strip().isin(["", "0"]))]
    return h


def _execute_holdings_metric(
    plan: QueryPlan, filings: pd.DataFrame, holdings: pd.DataFrame,
    quarters: list[str], form_types: list[str], manager_cik: str | None,
    issuer_cusip: str | None, issuer_names: list[str] | None,
) -> Result:
    accession_whitelist = None
    if form_types:
        accession_whitelist = set(
            _filter_filings(filings, quarters, form_types, manager_cik)["accession_number"]
        )
        if not accession_whitelist:
            return _null("no filings match the requested form-type/quarter/manager filters")

    h = _apply_holdings_filters(
        holdings, quarters, manager_cik, issuer_cusip, issuer_names,
        plan.option_type, plan.direct_only, accession_whitelist,
    )
    if h.empty:
        if plan.answer_format == "boolean":
            sources = sorted(
                _filter_filings(filings, quarters, [], manager_cik)["accession_number"].unique().tolist()
            )
            return Result(answer="no", unit="NONE", sources=sources)
        return _null("no holdings match the requested filters")

    cik_to_name = _cik_to_name(filings)

    if plan.aggregate == "delta":
        return _execute_delta(plan, h, quarters, cik_to_name)

    if plan.group_by == "none":
        return _execute_scalar(plan, h, cik_to_name)

    return _execute_grouped(plan, h, cik_to_name)


def _aggregate_series(plan: QueryPlan, h: pd.DataFrame) -> pd.Series | int | float:
    if plan.metric == "distinct_issuers":
        return h["name_of_issuer"].nunique()
    if plan.metric == "distinct_managers":
        return h["cik"].nunique()
    if plan.metric == "position_count":
        return len(h)

    col = _METRIC_COLUMN[plan.metric]
    if plan.aggregate == "sum":
        return h[col].sum()
    if plan.aggregate == "max":
        return h[col].max()
    if plan.aggregate == "min":
        return h[col].min()
    if plan.aggregate == "avg":
        return h[col].mean()
    if plan.aggregate == "count":
        return len(h)
    raise ValueError(f"unsupported aggregate for scalar metric: {plan.aggregate}")


def _execute_scalar(plan: QueryPlan, h: pd.DataFrame, cik_to_name: dict[str, str]) -> Result:
    value = _aggregate_series(plan, h)
    unit = _METRIC_UNIT[plan.metric]
    sources = sorted(h["accession_number"].unique().tolist())

    if plan.answer_format == "boolean":
        return Result(answer=("yes" if (isinstance(value, (int, float)) and value > 0) else "no"),
                      unit="NONE", sources=sources)
    if plan.answer_format == "name_and_value" and plan.metric in {"value", "shares"}:
        row = h.loc[h[_METRIC_COLUMN[plan.metric]].idxmax()]
        return Result(answer=[row["name_of_issuer"], _to_number(value)], unit=unit, sources=sources)

    return Result(answer=_to_number(value), unit=unit, sources=sources)


def _execute_grouped(plan: QueryPlan, h: pd.DataFrame, cik_to_name: dict[str, str]) -> Result:
    group_col = _GROUP_COLUMN[plan.group_by]
    unit = _METRIC_UNIT[plan.metric]

    if plan.metric in {"distinct_issuers", "distinct_managers"}:
        nunique_col = "name_of_issuer" if plan.metric == "distinct_issuers" else "cik"
        totals = h.groupby(group_col)[nunique_col].nunique()
    elif plan.metric == "position_count":
        totals = h.groupby(group_col).size()
    else:
        col = _METRIC_COLUMN[plan.metric]
        agg_fn = {"sum": "sum", "max": "max", "min": "min", "avg": "mean", "count": "count"}[plan.aggregate]
        totals = h.groupby(group_col)[col].agg(agg_fn)

    # group key as the secondary sort key so tied results are stable and reproducible
    totals = totals.sort_index()
    ascending = plan.sort_order == "asc"
    totals = totals.sort_values(ascending=ascending, kind="stable")

    top_n = plan.top_n if plan.top_n > 0 else len(totals)
    top = totals.head(top_n)

    def display_name(key: str) -> str:
        return cik_to_name.get(key, key) if plan.group_by == "manager" else key

    def sources_for(key: str) -> list[str]:
        return sorted(h.loc[h[group_col] == key, "accession_number"].unique().tolist())

    if plan.answer_format in {"name", "list_names"}:
        names = [display_name(k) for k in top.index]
        sources = sorted({acc for k in top.index for acc in sources_for(k)})
        answer = names[0] if (plan.answer_format == "name" and len(names) == 1) else names
        return Result(answer=answer, unit="NAME", sources=sources)

    if plan.answer_format == "name_and_value":
        key = top.index[0]
        return Result(
            answer=[display_name(key), _to_number(top.iloc[0])],
            unit=unit,
            sources=sources_for(key),
        )

    if plan.answer_format == "list_values":
        answer = [_to_number(v) for v in top.tolist()]
        sources = sorted({acc for k in top.index for acc in sources_for(k)})
        return Result(answer=answer, unit=unit, sources=sources)

    # answer_format == "value": a single number, usually the measurement of that group when top_n=1.
    key = top.index[0]
    return Result(answer=_to_number(top.iloc[0]), unit=unit, sources=sources_for(key))


def _execute_delta(
    plan: QueryPlan, h: pd.DataFrame, quarters: list[str], cik_to_name: dict[str, str],
) -> Result:
    if len(quarters) != 2:
        return _null("delta aggregate requires exactly two resolved quarters")
    q1, q2 = sorted(quarters)
    group_col = _GROUP_COLUMN.get(plan.group_by, "cik")
    col = _METRIC_COLUMN.get(plan.metric, "value")

    pivot = h.groupby([group_col, "report_quarter"])[col].sum().unstack("report_quarter")
    pivot = pivot.reindex(columns=[q1, q2], fill_value=0).fillna(0)
    pivot["delta"] = pivot[q2] - pivot[q1]
    pivot = pivot.sort_index()
    ascending = plan.sort_order == "asc"
    pivot = pivot.sort_values("delta", ascending=ascending, kind="stable")

    top_n = plan.top_n if plan.top_n > 0 else len(pivot)
    top = pivot.head(top_n)

    def display_name(key: str) -> str:
        return cik_to_name.get(key, key) if plan.group_by == "manager" else key

    def sources_for(key: str) -> list[str]:
        return sorted(h.loc[h[group_col] == key, "accession_number"].unique().tolist())

    unit = _METRIC_UNIT[plan.metric]
    key = top.index[0]
    delta_value = _to_number(top.loc[key, "delta"])

    if plan.answer_format in {"name", "list_names"}:
        names = [display_name(k) for k in top.index]
        sources = sorted({acc for k in top.index for acc in sources_for(k)})
        answer = names[0] if plan.answer_format == "name" else names
        return Result(answer=answer, unit="NAME", sources=sources)

    if plan.answer_format == "name_and_value":
        return Result(answer=[display_name(key), delta_value], unit=unit, sources=sources_for(key))

    return Result(answer=delta_value, unit=unit, sources=sources_for(key))


def _to_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value