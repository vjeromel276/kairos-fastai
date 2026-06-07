#!/usr/bin/env python3
"""
scripts/sharadar_data_sync.py
==================
Intelligently sync Sharadar data tables with the API.

v2: Removed intermediate parquet file. DataFrames are passed directly to DuckDB
    via native DataFrame scanning, avoiding the pyarrow LocalFileSystem conflict
    introduced by pyarrow 21+ coexisting with DuckDB.

For each table:
1. Check current max date in local DuckDB
2. Query API to see if newer data exists
3. Download only if new data is available (with pagination)
4. Merge into DuckDB directly from DataFrame

Tables supported:
- SEP: Daily stock prices (date field: date)
- DAILY: Daily fundamental ratios (date field: date)
- SF1: Quarterly fundamentals (date field: lastupdated)
- SF2: Insider transactions (date field: filingdate)
- METRICS: Daily snapshot metrics (date field: lastupdated)
- TICKERS: Ticker metadata (full reload)
- ACTIONS: Corporate actions (date field: date)
- EVENTS: Corporate event filings (date field: date)
- SF3/SF3A/SF3B: Institutional holdings (date field: calendardate)
- SP500: S&P 500 constituent changes (full reload)
- SFP and INDICATORS are checked by default in --check-only and are opt-in for sync.

Usage:
    # Check and sync standard package tables
    python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb
    
    # Check all configured tables, including SFP and INDICATORS, without downloading
    python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --check-only
    
    # Sync specific tables
    python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --tables SEP DAILY
    
    # Force download even if up to date
    python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --force

Environment:
    NASDAQ_DATA_LINK_API_KEY: Your Nasdaq Data Link API key
"""

import argparse
import io
import logging
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import zipfile

import requests
import pandas as pd
import duckdb

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# API configuration
API_KEY_ENV = "NASDAQ_DATA_LINK_API_KEY"
BASE_URL = "https://data.nasdaq.com/api/v3/datatables/SHARADAR"
PAGE_SAFETY_LIMIT = 50
BULK_EXPORT_POLL_SECONDS = 30.0
BULK_EXPORT_MAX_ATTEMPTS = 60
DEFAULT_BULK_DOWNLOAD_DIR = Path("data/downloads/full_refresh")
API_KEY_QUERY_RE = re.compile(r"((?:^|[?&\s])api_key=)[^&\s'\"<>)]+")
API_KEY_DICT_RE = re.compile(r"(['\"]api_key['\"]\s*:\s*['\"])[^'\"]+(['\"])")


def redact_api_key(value: object) -> str:
    """Redact Nasdaq API keys from URL and params-style exception text."""
    text = str(value)
    text = API_KEY_QUERY_RE.sub(r"\1<redacted>", text)
    return API_KEY_DICT_RE.sub(r"\1<redacted>\2", text)

