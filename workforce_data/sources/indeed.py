"""
Indeed Hiring Lab connector.

Daily-frequency job postings indexes (percent change vs. the Feb 1, 2020
baseline) published as CSVs on GitHub, plus the AI tracker (share of postings
mentioning AI). No API key. Data is CC-BY-4.0 — surface "Source: Indeed
Hiring Lab" wherever this data is displayed.

Repos: github.com/hiring-lab/job_postings_tracker, github.com/hiring-lab/ai-tracker
"""

import io
import time
from typing import Optional

import pandas as pd
import requests

BASE_URL = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/US"
AI_TRACKER_URL = "https://raw.githubusercontent.com/hiring-lab/ai-tracker/main/AI_posting.csv"

ATTRIBUTION = "Source: Indeed Hiring Lab (CC-BY-4.0)"

# The CSVs are 0.2–2.5 MB and update at most daily; cache parsed frames an hour
_TTL = 3600
_frames: dict[str, tuple[float, pd.DataFrame]] = {}


def _fetch_csv(url: str) -> pd.DataFrame:
    hit = _frames.get(url)
    if hit and hit[0] > time.time():
        return hit[1]
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["date"] = pd.to_datetime(df["date"])
    _frames[url] = (time.time() + _TTL, df)
    return df


def get_national_postings(start_date: Optional[str] = None, new_postings: bool = False) -> pd.DataFrame:
    """US postings index (seasonally adjusted + raw), daily.

    Args:
        start_date: 'YYYY-MM-DD' filter.
        new_postings: if True, return the new-postings index (postings on
            Indeed for 7 days or less) instead of total postings.
    """
    df = _fetch_csv(f"{BASE_URL}/aggregate_job_postings_US.csv")
    variable = "new postings" if new_postings else "total postings"
    out = df[df["variable"] == variable].copy()
    out = out.rename(columns={
        "indeed_job_postings_index_SA": "postings_index_sa",
        "indeed_job_postings_index_NSA": "postings_index_raw",
    })[["date", "postings_index_sa", "postings_index_raw"]]
    if start_date:
        out = out[out["date"] >= pd.Timestamp(start_date)]
    return out.reset_index(drop=True)


def get_state_postings(state: Optional[str] = None, start_date: Optional[str] = None) -> pd.DataFrame:
    """Postings index by US state (2-letter abbreviation), daily.

    Args:
        state: 2-letter abbreviation (e.g. 'tx'); None returns all states.
        start_date: 'YYYY-MM-DD' filter.
    """
    df = _fetch_csv(f"{BASE_URL}/state_job_postings_us.csv")
    out = df.rename(columns={"indeed_job_postings_index": "postings_index"}).copy()
    out["state"] = out["state"].str.upper()
    if state:
        out = out[out["state"] == state.strip().upper()]
    if start_date:
        out = out[out["date"] >= pd.Timestamp(start_date)]
    return out.reset_index(drop=True)


def get_sector_postings(sector: Optional[str] = None, start_date: Optional[str] = None) -> pd.DataFrame:
    """Postings index by occupational sector (e.g. 'Software Development',
    'Nursing'), daily.

    Args:
        sector: sector display name, case-insensitive substring match;
            None returns all sectors.
        start_date: 'YYYY-MM-DD' filter.
    """
    df = _fetch_csv(f"{BASE_URL}/job_postings_by_sector_US.csv")
    out = df[df["variable"] == "total postings"].copy()
    out = out.rename(columns={"indeed_job_postings_index": "postings_index", "display_name": "sector"})
    out = out[["date", "sector", "postings_index"]]
    if sector:
        out = out[out["sector"].str.contains(sector, case=False, na=False)]
    if start_date:
        out = out[out["date"] >= pd.Timestamp(start_date)]
    return out.reset_index(drop=True)


def get_metro_postings(metro: Optional[str] = None, start_date: Optional[str] = None) -> pd.DataFrame:
    """Postings index by metro area (CBSAs with 500k+ population), daily.

    Args:
        metro: metro name substring, case-insensitive (e.g. 'Seattle');
            None returns all metros.
        start_date: 'YYYY-MM-DD' filter.
    """
    df = _fetch_csv(f"{BASE_URL}/metro_job_postings_us.csv")
    out = df.rename(columns={"indeed_job_postings_index": "postings_index"}).copy()
    if metro:
        out = out[out["metro"].str.contains(metro, case=False, na=False)]
    if start_date:
        out = out[out["date"] >= pd.Timestamp(start_date)]
    return out.reset_index(drop=True)


def list_sectors() -> list[str]:
    """All sector display names in the sector postings file."""
    df = _fetch_csv(f"{BASE_URL}/job_postings_by_sector_US.csv")
    return sorted(df["display_name"].dropna().unique().tolist())


def get_ai_postings_share(country: str = "US", start_date: Optional[str] = None) -> pd.DataFrame:
    """Share of job postings mentioning AI terms (7-day trailing average),
    from the Indeed Hiring Lab AI tracker. Monthly refresh, daily frequency.

    Args:
        country: ISO-2 country code (default 'US').
        start_date: 'YYYY-MM-DD' filter.
    """
    df = _fetch_csv(AI_TRACKER_URL)
    out = df[df["jobcountry"] == country.upper()].copy()
    out = out.rename(columns={"AI_share_postings": "ai_share_pct"})[["date", "ai_share_pct"]]
    if start_date:
        out = out[out["date"] >= pd.Timestamp(start_date)]
    return out.reset_index(drop=True)
