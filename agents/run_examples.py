"""Run agents/answer.py over docs/questions-examples.md and write output/agent_usage.json."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from agents import answer, llm

QUESTIONS_DOC = Path(__file__).resolve().parents[1] / "docs" / "questions-examples.md"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "output" / "agent_usage.json"


def _load_questions() -> list[str]:
    text = QUESTIONS_DOC.read_text(encoding="utf-8")
    fenced = re.search(r"```\n(.*?)```", text, re.DOTALL)
    if not fenced:
        raise RuntimeError(f"no fenced question block found in {QUESTIONS_DOC}")
    return [line.strip() for line in fenced.group(1).splitlines() if line.strip()]


def main() -> int:
    questions = _load_questions()
    per_question = []

    for question in questions:
        before = llm.usage()
        start = time.perf_counter()
        result = answer.main(question)
        elapsed = time.perf_counter() - start
        after = llm.usage()

        per_question.append({
            "question": question,
            "calls": after["calls"] - before["calls"],
            "prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
            "completion_tokens": after["completion_tokens"] - before["completion_tokens"],
            "elapsed_seconds": round(elapsed, 3),
        })
        print(f"{question}\n  -> {json.dumps(result)}", file=sys.stderr)

    totals = llm.usage()
    report = {
        "questions": per_question,
        "totals": {
            "calls": totals["calls"],
            "prompt_tokens": totals["prompt_tokens"],
            "completion_tokens": totals["completion_tokens"],
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