# Table configurations
TABLES: Dict[str, Dict] = {
    "SEP": {
        "db_table": "sep_base",
        "date_field": "date",           # Field to filter API by
        "db_date_field": "date",        # Field in local DB to check max
        "description": "Daily stock prices",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["date"],
    },
    "DAILY": {
        "db_table": "daily",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Daily fundamental ratios (PE, PB, PS, EV/EBITDA)",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["date", "lastupdated"],
    },
    "SF1": {
        "db_table": "sf1",
        "date_field": "lastupdated",    # Filter API by lastupdated.gte
        "db_date_field": "lastupdated", # Check max lastupdated locally
        "description": "Quarterly/Annual fundamentals",
        "reload_mode": "incremental",
        "use_gte": True,
        "date_columns": ["datekey", "reportperiod", "lastupdated"],
    },
    "SF2": {
        "db_table": "sf2",
        "date_field": "filingdate",
        "db_date_field": "filingdate",
        "description": "Insider transactions",
        "reload_mode": "incremental",
        "use_gte": True,
        "date_columns": ["filingdate", "transactiondate"],
    },
    "SFP": {
        "db_table": "sfp",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Sharadar Fund Prices (mutual funds, ETFs)",
        "reload_mode": "incremental",
        "use_gte": False,
        "opt_in_only": True,
        "date_columns": ["date", "lastupdated"],
    },
    "METRICS": {
        "db_table": "sharadar_metrics",
        "date_field": "lastupdated",
        "db_date_field": "lastupdated",
        "description": "Daily snapshot metrics (52w hi/lo, MAs, betas)",
        "reload_mode": "incremental",
        "use_gte": True,
        "date_columns": ["date", "lastupdated"],
    },
    "TICKERS": {
        "db_table": "tickers",
        "date_field": "lastupdated",
        "db_date_field": "lastupdated",
        "description": "Ticker metadata (sector, industry, listings)",
        "reload_mode": "full",
        "date_columns": [
            "lastupdated", "firstadded", "firstpricedate", "lastpricedate",
            "firstquarter", "lastquarter",
        ],
    },
    "ACTIONS": {
        "db_table": "sharadar_actions",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Corporate actions (splits, dividends)",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["date"],
    },
    "EVENTS": {
        "db_table": "sharadar_events",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Corporate event filings",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["date"],
    },
    "SF3": {
        "db_table": "sf3",
        "date_field": "calendardate",
        "db_date_field": "calendardate",
        "description": "Institutional holdings (long form)",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["calendardate"],
    },
    "SF3A": {
        "db_table": "sf3a",
        "date_field": "calendardate",
        "db_date_field": "calendardate",
        "description": "Institutional holdings by ticker",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["calendardate"],
    },
    "SF3B": {
        "db_table": "sf3b",
        "date_field": "calendardate",
        "db_date_field": "calendardate",
        "description": "Institutional holdings by investor",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["calendardate"],
    },
    "SP500": {
        "db_table": "sharadar_sp500",
        "date_field": "date",
        "db_date_field": "date",
        "description": "S&P 500 constituent changes",
        "reload_mode": "full",
        "date_columns": ["date"],
    },
    "INDICATORS": {
        "db_table": "sharadar_indicators",
        "description": "Indicator metadata reference (no date field)",
        "reload_mode": "full",
        "no_date_field": True,
        "opt_in_only": True,
        "date_columns": [],
    },
}

DEFAULT_TABLES = [table for table, cfg in TABLES.items() if not cfg.get("opt_in_only")]


def get_api_key() -> str:
    """Get API key from environment."""
    api_key = os.getenv(API_KEY_ENV)
    if not api_key:
        logger.error(f"Environment variable '{API_KEY_ENV}' not set.")
        sys.exit(1)
    return api_key


def get_local_max_date(conn: duckdb.DuckDBPyConnection, table_config: Dict) -> Optional[date]:
    """Get the maximum date for a table in local DuckDB."""
    db_table = table_config["db_table"]
    date_field = table_config["db_date_field"]
    
    # Check if table exists
    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    if db_table not in tables:
        logger.info(f"  Table '{db_table}' does not exist locally")
        return None
    
    try:
        result = conn.execute(f"SELECT MAX({date_field}) FROM {db_table}").fetchone()
        if result and result[0]:
            max_val = result[0]
            if isinstance(max_val, datetime):
                return max_val.date()
            elif isinstance(max_val, date):
                return max_val
            else:
                return datetime.strptime(str(max_val)[:10], "%Y-%m-%d").date()
        return None
    except Exception as e:
        logger.warning(f"  Error getting max date from {db_table}: {e}")
        return None


def check_api_for_new_data(
    table_name: str, 
    table_config: Dict, 
    local_max: Optional[date],
    api_key: str
) -> Tuple[bool, Optional[date], int]:
    """
    Check if API has data newer than local_max.
    
    Returns: (has_new_data, api_max_date, estimated_rows)
    """
    date_field = table_config["date_field"]
    
    url = f"{BASE_URL}/{table_name}.json"
    params = {
        "qopts.columns": date_field,
        "qopts.per_page": "100",
        "api_key": api_key,
    }
    
    if local_max:
        # use_gte tables intentionally refresh the max-date overlap so
        # same-date corrections are not skipped.
        check_date = (
            local_max
            if table_config.get("use_gte", False)
            else local_max + timedelta(days=1)
        )
        params[f"{date_field}.gte"] = check_date.strftime("%Y-%m-%d")
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        rows = data.get("datatable", {}).get("data", [])
        
        if not rows:
            return False, local_max, 0
        
        # Find max date from returned rows
        api_max = None
        for row in rows:
            if row[0]:
                row_date = datetime.strptime(str(row[0])[:10], "%Y-%m-%d").date()
                if api_max is None or row_date > api_max:
                    api_max = row_date
        
        if api_max is None:
            return False, local_max, 0
        
        if local_max is None:
            return True, api_max, -1
        
        return True, api_max, -1
        
    except Exception as e:
        logger.warning(f"  Error checking API for {table_name}: {redact_api_key(e)}")
        return False, None, 0


