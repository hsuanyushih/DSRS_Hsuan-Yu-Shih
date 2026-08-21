"""問題 -> 結構化查詢計畫（QueryPlan）。

LLM 在這裡唯一的工作是把使用者的自然語言問題，翻譯成一組白名單欄位/列舉值組成的
查詢計畫 —— 不是 SQL、不是可執行的程式碼字串。計畫產出後一律經過 `validate_plan`
逐欄檢查（型別、列舉值、範圍），驗證失敗一律視為「無法規劃」而不是硬塞一個猜測值，
執行端（executor.py）再依這組白名單欄位對 pandas DataFrame 做篩選/聚合。

送進 prompt 的內容只有使用者問題本身和固定的系統說明文字，絕不包含任何申報書裡的
自由文字（name_of_issuer / title_of_class 等）—— 那些欄位是第三方申報者填的，
放進 prompt 就等於把不受控的文字餵進指令通道，因此 issuer/manager 的名字解析全部
留在 data.py 用本地字串比對完成，模型只需要把「使用者打的那段文字」原封不動抄出來。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agents import llm

logger = logging.getLogger(__name__)

METRICS = {"value", "shares", "distinct_issuers", "distinct_managers", "filing_count", "position_count"}
AGGREGATES = {"sum", "max", "min", "avg", "count", "delta"}
GROUP_BYS = {"manager", "issuer", "quarter", "none"}
ANSWER_FORMATS = {"value", "name", "boolean", "name_and_value", "list_names", "list_values"}
OPTION_TYPES = {"PUT", "CALL"}
SORT_ORDERS = {"asc", "desc"}

QUERY_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "manager_query": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "issuer_query": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "quarter_texts": {"type": "array", "items": {"type": "string"}},
        "form_types": {"type": "array", "items": {"type": "string"}},
        "metric": {"type": "string", "enum": sorted(METRICS)},
        "aggregate": {"type": "string", "enum": sorted(AGGREGATES)},
        "group_by": {"type": "string", "enum": sorted(GROUP_BYS)},
        "option_type": {"anyOf": [{"type": "string", "enum": sorted(OPTION_TYPES)}, {"type": "null"}]},
        "direct_only": {"type": "boolean"},
        "top_n": {"type": "integer"},
        "sort_order": {"type": "string", "enum": sorted(SORT_ORDERS)},
        "answer_format": {"type": "string", "enum": sorted(ANSWER_FORMATS)},
        "answerable": {"type": "boolean"},
        "reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": [
        "manager_query", "issuer_query", "quarter_texts", "form_types",
        "metric", "aggregate", "group_by", "option_type", "direct_only",
        "top_n", "sort_order", "answer_format", "answerable", "reason",
    ],
}

SYSTEM_PROMPT = """You translate a research question about SEC 13F filings into a \
structured query plan. You never answer the question yourself and never invent \
data -- you only choose values for the fields of the plan.

Dataset scope: ~20 investment managers, quarters 2026Q1 and 2026Q2 only. A question \
about any other quarter is out of scope.

Field meanings:
- manager_query: the manager/fund name mentioned in the question, copied verbatim \
  from the question (e.g. "Third Point LLC"), or null if none is named.
- issuer_query: the company/security mentioned (e.g. "Apple", "Nvidia"), copied \
  verbatim, or null if none is named.
- quarter_texts: the quarter(s) mentioned, copied verbatim (e.g. "2026 Q2"), one \
  entry per quarter mentioned. Empty list if none mentioned.
- form_types: EDGAR form type(s) mentioned or implied ("13F-HR", "13F-HR/A", \
  "13F-NT", "13F-NT/A"), else empty list.
- metric: what is being measured. "value" = position value in USD. "shares" = \
  ssh_prnamt (share/principal quantity). "distinct_issuers" = count of distinct \
  issuers. "distinct_managers" = count of distinct managers. "filing_count" = \
  count of filings (e.g. counting 13F-NT filings). "position_count" = count of \
  holding rows (e.g. counting option positions).
- aggregate: "sum", "max", "min", "avg", "count", or "delta" (change between two \
  quarters -- use with quarter_texts containing exactly two quarters).
- group_by: "manager" when comparing across managers (e.g. "which manager..."), \
  "issuer" when comparing across issuers (e.g. "largest position by ... and what \
  was it"), "quarter" when comparing across quarters, "none" when the question is \
  about one specific manager/issuer with no comparison.
- option_type: "PUT" or "CALL" if the question is about options, else null.
- direct_only: true only if the question asks whether a manager reported something \
  "directly" (i.e. excluding positions attributed to another manager).
- top_n: how many results are wanted. 1 for "which manager held the most/largest", \
  larger for "top 5", 0 if not a top-N style question.
