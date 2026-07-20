"""
Unified client — routes requests to the right connector based on source metadata.
"""

from typing import Optional
import pandas as pd

from . import catalog as cat
from . import cache


def get(
    source_id: str,
    use_cache: bool = True,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch data from a source by its catalog ID.

    Args:
        source_id: catalog source ID (e.g. 'bls_jolts', 'fred_main', 'dol_onet')
        use_cache: whether to use the local cache (default True)
        **kwargs: passed through to the underlying connector

    Returns:
        DataFrame with the requested data.
    """
    source = cat.get_source(source_id)
    if not source:
        raise ValueError(f"Unknown source '{source_id}'. Use catalog.search() to find valid IDs.")

    connector = source.get("connector")

    if use_cache:
        cached = cache.get(source_id, kwargs)
        if cached is not None:
            return cached

    df = _dispatch(source, connector, kwargs)

    if use_cache and df is not None and not df.empty:
        cache.put(source_id, kwargs, df, frequency=source.get("frequency", "default"))

    return df if df is not None else pd.DataFrame()


def describe(source_id: str) -> dict:
    """Return full metadata for a source."""
    source = cat.get_source(source_id)
    if not source:
        raise ValueError(f"Unknown source '{source_id}'.")
    return {k: v for k, v in source.items() if not k.startswith("_")}


def _dispatch(source: dict, connector: str, kwargs: dict) -> Optional[pd.DataFrame]:
    source_id = source["id"]

    if connector == "fred":
        from .sources import fred
        series_id = source.get("fred_series")
        if series_id:
            return fred.get_series(
                series_id,
                start_date=kwargs.get("start_date"),
                end_date=kwargs.get("end_date"),
            )
        elif source_id == "fred_main":
            # Generic FRED query
            topic = kwargs.get("topic", "")
            sid = kwargs.get("series_id", "")
            if sid:
                return fred.get_series(sid, start_date=kwargs.get("start_date"), end_date=kwargs.get("end_date"))
            elif topic:
                df, _ = fred.get_by_topic(topic, start_date=kwargs.get("start_date"), end_date=kwargs.get("end_date"))
                return df
        return pd.DataFrame()

    elif connector == "bls":
        from .sources import bls
        series_ids = kwargs.get("series_ids", [])
        if not series_ids:
            prefix = source.get("series_prefix", "")
            popular_key = kwargs.get("series_name", "")
            if popular_key:
                return bls.get_popular(popular_key, start_year=kwargs.get("start_year"), end_year=kwargs.get("end_year"))
            return pd.DataFrame()
        return bls.get_series(
            series_ids,
            start_year=kwargs.get("start_year"),
            end_year=kwargs.get("end_year"),
        )

    elif connector == "census":
        from .sources import census
        dataset = source.get("dataset", "")
        if dataset == "acs/acs1" or dataset == "acs/acs5":
            variables = kwargs.get("variables", list(census.ACS_VARIABLES.keys())[:5])
            return census.get_acs(
                variables=variables,
                year=kwargs.get("year", 2022),
                geography=kwargs.get("geography", "state"),
                dataset=dataset,
            )
        elif "qwi" in dataset:
            indicators = kwargs.get("indicators", ["employment", "hires_all", "separations"])
            return census.get_qwi(
                indicators=indicators,
                state_fips=kwargs.get("state_fips", "*"),
                year_start=kwargs.get("year_start", 2018),
                year_end=kwargs.get("year_end", 2023),
            )
        elif dataset == "cbp":
            return census.get_cbp(
                year=kwargs.get("year", 2021),
                geography=kwargs.get("geography", "state"),
                naics_code=kwargs.get("naics_code", ""),
            )
        elif dataset == "abscs":
            return census.get_acs(
                variables=["employed", "median_household_income"],
                year=kwargs.get("year", 2021),
                geography=kwargs.get("geography", "state"),
                dataset="abscb",
            )
        return pd.DataFrame()

    elif connector == "onet":
        from .sources import onet
        code = kwargs.get("code", "")
        data_type = kwargs.get("data_type", "skills")
        if not code:
            query = kwargs.get("query", "")
            if query:
                return onet.search_occupations(query)
            return pd.DataFrame()
        if data_type == "skills":
            return onet.get_skills(code)
        elif data_type == "tasks":
            return onet.get_tasks(code)
        elif data_type == "abilities":
            return onet.get_abilities(code)
        elif data_type == "knowledge":
            return onet.get_knowledge(code)
        elif data_type == "work_activities":
            return onet.get_work_activities(code)
        elif data_type == "technology":
            return onet.get_technology(code)
        return onet.get_skills(code)

    elif connector == "dol":
        from .sources import dol
        if source_id == "dol_osha":
            return dol.get_osha_inspections(
                state=kwargs.get("state"),
                start_date=kwargs.get("start_date"),
                end_date=kwargs.get("end_date"),
                limit=kwargs.get("limit", 500),
            )
        elif source_id == "dol_whd":
            return dol.get_whd_enforcement(
                state=kwargs.get("state"),
                limit=kwargs.get("limit", 500),
            )
        elif source_id == "dol_flc":
            return dol.get_h1b_disclosures(
                year=kwargs.get("year", 2024),
                limit=kwargs.get("limit", 1000),
            )
        elif source_id == "dol_ui":
            return dol.get_bls_ui_claims(weeks=kwargs.get("weeks", 52))
        return pd.DataFrame()

    elif connector == "sec":
        from .sources import sec
        if source_id == "sec_edgar":
            action = kwargs.get("action", "human_capital")
            if action == "human_capital":
                return sec.get_human_capital_filings(
                    date_range_start=kwargs.get("start_date", "2021-01-01"),
                    date_range_end=kwargs.get("end_date"),
                    limit=kwargs.get("limit", 50),
                )
            elif action == "layoffs":
                return sec.search_layoff_8k(
                    date_range_start=kwargs.get("start_date"),
                    date_range_end=kwargs.get("end_date"),
                    limit=kwargs.get("limit", 50),
                )
            elif action == "company":
                company = kwargs.get("company", "")
                return sec.search_company_filings(company, limit=kwargs.get("limit", 10))
        return pd.DataFrame()

    elif connector == "external":
        return pd.DataFrame({"message": [
            f"'{source['name']}' requires manual download or registration. "
            f"Visit: {source.get('url', '')}",
            source.get("notes", ""),
        ]})

    return pd.DataFrame()
