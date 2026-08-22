# Dependencies

Additions to `requirements-extra.txt`, beyond what's already pinned in the
frozen `requirements.txt`.

| Package | Version | Why |
|---|---|---|
| `pandas` | `3.0.1` | Used in `agents/data.py` and `agents/executor.py` for all read-only filtering, grouping, and aggregation over the two Parquet tables (`filings.parquet`, `holdings.parquet`) that back Chapter 4's agent. `pyarrow` (already in `requirements.txt`) is used to read the Parquet files into memory, but the actual query logic -- filtering by quarter/manager/issuer, grouping and summing, computing deltas between quarters -- is written against a `pandas.DataFrame`, not raw Arrow tables. No SQL, `eval`, or dynamically constructed query strings are used anywhere; every operation in `executor.py` is a whitelisted-field pandas filter/groupby/sort call built entirely from validated `QueryPlan` fields (see `submission/ASSUMPTIONS.md`). |

No other third-party packages were added. Everything else imported across
`src/`, `agents/`, and `submission/eda.py` is either already pinned in the
frozen `requirements.txt` (`httpx`, `pyarrow`, `openai`, `python-dotenv`) or
part of the Python standard library (`csv`, `re`, `json`, `logging`,
`hashlib`, `time`, `functools`, `difflib`, `datetime`, `pathlib`, `typing`,
`dataclasses`, `urllib.parse`, `xml.etree.ElementTree`, `collections`, `sys`,
`os`).
