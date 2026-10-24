"""Inicio (m-24842962, NAV-4) and Resultados (m-24843003, RESULTADOS-5): the counts the
owner's home and results screens show.

Read-only aggregation over tables other modules own — no table, no write, no lifecycle
of its own. See `summary.py` and `results.py`.
"""

from qualify_api.home.results import ResultsCounts, read_results_counts
from qualify_api.home.summary import WEEK, HomeCounts, read_home_counts

__all__ = ["WEEK", "HomeCounts", "ResultsCounts", "read_home_counts", "read_results_counts"]