def download_new_data_paginated(
    table_name: str,
    table_config: Dict,
    since_date: Optional[date],
    api_key: str,
) -> Optional[pd.DataFrame]:
    """
    Download new data from API with PAGINATION support.
    Returns combined DataFrame, or None if failed.
    """
    date_field = table_config["date_field"]
    use_gte = table_config.get("use_gte", False)
    date_columns = table_config.get("date_columns", [])
    
    base_url = f"{BASE_URL}/{table_name}.csv"
    base_params = {"api_key": api_key, "qopts.per_page": "10000"}
    
    if since_date:
        if use_gte:
            base_params[f"{date_field}.gte"] = since_date.strftime("%Y-%m-%d")
        else:
            next_date = since_date + timedelta(days=1)
            base_params[f"{date_field}.gte"] = next_date.strftime("%Y-%m-%d")
    
    logger.info(f"  Downloading {table_name} data (with pagination)...")
    
    all_dfs = []
    cursor_id = None
    page = 1
    total_rows = 0
    
    try:
        while True:
            params = base_params.copy()
            if cursor_id:
                params["qopts.cursor_id"] = cursor_id
            
            # Download this page
            resp = requests.get(base_url, params=params, timeout=120)
            resp.raise_for_status()
            
            # Check content type - CSV or JSON error?
            content_type = resp.headers.get('content-type', '')
            
            if 'application/json' in content_type:
                # Might be an error or empty response
                try:
                    json_data = resp.json()
                    if 'datatable' in json_data:
                        # Empty result
                        if not json_data['datatable'].get('data'):
                            break
                except:
                    pass
            
            # Parse CSV
            csv_content = resp.text
            if not csv_content.strip() or csv_content.strip() == '':
                break
            
            # Read CSV from string
            df_page = pd.read_csv(io.StringIO(csv_content), parse_dates=date_columns, low_memory=False)
            
            if df_page.empty:
                break
            
            rows_this_page = len(df_page)
            total_rows += rows_this_page
            all_dfs.append(df_page)
            
            logger.info(f"    Page {page}: {rows_this_page:,} rows (total: {total_rows:,})")
            
            # Check for next cursor
            # For CSV endpoint, we need to use JSON to get cursor_id
            if rows_this_page < 10000:
                # Less than full page = no more data
                break
            
            # Switch to JSON to get cursor_id
            json_url = f"{BASE_URL}/{table_name}.json"
            json_resp = requests.get(json_url, params=params, timeout=60)
            json_resp.raise_for_status()
            json_data = json_resp.json()
            
            cursor_id = json_data.get('meta', {}).get('next_cursor_id')
            
            if not cursor_id:
                break
            
            if page >= PAGE_SAFETY_LIMIT:
                raise RuntimeError(
                    f"Pagination safety limit reached for {table_name}: "
                    f"{PAGE_SAFETY_LIMIT} pages downloaded and API still returned next_cursor_id"
                )
            
            page += 1
        
        if not all_dfs:
            logger.warning(f"  No data downloaded")
            return None
        
        # Combine all pages
        df = pd.concat(all_dfs, ignore_index=True)
        logger.info(f"  Total downloaded: {len(df):,} rows across {page} page(s)")
        
        return df
        
    except Exception as e:
        logger.error(f"  Download failed: {redact_api_key(e)}")
        return None


