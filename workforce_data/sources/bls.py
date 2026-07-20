"""
BLS (Bureau of Labor Statistics) API v2 connector.
Covers series not available via FRED: OEWS, NCS, IIF, BED, and full series catalogs.

API key: https://data.bls.gov/registrationEngine/ (free)
Rate limits: 25 series/request, 500 requests/day (v2 with key)
"""

import os
from typing import Optional
import pandas as pd
import requests

BASE_URL = "https://api.bls.gov/publicAPI/v2"

# Common BLS series for quick access — organized by survey
POPULAR_SERIES = {
    # CES — Current Employment Statistics
    "ces_total_nonfarm": "CES0000000001",
    "ces_private": "CES0500000001",
    "ces_manufacturing": "CES3000000001",
    "ces_professional_business": "CES6000000001",
    "ces_education_health": "CES6500000001",
    "ces_leisure_hospitality": "CES7000000001",
    "ces_government": "CES9000000001",
    "ces_avg_hourly_earnings": "CES0500000003",
    "ces_avg_weekly_hours": "CES0500000007",
    # CPS — Current Population Survey
    "cps_unemployment_rate": "LNS14000000",
    "cps_labor_force_participation": "LNS11300000",
    "cps_employed": "LNS12000000",
    "cps_unemployed": "LNS13000000",
    "cps_not_in_labor_force": "LNS15000000",
    # JOLTS — Job Openings and Labor Turnover
    "jolts_openings_total": "JTS000000000000000JOL",
    "jolts_hires_total": "JTS000000000000000HIL",
    "jolts_quits_total": "JTS000000000000000QUL",
    "jolts_layoffs_total": "JTS000000000000000LDL",
    "jolts_separations_total": "JTS000000000000000TSL",
    # ECI — Employment Cost Index
    "eci_total_compensation": "CIS1010000000000I",
    "eci_wages_salaries": "CIS1020000000000I",
    "eci_benefits": "CIS1030000000000I",
    # Productivity
    "productivity_nonfarm_business": "PRS85006092",
    "unit_labor_costs_nonfarm": "PRS85006112",
    # OEWS — Occupational Employment (national averages)
    "oews_all_occupations_mean_wage": "OEUN000000000000000000004",
}

# OEWS series format: OEU + seasonal/area-type + area(7) + industry(6) + occupation(6) + datatype(2)
# e.g. OEUN000000000000015125204 = national, all industries, SOC 15-1252, mean annual wage
# datatype: 04 = mean annual wage, 01 = employment, 03 = mean hourly wage
# Note: the BLS API only serves the most recent OEWS survey year.


def _api_key() -> str:
    return os.getenv("BLS_API_KEY", "")


def _headers() -> dict:
    key = _api_key()
    if key:
        return {"Content-Type": "application/json", "registrationkey": key}
    return {"Content-Type": "application/json"}


def get_series(
    series_ids: list[str],
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    annual_average: bool = False,
) -> pd.DataFrame:
    """
    Fetch one or more BLS series by their series IDs.
    Max 25 series per call with a registered key; 10 without.

    Returns a tidy DataFrame with columns: series_id, year, period, value, footnotes.
    """
    from datetime import datetime
    current_year = datetime.now().year

    if not start_year:
        start_year = current_year - 10
    if not end_year:
        end_year = current_year

    # BLS API allows max 20-year windows
    if end_year - start_year > 20:
        start_year = end_year - 20

    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
        "annualaverage": annual_average,
        "catalog": False,
        "calculations": False,
    }
    key = _api_key()
    if key:
        payload["registrationkey"] = key

    resp = requests.post(f"{BASE_URL}/timeseries/data/", json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "REQUEST_SUCCEEDED":
        messages = data.get("message", [])
        raise RuntimeError(f"BLS API error: {messages}")

    rows = []
    for series in data.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        for obs in series.get("data", []):
            value = obs.get("value", "")
            try:
                value = float(value)
            except (ValueError, TypeError):
                value = None
            rows.append({
                "series_id": sid,
                "year": int(obs["year"]),
                "period": obs["period"],
                "period_name": obs.get("periodName", ""),
                "value": value,
                "footnotes": ", ".join(f.get("text", "") for f in obs.get("footnotes", []) if f),
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Parse period into a proper date
    df["date"] = pd.to_datetime(
        df.apply(_period_to_date, axis=1), errors="coerce"
    )
    df = df.sort_values(["series_id", "date"]).reset_index(drop=True)
    return df


def _period_to_date(row) -> str:
    """Convert BLS year/period to an ISO date string."""
    year = row["year"]
    period = row["period"]
    if period.startswith("M"):
        month = int(period[1:])
        return f"{year}-{month:02d}-01"
    elif period.startswith("Q"):
        quarter = int(period[1:])
        month = (quarter - 1) * 3 + 1
        return f"{year}-{month:02d}-01"
    elif period == "A01":
        return f"{year}-01-01"
    return f"{year}-01-01"


def get_popular(
    series_name: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch a series from the curated POPULAR_SERIES map by friendly name."""
    series_id = POPULAR_SERIES.get(series_name)
    if not series_id:
        matches = [k for k in POPULAR_SERIES if series_name.lower() in k]
        if matches:
            raise ValueError(
                f"'{series_name}' not found. Did you mean one of: {matches}?"
            )
        raise ValueError(
            f"'{series_name}' not in popular series map. "
            f"Use get_series([series_id]) directly or check list_popular()."
        )
    return get_series([series_id], start_year=start_year, end_year=end_year)


def list_popular() -> list[str]:
    """Return the names of all curated popular series."""
    return sorted(POPULAR_SERIES.keys())


def get_oews_occupation(
    soc_code: str,
    area_code: str = "0000000",
    data_type: str = "M04",
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> pd.DataFrame:
    """
    Fetch OEWS data for a specific occupation.

    Note: the BLS API only serves the most recent OEWS survey year, so the
    returned frame typically has a single observation per series.

    Args:
        soc_code: SOC code without hyphen (e.g., '151252' for Software Developers)
        area_code: '0000000' for national, or a BLS area code for state/metro
        data_type: 'M04'/'04' = mean annual wage, 'M01'/'01' = employment,
                   'M03'/'03' = mean hourly wage ('M02' is accepted as employment)
    """
    dt = data_type.upper().lstrip("M").zfill(2)
    if dt == "02":  # legacy alias used by older callers for employment
        dt = "01"
    area = area_code.zfill(7)
    area_type = "N" if area.strip("0") == "" else "S"
    series_id = f"OEU{area_type}{area}000000{soc_code}{dt}"
    return get_series([series_id], start_year=start_year, end_year=end_year)


def get_series_catalog(series_id: str) -> dict:
    """Fetch metadata for a BLS series."""
    key = _api_key()
    payload = {
        "seriesid": [series_id],
        "catalog": True,
    }
    if key:
        payload["registrationkey"] = key

    resp = requests.post(f"{BASE_URL}/timeseries/data/", json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    series_list = data.get("Results", {}).get("series", [{}])
    if series_list:
        return series_list[0].get("catalog", {})
    return {}
