#!/usr/bin/env python3
"""Run the whole pipeline: fetch from EDGAR, parse, write the dataset.

Entry point called by the grader. Must work from a clean checkout with
nothing in output/. Runs, in order:

    1. cik_verify       verify/correct the 20 CIKs against SEC's lookup file
    2. discover_filings find the in-scope 13F filings via the submissions API
    3. download_filings fetch and cache the filing XML
    4. parse_filings    parse into filings.parquet / holdings.parquet

"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILERS = ROOT / "filers.csv"
OUTPUT = ROOT / "output"
SRC = ROOT / "src"
UA_PATTERN = re.compile(r"^\S.*\s+[^@\s]+@[^@\s]+\.[a-z]{2,}\s*$", re.I)


def run(user_agent: str, output: Path) -> None:
    """Build the dataset by running each chapter's script in sequence."""
    sys.path.insert(0, str(SRC))

    from fetch import set_user_agent
    set_user_agent(user_agent)

    import cik_verify
    import discover_filings
    import download_filings
    import parse_filings

    steps = [
        ("CIK verification", cik_verify.main),
        ("Filing discovery", discover_filings.main),
        ("Filing download", download_filings.main),
        ("Parse to Parquet", parse_filings.main),
    ]

    for label, step in steps:
        logging.info("=== %s ===", label)
        exit_code = step()
        if exit_code != 0:
            sys.exit(f"{label} failed (exit code {exit_code}); aborting pipeline.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-agent", required=True,
                    help='required by SEC: "FirstName LastName netid@illinois.edu"')
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args()

    if not UA_PATTERN.match(args.user_agent):
        sys.exit(
            "invalid --user-agent.\n"
            "SEC requires a contact address and rejects requests without one.\n"
            '  python main.py --user-agent "Jane Doe jdoe@illinois.edu"'
        )

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args.output.mkdir(parents=True, exist_ok=True)
    run(args.user_agent, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())