def merge_df_to_db(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    table_config: Dict
) -> int:
    """Merge downloaded DataFrame into DuckDB table. Returns net rows added."""
    db_table = table_config["db_table"]
    date_field = table_config["db_date_field"]
    use_gte = table_config.get("use_gte", False)
    
    # Check if table exists
    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    
    if db_table not in tables:
        # Create table from DataFrame
        logger.info(f"  Creating table '{db_table}'...")
        conn.execute(f"""
            CREATE TABLE {db_table} AS
            SELECT * FROM df
        """)
        count = conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]
        return count
    
    # Get current max date
    local_max = get_local_max_date(conn, table_config)
    
    # Insert only new rows
    before_count = conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]
    
    if local_max and use_gte:
        overlap_start = local_max.isoformat()
        logger.info(f"  Refreshing overlap window from {overlap_start}")
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(f"""
                DELETE FROM {db_table}
                WHERE {date_field} >= DATE '{overlap_start}'
            """)
            conn.execute(f"""
                INSERT INTO {db_table}
                SELECT DISTINCT * FROM df
                WHERE {date_field} >= DATE '{overlap_start}'
            """)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    else:
        if local_max:
            filter_clause = f"WHERE {date_field} > DATE '{local_max.isoformat()}'"
        else:
            filter_clause = ""

        conn.execute(f"""
            INSERT INTO {db_table}
            SELECT DISTINCT * FROM df
            {filter_clause}
        """)
    
    after_count = conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]
    inserted = after_count - before_count
    
    return inserted


def sql_literal(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def write_response_to_file(resp, output_path: Path) -> None:
    with output_path.open("wb") as f:
        if hasattr(resp, "iter_content"):
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        else:
            f.write(resp.content)


def download_bulk_export_zip(
    table_name: str,
    api_key: str,
    download_root: Path,
    poll_seconds: float = BULK_EXPORT_POLL_SECONDS,
    max_attempts: int = BULK_EXPORT_MAX_ATTEMPTS,
) -> Path:
    """Request Nasdaq bulk export and download the fresh zipped CSV file."""
    run_id = f"{datetime.utcnow():%Y%m%dT%H%M%SZ}_{table_name.lower()}_{uuid.uuid4().hex[:8]}"
    run_dir = download_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    export_url = f"{BASE_URL}/{table_name}.json"
    export_params = {"api_key": api_key, "qopts.export": "true"}
    zip_path = run_dir / f"{table_name.lower()}_bulk.zip"

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(export_url, params=export_params, timeout=60)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            raise RuntimeError(
                f"Bulk export status request failed for {table_name}: {redact_api_key(e)}"
            ) from e

        bulk = payload.get("datatable_bulk_download", {})
        file_info = bulk.get("file", {}) or {}
        status = str(file_info.get("status") or "").lower()
        link = file_info.get("link")
        logger.info(f"  Bulk export status for {table_name}: {status or 'unknown'}")

        if status == "fresh" and link:
            try:
                download_resp = requests.get(link, timeout=600, stream=True)
                download_resp.raise_for_status()
                write_response_to_file(download_resp, zip_path)
            except Exception as e:
                raise RuntimeError(
                    f"Bulk export download failed for {table_name}: {redact_api_key(e)}"
                ) from e

            if zip_path.stat().st_size == 0:
                raise RuntimeError(f"Bulk export download for {table_name} produced an empty file")
            logger.info(f"  Downloaded bulk export to {zip_path}")
            return zip_path

        if attempt < max_attempts:
            time.sleep(poll_seconds)

    raise RuntimeError(
        f"Bulk export for {table_name} was not fresh after {max_attempts} attempt(s)"
    )


def extract_bulk_csv(zip_path: Path) -> Path:
    """Extract the single CSV from a Nasdaq bulk export zip."""
    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError(f"Bulk export file is not a zip archive: {zip_path}")

    extract_dir = zip_path.parent / "extracted"
    extract_dir.mkdir(exist_ok=False)

    with zipfile.ZipFile(zip_path) as zf:
        csv_members = [
            member
            for member in zf.namelist()
            if not member.endswith("/") and member.lower().endswith(".csv")
        ]
        if len(csv_members) != 1:
            raise RuntimeError(
                f"Expected exactly one CSV in {zip_path}, found {len(csv_members)}"
            )
        csv_path = extract_dir / Path(csv_members[0]).name
        with zf.open(csv_members[0]) as src, csv_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)

    if not csv_path.exists():
        raise RuntimeError(f"Bulk export CSV was not extracted: {csv_path}")
    return csv_path


