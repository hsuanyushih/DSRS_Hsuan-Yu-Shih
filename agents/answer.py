"""Your agent: a question in, a structured answer out.

    python -m agents.answer "which manager held the largest Apple position in 2026 Q2?"

Architecture (see submission/ASSUMPTIONS.md for the reasoning):

    question -> planner.plan_query()   LLM, schema-constrained -> QueryPlan
             -> executor.execute()     pure pandas over the read-only Parquet files
             -> this module            formats {"answer", "unit", "sources"}

The LLM only ever sees the user's question text; it never sees filing-sourced free
text (name_of_issuer / title_of_class), and it never produces anything that gets
executed as code or SQL -- only whitelisted enum/string fields that planner.py
validates before executor.py touches the data. Manager/issuer name resolution
happens locally in data.py via string matching, not through the model.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from agents import executor, planner

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stderr)
logger = logging.getLogger(__name__)

VALID_UNITS = {"USD", "SHARES", "COUNT", "PERCENT", "NAME", "DATE", "NONE"}


def main(question: str) -> dict[str, Any]:
    """Answer `question` against the dataset. Never raises -- a failure is a null answer.

    Do not rename this function or change its signature.
    """
    try:
        plan = planner.plan_query(question)
        result = executor.execute(plan)
    except Exception as exc:  # noqa: BLE001 -- a crash must still score as a null answer
        logger.warning("could not answer %r: %s", question, exc)
        return {"answer": None, "unit": "NONE", "sources": [],
                "note": "Couldn't produce a valid query plan for this question."}

    if result.answer is None and result.note:
        logger.info("null answer for %r: %s", question, result.note)

    return {
        "answer": result.answer,
        "unit": result.unit,
        "sources": result.sources,
        "note": result.note,
    }


def _cli() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m agents.answer "your question"', file=sys.stderr)
        return 2

    result = main(sys.argv[1])

    # Validated here so a shape mistake surfaces while you can still fix it. The grader
    # parses stdout as JSON and reads exactly these three keys.
    if not isinstance(result, dict):
        print(f"main() must return a dict, got {type(result).__name__}", file=sys.stderr)
        return 1
    missing = {"answer", "unit", "sources"} - set(result)
    if missing:
        print(f"result missing key(s): {sorted(missing)}", file=sys.stderr)
        return 1
    if result["unit"] not in VALID_UNITS:
        print(f"unit must be one of {sorted(VALID_UNITS)}, got {result['unit']!r}",
              file=sys.stderr)
        return 1
    if not isinstance(result["sources"], list):
        print("sources must be a list of accession numbers", file=sys.stderr)
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
