from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WAREHOUSE = Path(os.environ.get("WAREHOUSE_PATH", PROJECT_ROOT / "data" / "warehouse.duckdb"))


def connect(path: str | Path = DEFAULT_WAREHOUSE, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)


def query(con: duckdb.DuckDBPyConnection, sql: str, **params) -> pd.DataFrame:
    return con.execute(sql, params or None).df() if params else con.sql(sql).df()


def write_table(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    """Persist an analysis output back to the warehouse so BI tools / the report can use it."""
    con.register("_tmp_df", df)
    con.execute(f"create or replace table {name} as select * from _tmp_df")
    con.unregister("_tmp_df")
