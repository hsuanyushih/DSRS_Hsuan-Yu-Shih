# Dependencies

Extra packages I added to `requirements-extra.txt`, on top of what's already
in the frozen `requirements.txt`.

| Package | Version | Why |
|---|---|---|
| `pandas` | `3.0.1` | I use this in `agents/data.py` and `executor.py` to filter, group, and sum the two Parquet tables for Chapter 4's agent. `pyarrow` just reads the files in; the actual filtering and grouping logic runs on a pandas DataFrame. Every query in `executor.py` only touches a fixed set of whitelisted columns based on the validated QueryPlan fields. |


I didn't add anything else. Everything else I import in `src/`, `agents/`,
and `submission/eda.py` is either already in `requirements.txt` (`httpx`,
`pyarrow`, `openai`, `python-dotenv`) or comes from Python's standard
library (`csv`, `re`, `json`, `logging`, `hashlib`, `time`, `functools`,
`difflib`, `datetime`, `pathlib`, `typing`, `dataclasses`, `urllib.parse`,
`xml.etree.ElementTree`, `collections`, `sys`, `os`).
