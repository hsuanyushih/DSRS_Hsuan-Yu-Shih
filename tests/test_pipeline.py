"""Your tests. Presence and pass rate are part of how the code is read.

You do not need many. A handful covering the parts most likely to be wrong is worth more
than broad coverage of trivial code. Good candidates here:

  - CUSIP normalisation, especially leading zeros and letter-prefixed CINS codes
  - namespace handling across filings that declare it differently
  - the report period and filing-date filters
  - anything your agent does with model output before acting on it

Run with:

    python -m pytest -q

`LLM_MODE=mock` in your .env lets agent tests run with no model at all.
"""


def test_placeholder():
    """Replace this."""
    assert True