def replace_full_from_staging_table(
    conn: duckdb.DuckDBPyConnection,
    staging_table: str,
    table_config: Dict,
) -> Tuple[int, int]:
    """Atomically replace a full-reload table from a validated staging table."""
    db_table = table_config["db_table"]
    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    before = (
        conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]
        if db_table in tables else 0
    )
    after = conn.execute(f"SELECT COUNT(*) FROM {staging_table}").fetchone()[0]
    staging_columns = [
        column[0]
        for column in conn.execute(f"SELECT * FROM {staging_table} LIMIT 0").description
    ]
    if not staging_columns:
        raise RuntimeError(f"Bulk replacement for {db_table} produced no columns")

    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {db_table}")
        conn.execute(f"CREATE TABLE {db_table} AS SELECT * FROM {staging_table}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return before, after


def replace_full_from_csv(
    conn: duckdb.DuckDBPyConnection,
    csv_path: Path,
    table_config: Dict,
) -> Tuple[int, int]:
    """Load a bulk-export CSV into staging, then atomically replace the table."""
    db_table = table_config["db_table"]
    temp_table = f"tmp_{db_table}_bulk_{uuid.uuid4().hex}"
    temp_created = False
    try:
        conn.execute(f"""
            CREATE TEMP TABLE {temp_table} AS
            SELECT * FROM read_csv_auto({sql_literal(csv_path)}, header = true)
        """)
        temp_created = True
        return replace_full_from_staging_table(conn, temp_table, table_config)
    finally:
        if temp_created:
            conn.execute(f"DROP TABLE IF EXISTS {temp_table}")


def replace_full_from_bulk_export(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    table_config: Dict,
    api_key: str,
    download_root: Path,
    keep_downloads: bool = False,
    poll_seconds: float = BULK_EXPORT_POLL_SECONDS,
    max_attempts: int = BULK_EXPORT_MAX_ATTEMPTS,
) -> Tuple[int, int]:
    """
    Download a full table via Nasdaq bulk export, ingest from local CSV, and clean up.

    Downloads are deleted only after successful ingestion. Failed runs leave files in
    place so they can be inspected or ingested manually without another export request.
    """
    zip_path = download_bulk_export_zip(
        table_name,
        api_key,
        download_root,
        poll_seconds=poll_seconds,
        max_attempts=max_attempts,
    )
    run_dir = zip_path.parent
    success = False
    try:
        csv_path = extract_bulk_csv(zip_path)
        before, after = replace_full_from_csv(conn, csv_path, table_config)
        success = True
        return before, after
    finally:
        if success and not keep_downloads:
            shutil.rmtree(run_dir, ignore_errors=True)


def refresh_trading_calendar(
    conn: duckdb.DuckDBPyConnection,
    source_table: str = "sep_base",
    calendar_table: str = "trading_calendar",
    check_only: bool = False,
) -> Dict:
    """Refresh trading_calendar from distinct SEP source dates."""
    result = {
        "table": calendar_table,
        "source_table": source_table,
        "rows_before": 0,
        "rows_after": 0,
        "old_max": None,
        "new_max": None,
        "status": "unknown",
    }

    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    if source_table not in tables:
        logger.warning(f"Trading calendar source table '{source_table}' does not exist")
        result["status"] = "missing_source"
        return result

    if calendar_table in tables:
        before = conn.execute(
            f"SELECT COUNT(*), MAX(trading_date) FROM {calendar_table}"
        ).fetchone()
        result["rows_before"] = before[0]
        result["old_max"] = before[1]

    after_preview = conn.execute(
        f"SELECT COUNT(DISTINCT date), MAX(date) FROM {source_table}"
    ).fetchone()
    result["rows_after"] = after_preview[0]
    result["new_max"] = after_preview[1]

    needs_update = (
        result["rows_before"] != result["rows_after"]
        or result["old_max"] != result["new_max"]
    )

    logger.info(f"\n{'='*60}")
    logger.info("TRADING CALENDAR")
    logger.info(f"{'='*60}")
    logger.info(
        f"  Source {source_table}: {result['rows_after']:,} dates "
        f"(max {result['new_max']})"
    )

    if check_only:
        result["status"] = "needs_update" if needs_update else "up_to_date"
        logger.info(f"  (check-only mode, status: {result['status']})")
        return result

    if not needs_update:
        result["status"] = "up_to_date"
        logger.info(f"  Already up to date")
        return result

    conn.execute(f"""
        CREATE OR REPLACE TABLE {calendar_table} AS
        SELECT DISTINCT CAST(date AS DATE) AS trading_date
        FROM {source_table}
        WHERE date IS NOT NULL
        ORDER BY trading_date
    """)
    result["status"] = "updated"
    logger.info(
        f"  Updated {calendar_table}: {result['rows_before']:,} -> "
        f"{result['rows_after']:,} rows, max {result['old_max']} -> {result['new_max']}"
    )
    return result


def sync_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    table_config: Dict,
    api_key: str,
    check_only: bool = False,
    force: bool = False,
    download_root: Path = DEFAULT_BULK_DOWNLOAD_DIR,
    keep_downloads: bool = False,
    bulk_poll_seconds: float = BULK_EXPORT_POLL_SECONDS,
    bulk_max_attempts: int = BULK_EXPORT_MAX_ATTEMPTS,
) -> Dict:
    """
    Sync a single table. Returns status dict.
    """
    mode = table_config.get("reload_mode", "incremental")
    result = {
        "table": table_name,
        "db_table": table_config["db_table"],
        "mode": mode,
        "local_max": None,
        "api_max": None,
        "has_new_data": False,
        "rows_before": None,
        "rows_after": None,
        "rows_added": 0,
        "status": "unknown",
    }
    
    logger.info(f"\n{'='*50}")
    logger.info(f"{table_name} [{mode}]: {table_config['description']}")
    logger.info(f"{'='*50}")
    
    if mode == "full":
        if table_config.get("no_date_field", False):
            local_max = None
            logger.info("  No date field; will full-reload when selected")
        else:
            local_max = get_local_max_date(conn, table_config)
            logger.info(f"  Local max date: {local_max or 'No data'}")
        result["local_max"] = local_max
        result["has_new_data"] = True
        logger.info("  Full-reload table; skipping incremental staleness check")

        if force:
            logger.info("  Force download requested")
        else:
            logger.info("  Full reload scheduled")

        if check_only:
            logger.info("  (check-only mode, skipping download)")
            result["status"] = "needs_update"
            return result

        try:
            before, after = replace_full_from_bulk_export(
                conn,
                table_name,
                table_config,
                api_key,
                download_root,
                keep_downloads=keep_downloads,
                poll_seconds=bulk_poll_seconds,
                max_attempts=bulk_max_attempts,
            )
        except Exception as e:
            logger.error(f"  Bulk full reload failed: {redact_api_key(e)}")
            result["status"] = "download_failed"
            return result

        result["rows_before"] = before
        result["rows_after"] = after
        result["rows_added"] = after - before
        logger.info(f"  ✓ Replaced table: {before:,} -> {after:,} rows ({after - before:+,})")
        result["status"] = "updated"
        return result

    local_max = get_local_max_date(conn, table_config)
    result["local_max"] = local_max
    logger.info(f"  Local max date: {local_max or 'No data'}")

    has_new, api_max, est_rows = check_api_for_new_data(
        table_name,
        table_config,
        local_max,
        api_key,
    )
    result["api_max"] = api_max
    result["has_new_data"] = has_new

    if api_max:
        logger.info(f"  API max date: {api_max}")
    
    if not has_new and not force:
        if local_max and api_max and local_max >= api_max:
            logger.info(f"  ✓ Already up to date")
            result["status"] = "up_to_date"
        elif not api_max:
            logger.info(f"  ⚠ Could not determine API status")
            result["status"] = "check_failed"
        else:
            logger.info(f"  ✓ No new data available")
            result["status"] = "up_to_date"
        return result
    
    if force:
        logger.info(f"  Force download requested")
    else:
        logger.info(f"  New data available!")
    
    if check_only:
        logger.info(f"  (check-only mode, skipping download)")
        result["status"] = "needs_update"
        return result
    
    # Download new data WITH PAGINATION
    df = download_new_data_paginated(
        table_name, table_config, local_max, api_key
    )
    
    if df is None:
        result["status"] = "download_failed"
        return result
    
    # Merge DataFrame directly to database
    rows_added = merge_df_to_db(conn, df, table_config)
    result["rows_added"] = rows_added
    
    # Get new max date
    new_max = get_local_max_date(conn, table_config)
    result["local_max"] = new_max
    
    logger.info(f"  ✓ Added {rows_added:,} rows, new max date: {new_max}")
    result["status"] = "updated"
    
    return result


