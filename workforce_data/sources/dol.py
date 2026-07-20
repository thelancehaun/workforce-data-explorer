"""
DOL Open Data Portal connector.
Covers OSHA inspections, Wage & Hour enforcement, VETS-4212, and
UI claims (via FRED).

Portal: https://dataportal.dol.gov — API v4 at https://apiprod.dol.gov/v4
All v4 endpoints require a free API key (register at https://dataportal.dol.gov).
H-1B LCA disclosure data has no API; DOL publishes quarterly Excel files only.
"""

import json
import os
from typing import Optional
import pandas as pd
import requests

DOL_API_BASE = "https://apiprod.dol.gov/v4"

REGISTER_MSG = (
    "DOL_API_KEY not set. The DOL API requires a free key — register at "
    "https://dataportal.dol.gov and add DOL_API_KEY to your .env file."
)


def _api_key() -> str:
    return os.getenv("DOL_API_KEY", "")


def _get_v4(agency: str, endpoint: str, params: dict) -> pd.DataFrame:
    """Fetch records from a DOL API v4 dataset. Raises if no API key is set."""
    key = _api_key()
    if not key:
        raise ValueError(REGISTER_MSG)

    url = f"{DOL_API_BASE}/get/{agency}/{endpoint}/json"
    # DOL v4 accepts the key only as a query parameter (a 401 comes back if
    # it's sent as an X-API-KEY header)
    resp = requests.get(url, params={**params, "X-API-KEY": key}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    records = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(records, list) and records:
        return pd.DataFrame(records)
    return pd.DataFrame()


def get_osha_inspections(
    state: Optional[str] = None,
    industry_code: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 500,
) -> pd.DataFrame:
    """
    Fetch OSHA inspection records via the DOL API v4 (requires free DOL_API_KEY).

    Args:
        state: 2-letter state code (e.g. 'CA', 'TX')
        industry_code: NAICS code filter
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
        limit: max records to return
    """
    conditions = []
    if state:
        conditions.append({"field": "site_state", "operator": "eq", "value": state})
    if start_date:
        conditions.append({"field": "open_date", "operator": "gt", "value": start_date})
    if end_date:
        conditions.append({"field": "open_date", "operator": "lt", "value": end_date})
    if industry_code:
        conditions.append({"field": "naics_code", "operator": "eq", "value": industry_code})

    params: dict = {"limit": limit, "sort": "desc", "sort_by": "open_date"}
    if len(conditions) == 1:
        params["filter_object"] = json.dumps(conditions[0])
    elif conditions:
        params["filter_object"] = json.dumps({"and": conditions})

    return _get_v4("osha", "inspection", params)


def get_whd_enforcement(
    state: Optional[str] = None,
    industry: Optional[str] = None,
    limit: int = 500,
) -> pd.DataFrame:
    """
    Fetch WHD (Wage and Hour Division) enforcement actions via the DOL API v4
    (requires free DOL_API_KEY).
    Includes FLSA violations, back wages assessed, employees affected.
    """
    params: dict = {"limit": limit}
    if state:
        params["filter_object"] = json.dumps(
            {"field": "st_cd", "operator": "eq", "value": state}
        )
    return _get_v4("whd", "enforcement", params)


def get_h1b_disclosures(year: int = 2024, limit: int = 1000) -> pd.DataFrame:
    """
    H-1B Labor Condition Application (LCA) disclosure data.

    DOL does not offer an API for LCA disclosures — only quarterly Excel files at
    https://www.dol.gov/agencies/eta/foreign-labor/performance. Returns an empty
    DataFrame so callers can surface that guidance.
    """
    return pd.DataFrame()


def get_bls_ui_claims(weeks: int = 52) -> pd.DataFrame:
    """
    Fetch weekly unemployment insurance initial claims data via FRED (most reliable source).
    This wraps the FRED series for UI claims.
    """
    from datetime import datetime, timedelta
    from .fred import get_series

    end = datetime.now()
    start = end - timedelta(weeks=weeks)

    try:
        df = get_series(
            "ICSA",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        df = df.rename(columns={"value": "initial_claims_thousands"})
        df["series"] = "Initial Claims (Seasonally Adjusted, Thousands)"
        return df[["date", "initial_claims_thousands", "series"]]
    except Exception:
        return pd.DataFrame()
