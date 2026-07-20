"""
Census Bureau API connector.
Covers ACS, LEHD/QWI, and County Business Patterns.

API key: https://api.census.gov/data/key_signup.html (free, instant email)
"""

import os
from typing import Optional
import pandas as pd
import requests

BASE_URL = "https://api.census.gov/data"

# ACS variable groups for common queries
ACS_VARIABLES = {
    # Employment
    "employed": "B23025_004E",
    "unemployed": "B23025_005E",
    "not_in_labor_force": "B23025_007E",
    "labor_force": "B23025_003E",
    "population_16plus": "B23025_001E",
    # Income
    "median_household_income": "B19013_001E",
    "median_individual_earnings": "B20002_001E",
    "per_capita_income": "B19301_001E",
    # Commuting
    "work_from_home": "B08006_017E",
    "drive_alone": "B08006_003E",
    "carpool": "B08006_004E",
    "public_transit": "B08006_008E",
    "walk": "B08006_015E",
    "mean_travel_time": "B08135_001E",
    # Education
    "bachelors_or_higher": "B15003_022E",
    "high_school_grad": "B15003_017E",
    "population_25plus": "B15003_001E",
    # Demographics
    "total_population": "B01003_001E",
    "median_age": "B01002_001E",
    # Poverty
    "below_poverty": "B17001_002E",
    "poverty_universe": "B17001_001E",
}

# QWI indicator codes
QWI_INDICATORS = {
    "employment": "Emp",
    "employment_end": "EmpEnd",
    "employment_full_quarter": "EmpS",
    "hires_all": "HirA",
    "hires_new": "HirN",
    "separations": "Sep",
    "earnings_full_quarter": "EarnS",
    "earnings_all_workers": "EarnHirAS",
    "job_creation": "JbC",
    "job_destruction": "JbD",
}

GEO_CODES = {
    "national": {"for": "us:1"},
    "state": {"for": "state:*"},
    "county": {"for": "county:*", "in": "state:*"},
}


def _api_key() -> str:
    return os.getenv("CENSUS_API_KEY", "")


def _key_param() -> dict:
    key = _api_key()
    return {"key": key} if key else {}


def get_acs(
    variables: list[str],
    year: int = 2022,
    geography: str = "state",
    state_fips: Optional[str] = None,
    dataset: str = "acs/acs1",
) -> pd.DataFrame:
    """
    Fetch ACS data for specified variables.

    Args:
        variables: list of ACS variable codes (e.g. ['B23025_004E', 'B19013_001E'])
                   or friendly names from ACS_VARIABLES dict
        year: survey year (default 2022; acs1 not available for all years/geographies)
        geography: 'national', 'state', 'county', or 'metro'
        state_fips: 2-digit state FIPS code (e.g. '06' for California) for county queries
        dataset: 'acs/acs1' (1-year) or 'acs/acs5' (5-year, more geography levels)
    """
    resolved_vars = []
    for v in variables:
        if v in ACS_VARIABLES:
            resolved_vars.append(ACS_VARIABLES[v])
        else:
            resolved_vars.append(v)

    get_vars = ",".join(["NAME"] + resolved_vars)

    params = {"get": get_vars, **_key_param()}

    if geography == "national":
        params["for"] = "us:1"
        url = f"{BASE_URL}/{year}/{dataset}"
    elif geography == "state":
        params["for"] = "state:*"
        url = f"{BASE_URL}/{year}/{dataset}"
    elif geography == "county":
        params["for"] = "county:*"
        if state_fips:
            params["in"] = f"state:{state_fips}"
        else:
            params["in"] = "state:*"
        url = f"{BASE_URL}/{year}/{dataset}"
    elif geography == "metro":
        params["for"] = "metropolitan statistical area/micropolitan statistical area:*"
        url = f"{BASE_URL}/{year}/{dataset}"
    else:
        raise ValueError(f"Unknown geography: {geography}")

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data or len(data) < 2:
        return pd.DataFrame()

    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)

    # Convert numeric columns
    for col in resolved_vars:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Rename resolved vars back to friendly names where possible
    reverse_map = {v: k for k, v in ACS_VARIABLES.items()}
    df = df.rename(columns=reverse_map)

    return df