def print_summary(results: List[Dict]):
    """Print summary of sync results."""
    logger.info(f"\n{'='*60}")
    logger.info("SYNC SUMMARY")
    logger.info(f"{'='*60}")
    
    for r in results:
        status_icon = {
            "up_to_date": "✓",
            "updated": "✓",
            "needs_update": "⚠",
            "download_failed": "✗",
            "check_failed": "?",
        }.get(r["status"], "?")
        
        local_str = str(r['local_max']) if r['local_max'] else 'None'
        
        logger.info(f"{status_icon} {r['table']:8} [{r['mode']:11}] ({r['db_table']:17}) | "
                   f"Local: {local_str:12} | "
                   f"Status: {r['status']}")
        
        if r["mode"] == "full" and r["rows_before"] is not None:
            logger.info(
                f"  └─ rows: {r['rows_before']:,} -> {r['rows_after']:,} "
                f"({r['rows_added']:+,})"
            )
        elif r["rows_added"] > 0:
            logger.info(f"  └─ Added {r['rows_added']:,} rows")
    
    logger.info(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Smart Sharadar data sync v2 (in-memory DataFrame merge)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check standard package tables for new data and sync
  python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb
  
  # Check only (show what would be updated, including opt-in tables)
  python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --check-only
  
  # Sync only SEP and DAILY
  python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --tables SEP DAILY
  
  # Force re-download even if up to date
  python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --tables SF1 --force
"""
    )
    
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=list(TABLES.keys()),
        default=None,
        help=(
            f"Tables to sync (sync default: {', '.join(DEFAULT_TABLES)}; "
            f"check-only default: {', '.join(TABLES.keys())})"
        )
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check for new data, don't download"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force download even if local data appears up to date"
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=DEFAULT_BULK_DOWNLOAD_DIR,
        help="Directory for temporary full-reload bulk export downloads",
    )
    parser.add_argument(
        "--keep-downloads",
        action="store_true",
        help="Keep full-reload bulk export files after successful ingestion",
    )
    parser.add_argument(
        "--bulk-poll-seconds",
        type=float,
        default=BULK_EXPORT_POLL_SECONDS,
        help="Seconds to wait between bulk export status checks",
    )
    parser.add_argument(
        "--bulk-max-attempts",
        type=int,
        default=BULK_EXPORT_MAX_ATTEMPTS,
        help="Maximum bulk export status checks before failing",
    )
    
    args = parser.parse_args()
    selected_tables = (
        args.tables
        if args.tables is not None
        else list(TABLES.keys()) if args.check_only else DEFAULT_TABLES
    )
    
    # Get API key
    api_key = get_api_key()
    
    # Connect to database
    logger.info(f"\n{'='*60}")
    logger.info("SHARADAR DATA SYNC v2 (in-memory DataFrame merge)")
    logger.info(f"{'='*60}")
    logger.info(f"Database: {args.db}")
    logger.info(f"Tables: {', '.join(selected_tables)}")
    logger.info(f"Mode: {'Check only' if args.check_only else 'Sync'}")
    
    conn = duckdb.connect(args.db)
    
    # Sync each table
    results = []
    for table_name in selected_tables:
        table_config = TABLES[table_name]
        result = sync_table(
            conn=conn,
            table_name=table_name,
            table_config=table_config,
            api_key=api_key,
            check_only=args.check_only,
            force=args.force,
            download_root=args.download_dir,
            keep_downloads=args.keep_downloads,
            bulk_poll_seconds=args.bulk_poll_seconds,
            bulk_max_attempts=args.bulk_max_attempts,
        )
        results.append(result)

    calendar_result = None
    if "SEP" in selected_tables:
        sep_result = next((r for r in results if r["table"] == "SEP"), None)
        if sep_result and sep_result["status"] not in ("download_failed", "check_failed"):
            calendar_result = refresh_trading_calendar(conn, check_only=args.check_only)
        else:
            logger.warning("Skipping trading_calendar refresh because SEP did not sync cleanly")
    
    conn.close()
    
    # Print summary
    print_summary(results)
    if calendar_result:
        logger.info(
            "Calendar: %s | rows %s -> %s | max %s -> %s",
            calendar_result["status"],
            calendar_result["rows_before"],
            calendar_result["rows_after"],
            calendar_result["old_max"],
            calendar_result["new_max"],
        )
    
    # Exit with error if any syncs failed
    failed = any(r["status"] in ("download_failed", "check_failed") for r in results)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
