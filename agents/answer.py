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
    except Exception as exc: 
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
