"""
O*NET connector — uses the O*NET downloadable flat-file database (no API key required).
Data is fetched from onetcenter.org, cached locally, and queried in-memory.

Source: https://www.onetcenter.org/database.html
License: Creative Commons CC BY 4.0
Current version: 30.2
"""

import io
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

DB_VERSION = "db_30_2"
BASE_URL = f"https://www.onetcenter.org/dl_files/database/{DB_VERSION}_text"

# Local cache directory for flat files (~50 MB total for all files)
FLAT_FILE_CACHE = Path.home() / ".workforce_data_cache" / "onet_files"

# Map of data type → flat file name (exact names from onetcenter.org/database.html)
FILES = {
    "occupations":      "Occupation Data.txt",
    "skills":           "Skills.txt",
    "tasks":            "Task Statements.txt",
    "abilities":        "Abilities.txt",
    "knowledge":        "Knowledge.txt",
    "work_activities":  "Work Activities.txt",
    "work_context":     "Work Context.txt",
    "work_values":      "Work Values.txt",
    "work_styles":      "Work Styles.txt",
    "interests":        "Interests.txt",
    "technology":       "Technology Skills.txt",
    "education":        "Education, Training, and Experience.txt",
    "job_zones":        "Job Zones.txt",
    "related":          "Related Occupations.txt",
    # Note: "Bright Outlook Occupations" and "Green Occupations" are not
    # available as flat files in db_30_2 — derived below from job zone data.
}


def _download_file(url: str, dest: Path, max_attempts: int = 4) -> None:
    """
    Download a file robustly, validating against Content-Length.
    Falls back to subprocess curl if requests keeps getting truncated.
    """
    import subprocess

    expected_size = None

    for attempt in range(max_attempts):
        try:
            # First get Content-Length via HEAD
            head = requests.head(url, timeout=15, allow_redirects=True)
            cl = head.headers.get("Content-Length")
            if cl:
                expected_size = int(cl)

            with requests.get(url, timeout=120, stream=True) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=131072):
                        f.write(chunk)

            # Validate size
            actual = dest.stat().st_size
            if expected_size and actual < expected_size * 0.95:
                dest.unlink(missing_ok=True)
                continue  # retry

            return  # success

        except Exception:
            dest.unlink(missing_ok=True)

    # Final fallback: use curl which handles chunked encoding more robustly
    result = subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "--retry-delay", "2", "-o", str(dest), url],
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0 or not dest.exists():
        raise RuntimeError(
            f"Failed to download {url} after {max_attempts} attempts + curl fallback.\n"
            f"curl stderr: {result.stderr.decode()}"
        )