def get_qwi(
    indicators: list[str],
    state_fips: str = "*",
    year_start: int = 2015,
    year_end: int = 2023,
    geography: str = "state",
    industry: str = "00",
    sex: str = "0",
    age_group: str = "A00",
    education: str = "E0",
    seasonadj: str = "U",
) -> pd.DataFrame:
    """
    Fetch LEHD Quarterly Workforce Indicators (QWI).

    Args:
        indicators: list from QWI_INDICATORS keys or raw codes (e.g. ['employment', 'hires_all'])
        state_fips: 2-digit state FIPS or '*' for all states (not all states support all years)
        year_start / year_end: year range
        geography: 'state' or 'county'
        industry: 2-digit NAICS or '00' for all industries
        sex: '0'=all, '1'=male, '2'=female
        age_group: 'A00'=all ages
        education: 'E0'=all education
        seasonadj: 'U'=unadjusted, 'S'=seasonally adjusted
    """
    resolved = []
    for ind in indicators:
        if ind in QWI_INDICATORS:
            resolved.append(QWI_INDICATORS[ind])
        else:
            resolved.append(ind)

    # QWI lives at the timeseries endpoint; /sa is the sex-by-age tabulation,
    # /se is sex-by-education. Time is passed as a from/to range, not a URL year.
    if education != "E0":
        endpoint, demo_params = "se", {"sex": sex, "education": education}
    else:
        endpoint, demo_params = "sa", {"sex": sex, "agegrp": age_group}

    url = f"{BASE_URL}/timeseries/qwi/{endpoint}"
    params = {
        "get": ",".join(resolved),
        "time": f"from {year_start}-Q1 to {year_end}-Q4",
        "industry": industry,
        "ownercode": "A05",
        "seasonadj": seasonadj,
        **demo_params,
        **_key_param(),
    }
    if geography == "county":
        params["for"] = "county:*"
        params["in"] = f"state:{state_fips}" if state_fips != "*" else "state:*"
    else:
        params["for"] = f"state:{state_fips}"

    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if not data or len(data) < 2:
        return pd.DataFrame()

    df = pd.DataFrame(data[1:], columns=data[0])
    for col in resolved:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # time comes back as 'YYYY-QN'
    parts = df["time"].str.extract(r"(\d{4})-Q(\d)")
    df["year"] = parts[0].astype(int)
    df["quarter"] = parts[1].astype(int)
    df["date"] = pd.to_datetime(
        df["year"].astype(str) + "-" + ((df["quarter"] - 1) * 3 + 1).astype(str).str.zfill(2) + "-01"
    )
    return df.sort_values("date").reset_index(drop=True)


def get_cbp(
    year: int = 2021,
    geography: str = "state",
    naics_code: str = "",
    state_fips: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch County Business Patterns data.

    Args:
        year: survey year
        geography: 'national', 'state', or 'county'
        naics_code: NAICS code filter (e.g. '62' for Health Care, '' for all)
        state_fips: required for county geography
    """
    url = f"{BASE_URL}/{year}/cbp"
    get_vars = "ESTAB,EMP,PAYANN,NAICS2017,NAICS2017_LABEL,NAME"

    params = {"get": get_vars, **_key_param()}

    if geography == "national":
        params["for"] = "us:*"
    elif geography == "state":
        params["for"] = "state:*"
    elif geography == "county":
        params["for"] = "county:*"
        if state_fips:
            params["in"] = f"state:{state_fips}"

    if naics_code:
        params["NAICS2017"] = naics_code

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data or len(data) < 2:
        return pd.DataFrame()

    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)
    for col in ["ESTAB", "EMP", "PAYANN"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def list_acs_variables() -> dict:
    """Return the curated ACS variable map."""
    return ACS_VARIABLES


def list_qwi_indicators() -> dict:
    """Return the curated QWI indicator map."""
    return QWI_INDICATORS
