"""Your agent: a question in, a structured answer out.

Yours to rewrite. One thing is fixed — `main(question) -> dict` must exist, because we
call it directly:

    python -m agents.answer "which manager held the largest Apple position in 2026 Q2?"

Return this shape. Nothing else on stdout.

    {
      "answer":  <number | string | list | null>,
      "unit":    "USD" | "SHARES" | "COUNT" | "PERCENT" | "NAME" | "DATE" | "NONE",
      "sources": ["0001423053-26-000012", ...]
    }

`sources` is graded separately from `answer`, and it is the more diagnostic of the two.
An agent that produces the right number without knowing which filings it came from is
not one a researcher can trust with a question they cannot check by hand.

Put logging on stderr. stdout carries the JSON and nothing else.

See agents/llm.py for the model interface, and docs/04-serve.md for what is graded.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

OUTPUT = Path(__file__).resolve().parents[1] / "output"
FILINGS = OUTPUT / "filings.parquet"
HOLDINGS = OUTPUT / "holdings.parquet"

VALID_UNITS = {"USD", "SHARES", "COUNT", "PERCENT", "NAME", "DATE", "NONE"}


def main(question: str) -> dict[str, Any]:
    """Answer `question` against your dataset.

    Do not rename this function or change its signature.
    """
    raise NotImplementedError("Implement your agent here. See docs/04-serve.md.")


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