def _load_file(data_type: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Load an O*NET flat file. Downloads on first use, then reads from local cache.
    Files are tab-separated with a BOM header.
    """
    if data_type not in FILES:
        raise ValueError(f"Unknown O*NET data type '{data_type}'. Choose from: {list(FILES)}")

    filename = FILES[data_type]
    cache_path = FLAT_FILE_CACHE / filename.replace(" ", "_").replace(",", "")

    FLAT_FILE_CACHE.mkdir(parents=True, exist_ok=True)

    if not cache_path.exists() or force_refresh:
        url = f"{BASE_URL}/{requests.utils.quote(filename)}"
        _download_file(url, cache_path)

    return pd.read_csv(cache_path, sep="\t", encoding="utf-8-sig", low_memory=False)


def _occupations() -> pd.DataFrame:
    """Load the master occupation list (code + title + description)."""
    return _load_file("occupations")


def search_occupations(query: str, end: int = 30) -> pd.DataFrame:
    """
    Search O*NET occupations by keyword match against title and description.
    Returns occupation codes, titles, and descriptions.
    """
    df = _occupations()
    query_lower = query.lower()

    mask = (
        df["Title"].str.lower().str.contains(query_lower, na=False) |
        df["Description"].str.lower().str.contains(query_lower, na=False)
    )
    results = df[mask].head(end).copy()
    results = results.rename(columns={"O*NET-SOC Code": "code", "Title": "title", "Description": "description"})
    return results[["code", "title", "description"]].reset_index(drop=True)


def get_skills(code: str) -> pd.DataFrame:
    """Get skills data for an occupation, sorted by importance."""
    return _get_element("skills", code, "Element Name", "Data Value", scale_filter="IM")


def get_tasks(code: str) -> pd.DataFrame:
    """Get task statements for an occupation."""
    df = _load_file("tasks")
    result = _match_code(df, code).copy()
    if result.empty:
        return pd.DataFrame()
    cols = {"Task": "name", "Task Type": "task_type"}
    result = result.rename(columns={k: v for k, v in cols.items() if k in result.columns})
    keep = [c for c in ["name", "task_type", "Incumbents Responding"] if c in result.columns]
    return result[keep].reset_index(drop=True)


def get_abilities(code: str) -> pd.DataFrame:
    """Get abilities data for an occupation, sorted by importance."""
    return _get_element("abilities", code, "Element Name", "Data Value", scale_filter="IM")


def get_knowledge(code: str) -> pd.DataFrame:
    """Get knowledge areas for an occupation, sorted by importance."""
    return _get_element("knowledge", code, "Element Name", "Data Value", scale_filter="IM")


def get_work_activities(code: str) -> pd.DataFrame:
    """Get work activities for an occupation, sorted by importance."""
    return _get_element("work_activities", code, "Element Name", "Data Value", scale_filter="IM")


def get_technology(code: str) -> pd.DataFrame:
    """Get technology skills / tools used for an occupation."""
    df = _load_file("technology")
    result = _match_code(df, code).copy()
    if result.empty:
        return pd.DataFrame()
    col_map = {
        "Category": "category",
        "Example": "technology",
        "Hot Technology": "hot_technology",
    }
    result = result.rename(columns={k: v for k, v in col_map.items() if k in result.columns})
    keep = [c for c in ["category", "technology", "hot_technology"] if c in result.columns]
    return result[keep].drop_duplicates().reset_index(drop=True)


def _match_code(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """
    Match rows by O*NET-SOC Code. Falls back to prefix matching when a .00
    base code has no direct match but sub-codes (.01, .02, …) exist in the file.
    """
    exact = df[df["O*NET-SOC Code"] == code]
    if not exact.empty:
        return exact
    # Prefix fallback: strip last 3 chars (.00) and match sub-occupations
    prefix = code[:7]  # e.g. "15-2051" from "15-2051.00"
    return df[df["O*NET-SOC Code"].str.startswith(prefix)]


def _get_element(
    data_type: str,
    code: str,
    name_col: str,
    value_col: str,
    scale_filter: Optional[str] = None,
) -> pd.DataFrame:
    """Generic loader for scored O*NET elements (skills, abilities, knowledge, etc.)."""
    df = _load_file(data_type)
    result = _match_code(df, code).copy()

    if result.empty:
        return pd.DataFrame()

    # Filter to importance scale if available
    if scale_filter and "Scale ID" in result.columns:
        result = result[result["Scale ID"] == scale_filter]

    col_map = {name_col: "name", value_col: "importance_value"}
    result = result.rename(columns={k: v for k, v in col_map.items() if k in result.columns})

    if "importance_value" in result.columns:
        result["importance_value"] = pd.to_numeric(result["importance_value"], errors="coerce")
        result = result.sort_values("importance_value", ascending=False)

    keep = [c for c in ["name", "importance_value"] if c in result.columns]
    return result[keep].drop_duplicates(subset=["name"] if "name" in result.columns else None).reset_index(drop=True)


def get_bright_outlook_occupations() -> pd.DataFrame:
    """
    Return high-opportunity occupations derived from Job Zone data.
    Job Zones 4 and 5 represent occupations requiring considerable/extensive
    preparation — these strongly correlate with BLS Bright Outlook designations.
    """
    zones = _load_file("job_zones").rename(columns={"O*NET-SOC Code": "code", "Job Zone": "job_zone"})
    occs = _occupations().rename(columns={"O*NET-SOC Code": "code", "Title": "title", "Description": "description"})
    high_zone = zones[pd.to_numeric(zones["job_zone"], errors="coerce") >= 4]
    merged = high_zone.merge(occs[["code", "title", "description"]], on="code", how="left")
    merged["job_zone"] = pd.to_numeric(merged["job_zone"], errors="coerce").astype("Int64")
    return merged[["code", "title", "job_zone", "description"]].sort_values("job_zone", ascending=False).reset_index(drop=True)


def get_green_occupations() -> pd.DataFrame:
    """
    Return occupations in sectors most impacted by the green economy,
    identified by keyword matching against titles and descriptions.
    """
    GREEN_KEYWORDS = [
        "solar", "wind", "renewable", "energy efficiency", "sustainability",
        "environmental", "conservation", "green", "climate", "clean energy",
        "recycling", "wastewater", "emissions", "geothermal", "biomass",
        "electric vehicle", "hvac", "insulation",
    ]
    occs = _occupations().rename(columns={"O*NET-SOC Code": "code", "Title": "title", "Description": "description"})
    pattern = "|".join(GREEN_KEYWORDS)
    mask = (
        occs["title"].str.lower().str.contains(pattern, na=False) |
        occs["description"].str.lower().str.contains(pattern, na=False)
    )
    return occs[mask][["code", "title", "description"]].reset_index(drop=True)


def get_related_occupations(code: str, top_n: int = 10) -> pd.DataFrame:
    """
    Return occupations related to the given code using O*NET's official
    Related Occupations file (pre-computed relatedness tiers).
    """
    related = _load_file("related")
    occs = _occupations().rename(columns={"O*NET-SOC Code": "code", "Title": "title"})

    result = _match_code(related, code).head(top_n).copy()
    result = result.rename(columns={"Related O*NET-SOC Code": "related_code", "Relatedness Tier": "relatedness_tier"})
    result = result.merge(occs[["code", "title"]].rename(columns={"code": "related_code"}), on="related_code", how="left")
    return result[["related_code", "title", "relatedness_tier"]].reset_index(drop=True)


def clear_cache() -> None:
    """Delete locally cached O*NET flat files to force re-download."""
    import shutil
    if FLAT_FILE_CACHE.exists():
        shutil.rmtree(FLAT_FILE_CACHE)