- sort_order: "desc" for largest/most/highest, "asc" for smallest/least/lowest.
- answer_format: "value" (a single number), "name" (a manager or issuer name), \
  "boolean" (yes/no question), "name_and_value" (asks for both the name and its \
  number, e.g. "largest position... and what was it"), "list_names" (asks which \
  managers/issuers satisfy a condition, e.g. "which managers filed a 13F-NT"), \
  "list_values" (asks for several numeric values).
- answerable: false if the question needs data this dataset does not have (a \
  quarter other than 2026Q1/2026Q2, a metric not covered by the fields above, or \
  information this dataset does not track). true otherwise.
- reason: null when answerable is true; a short explanation when it is false.

Respond with exactly one JSON object matching this schema, and nothing else -- no
markdown fences, no YAML, no commentary before or after it."""


@dataclass(frozen=True)
class QueryPlan:
    manager_query: str | None
    issuer_query: str | None
    quarter_texts: list[str]
    form_types: list[str]
    metric: str
    aggregate: str
    group_by: str
    option_type: str | None
    direct_only: bool
    top_n: int
    sort_order: str
    answer_format: str
    answerable: bool
    reason: str | None = field(default=None)


class PlanError(RuntimeError):
    """The model's plan was missing, malformed, or failed validation."""


def _validate(raw: Any) -> QueryPlan:
    if not isinstance(raw, dict):
        raise PlanError(f"plan is not an object: {type(raw).__name__}")

    # Guided decoding (vLLM, at grading time) always fills every required field. Without
    # it (e.g. a local Ollama/LM Studio model during development), a small model may drop
    # a field it considers unimportant. Defaulting those here -- never the fields that
    # determine *what* to compute -- keeps the agent testable against non-guided
    # endpoints without weakening validation of the fields that actually matter.
    defaults = {
        "form_types": [], "option_type": None, "direct_only": False,
        "top_n": 0, "sort_order": "desc", "reason": None,
    }
    for key, value in defaults.items():
        if raw.get(key) is None:
            raw[key] = value

    critical = set(QUERY_PLAN_SCHEMA["required"]) - set(defaults)
    missing = critical - set(raw)
    if missing:
        raise PlanError(f"plan missing field(s): {sorted(missing)}")

    metric = raw["metric"]
    aggregate = raw["aggregate"]
    group_by = raw["group_by"]
    answer_format = raw["answer_format"]
    sort_order = raw["sort_order"]
    option_type = raw["option_type"]

    if metric not in METRICS:
        raise PlanError(f"invalid metric: {metric!r}")
    if aggregate not in AGGREGATES:
        raise PlanError(f"invalid aggregate: {aggregate!r}")
    if group_by not in GROUP_BYS:
        raise PlanError(f"invalid group_by: {group_by!r}")
    if answer_format not in ANSWER_FORMATS:
        raise PlanError(f"invalid answer_format: {answer_format!r}")
    if sort_order not in SORT_ORDERS:
        raise PlanError(f"invalid sort_order: {sort_order!r}")
    if option_type is not None and option_type not in OPTION_TYPES:
        raise PlanError(f"invalid option_type: {option_type!r}")
    if not isinstance(raw["quarter_texts"], list) or not isinstance(raw["form_types"], list):
        raise PlanError("quarter_texts/form_types must be arrays")

    top_n = raw["top_n"]
    if not isinstance(top_n, int):
        raise PlanError(f"top_n must be an integer, got {top_n!r}")
    top_n = max(0, min(top_n, 50))  # 白名單範圍內夾住，避免離譜的值拖垮後續運算

    return QueryPlan(
        manager_query=raw["manager_query"],
        issuer_query=raw["issuer_query"],
        quarter_texts=[str(q) for q in raw["quarter_texts"]],
        form_types=[str(f) for f in raw["form_types"]],
        metric=metric,
        aggregate=aggregate,
        group_by=group_by,
        option_type=option_type,
        direct_only=bool(raw["direct_only"]),
        top_n=top_n,
        sort_order=sort_order,
        answer_format=answer_format,
        answerable=bool(raw["answerable"]),
        reason=raw["reason"],
    )


def plan_query(question: str) -> QueryPlan:
    """把 `question` 送進 LLM，拿回驗證過的 QueryPlan。

    驗證失敗（包含 LLM_MODE=mock 底下固定回傳的 canned JSON 對不上這裡的欄位）
    一律拋出 PlanError，由呼叫端接住並回傳 null 答案 —— 這是刻意設計成
    "驗證失敗 = 無法規劃"，而不是塞一組預設值硬跑下去。
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    raw = llm.complete_json(messages, QUERY_PLAN_SCHEMA, max_tokens=400)
    return _validate(raw)
