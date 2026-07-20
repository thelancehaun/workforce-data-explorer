"""
Anthropic Economic Index connector.

Occupation- and task-level measures of real-world AI usage, derived from
anonymized Claude conversations mapped to O*NET tasks and SOC occupations.
Published as open CSVs on Hugging Face; no key required.

Dataset: huggingface.co/datasets/Anthropic/EconomicIndex
"""

import io
import time
from typing import Optional

import pandas as pd
import requests

BASE_URL = "https://huggingface.co/datasets/Anthropic/EconomicIndex/resolve/main"

ATTRIBUTION = "Source: Anthropic Economic Index"

_TTL = 86400  # dataset updates a few times a year
_frames: dict[str, tuple[float, pd.DataFrame]] = {}


def _fetch_csv(path: str) -> pd.DataFrame:
    hit = _frames.get(path)
    if hit and hit[0] > time.time():
        return hit[1]
    resp = requests.get(f"{BASE_URL}/{path}", timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    _frames[path] = (time.time() + _TTL, df)
    return df


def get_job_exposure(occupation: Optional[str] = None) -> pd.DataFrame:
    """AI-usage exposure by occupation (0–1 share of the occupation's tasks
    observed in real Claude usage), for 756 SOC occupations.

    Args:
        occupation: optional filter — SOC code prefix ('15-1252') or
            case-insensitive title substring ('software').
    """
    df = _fetch_csv("labor_market_impacts/job_exposure.csv").copy()
    df = df.sort_values("observed_exposure", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    if occupation:
        q = occupation.strip()
        mask = df["occ_code"].str.startswith(q.split(".")[0]) | df["title"].str.contains(q, case=False, na=False)
        df = df[mask]
    return df.reset_index(drop=True)


def get_task_penetration(search: Optional[str] = None, top_n: int = 50) -> pd.DataFrame:
    """AI penetration for ~18,000 O*NET work tasks (share observed in real
    Claude usage).

    Args:
        search: case-insensitive substring to filter task text.
        top_n: rows to return (sorted by penetration, descending).
    """
    df = _fetch_csv("labor_market_impacts/task_penetration.csv")
    if search:
        df = df[df["task"].str.contains(search, case=False, na=False)]
    return df.sort_values("penetration", ascending=False).head(top_n).reset_index(drop=True)
