"""Safe SQL execution plus a fixed menu of statistical analyses.

The assistant is never allowed to run arbitrary Python. It gets a read-only SQL
tool and these named analyses, which is enough for descriptive stats,
segmentation, correlation, outlier hunting, trends and naive forecasting.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal

import numpy as np

from . import db
from .config import SQL_ROW_LIMIT

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|vacuum|"
    r"analyze|reindex|cluster|call|do|begin|commit|rollback|set|reset|listen|notify|"
    r"security|refresh|import|prepare|execute|discard)\b", re.I)
DANGEROUS = re.compile(r"(pg_read_file|pg_write|lo_import|lo_export|dblink|pg_sleep|"
                       r"pg_ls_dir|pg_stat_file|copy\s*\()", re.I)


class SQLError(ValueError):
    pass


def guard(sql: str) -> str:
    """Reject anything that is not a single read-only SELECT, and cap the rows."""
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise SQLError("Empty query.")
    if ";" in s:
        raise SQLError("Only one statement is allowed per query.")
    if not re.match(r"^(with|select)\b", s, re.I):
        raise SQLError("Only SELECT (or WITH ... SELECT) queries are allowed.")
    # ignore string literals and quoted identifiers so a column named "update"
    # cannot trip the keyword scan
    stripped = re.sub(r'"[^"]*"', '""', re.sub(r"'[^']*'", "''", s))
    if FORBIDDEN.search(stripped):
        raise SQLError("Only read-only SELECT queries are allowed.")
    if DANGEROUS.search(stripped):
        raise SQLError("That function is not permitted.")
    if not re.search(r"\blimit\s+\d+\s*$", s, re.I):
        s = f"{s} LIMIT {SQL_ROW_LIMIT}"
    return s


def clean(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "<binary>"
    return v


def run_sql(sql: str) -> dict:
    safe = guard(sql)
    cols, rows = db.read_only(safe)
    return {"sql": safe, "columns": cols,
            "rows": [[clean(v) for v in r] for r in rows], "row_count": len(rows)}


# ------------------------------------------------------------- analytics ---

def _cols(dataset_id: str) -> dict[str, dict]:
    return {r["name"]: r for r in db.query(
        "SELECT name, semantic_type, pg_type FROM core.dataset_columns "
        "WHERE dataset_id=%s ORDER BY position", (dataset_id,))}


def _table(dataset_id: str) -> str:
    row = db.one("SELECT table_name FROM core.datasets WHERE id=%s", (dataset_id,))
    if not row:
        raise SQLError("Unknown dataset.")
    return row["table_name"]


def _check(cols: dict, wanted: list[str], kinds: tuple[str, ...] | None = None) -> list[str]:
    out = []
    for c in wanted:
        if c not in cols:
            raise SQLError(f'Column "{c}" does not exist. Available: {", ".join(cols)}')
        if kinds and cols[c]["semantic_type"] not in kinds:
            raise SQLError(f'Column "{c}" is {cols[c]["semantic_type"]}, needs one of {kinds}.')
        out.append(c)
    return out


def describe(dataset_id: str, columns: list[str] | None = None) -> dict:
    cols = _cols(dataset_id)
    tbl = _table(dataset_id)
    nums = [c for c in (columns or cols) if cols.get(c, {}).get("semantic_type") in ("integer", "numeric")]
    if not nums:
        nums = [c for c, m in cols.items() if m["semantic_type"] in ("integer", "numeric")]
    if not nums:
        return {"note": "This dataset has no numeric columns to describe.", "rows": []}
    out = []
    for c in nums:
        r = db.query(f'''SELECT count("{c}") AS n, avg("{c}") AS mean,
                                stddev_samp("{c}") AS std, min("{c}") AS min, max("{c}") AS max,
                                percentile_cont(0.25) WITHIN GROUP (ORDER BY "{c}") AS p25,
                                percentile_cont(0.50) WITHIN GROUP (ORDER BY "{c}") AS median,
                                percentile_cont(0.75) WITHIN GROUP (ORDER BY "{c}") AS p75,
                                sum("{c}") AS sum
                         FROM data."{tbl}"''')[0]
        out.append({"column": c, **{k: clean(v) for k, v in r.items()}})
    return {"columns": ["column", "n", "mean", "std", "min", "max", "p25", "median", "p75", "sum"],
            "rows": [[o.get(k) for k in ["column", "n", "mean", "std", "min", "max", "p25", "median", "p75", "sum"]]
                     for o in out]}


def correlation(dataset_id: str, columns: list[str] | None = None) -> dict:
    cols = _cols(dataset_id)
    tbl = _table(dataset_id)
    nums = [c for c in (columns or cols) if cols.get(c, {}).get("semantic_type") in ("integer", "numeric")]
    nums = nums[:12]
    if len(nums) < 2:
        return {"note": "At least two numeric columns are needed for a correlation matrix.", "rows": []}
    sel = ", ".join(f'corr("{a}","{b}") AS "{a}__{b}"' for a in nums for b in nums if a != b)
    row = db.query(f'SELECT {sel} FROM data."{tbl}"')[0]
    matrix = [[1.0 if a == b else clean(row.get(f"{a}__{b}")) for b in nums] for a in nums]
    pairs = sorted(
        ({"a": a, "b": b, "r": clean(row.get(f"{a}__{b}"))}
         for i, a in enumerate(nums) for b in nums[i + 1:] if row.get(f"{a}__{b}") is not None),
        key=lambda p: -abs(p["r"]))
    return {"variables": nums, "matrix": matrix, "strongest": pairs[:8]}


def outliers(dataset_id: str, column: str, method: str = "iqr", limit: int = 25) -> dict:
    cols = _cols(dataset_id)
    tbl = _table(dataset_id)
    _check(cols, [column], ("integer", "numeric"))
    if method == "zscore":
        s = db.query(f'SELECT avg("{column}") AS m, stddev_samp("{column}") AS sd FROM data."{tbl}"')[0]
        if not s["sd"]:
            return {"note": "No variation in this column.", "rows": []}
        lo, hi = float(s["m"]) - 3 * float(s["sd"]), float(s["m"]) + 3 * float(s["sd"])
        rule = "mean ± 3 standard deviations"
    else:
        s = db.query(f'''SELECT percentile_cont(0.25) WITHIN GROUP (ORDER BY "{column}") AS q1,
                                percentile_cont(0.75) WITHIN GROUP (ORDER BY "{column}") AS q3
                         FROM data."{tbl}"''')[0]
        q1, q3 = float(s["q1"] or 0), float(s["q3"] or 0)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        rule = "Tukey IQR fence (Q1 - 1.5·IQR, Q3 + 1.5·IQR)"
    n = db.query(f'SELECT count(*) AS n FROM data."{tbl}" WHERE "{column}" < %s OR "{column}" > %s',
                 (lo, hi))[0]["n"]
    rows = db.query(f'''SELECT "_row_id", "{column}" FROM data."{tbl}"
                        WHERE "{column}" < %s OR "{column}" > %s
                        ORDER BY abs("{column}" - %s) DESC LIMIT {int(limit)}''',
                    (lo, hi, (lo + hi) / 2))
    return {"method": rule, "lower_bound": lo, "upper_bound": hi, "outlier_count": int(n),
            "columns": ["_row_id", column],
            "rows": [[clean(r["_row_id"]), clean(r[column])] for r in rows]}


def distribution(dataset_id: str, column: str, bins: int = 12) -> dict:
    cols = _cols(dataset_id)
    tbl = _table(dataset_id)
    _check(cols, [column])
    sem = cols[column]["semantic_type"]
    if sem in ("integer", "numeric"):
        b = db.query(f'SELECT min("{column}") AS mn, max("{column}") AS mx FROM data."{tbl}"')[0]
        mn, mx = float(b["mn"] or 0), float(b["mx"] or 0)
        if mn == mx:
            mx = mn + 1
        rows = db.query(f'''SELECT width_bucket("{column}", %s, %s, %s) AS b, count(*) AS n
                            FROM data."{tbl}" WHERE "{column}" IS NOT NULL GROUP BY 1 ORDER BY 1''',
                        (mn, mx, int(bins)))
        step = (mx - mn) / max(1, bins)
        return {"columns": ["bucket", "count"],
                "rows": [[f"{mn + (int(r['b']) - 1) * step:,.4g} – {mn + int(r['b']) * step:,.4g}",
                          int(r["n"])] for r in rows]}
    rows = db.query(f'''SELECT "{column}"::text AS v, count(*) AS n FROM data."{tbl}"
                        GROUP BY 1 ORDER BY n DESC LIMIT 30''')
    return {"columns": [column, "count"], "rows": [[r["v"], int(r["n"])] for r in rows]}


AGGS = {"sum": "sum", "avg": "avg", "count": "count", "min": "min", "max": "max"}


def group_summary(dataset_id: str, dimension: str, measure: str | None = None,
                  agg: str = "sum", top: int = 20) -> dict:
    cols = _cols(dataset_id)
    tbl = _table(dataset_id)
    _check(cols, [dimension])
    fn = AGGS.get(agg, "sum")
    if measure and measure in cols and cols[measure]["semantic_type"] in ("integer", "numeric"):
        expr, label = f'{fn}("{measure}")', f"{fn}_{measure}"
    else:
        expr, label = "count(*)", "count"
    rows = db.query(f'''SELECT "{dimension}"::text AS k, {expr} AS v, count(*) AS n
                        FROM data."{tbl}" GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT {int(top)}''')
    return {"columns": [dimension, label, "row_count"],
            "rows": [[r["k"], clean(r["v"]), int(r["n"])] for r in rows]}


def trend(dataset_id: str, date_column: str, value_column: str | None = None,
          agg: str = "sum", granularity: str = "month", forecast: int = 0) -> dict:
    cols = _cols(dataset_id)
    tbl = _table(dataset_id)
    _check(cols, [date_column], ("datetime",))
    gran = granularity if granularity in ("day", "week", "month", "quarter", "year") else "month"
    fn = AGGS.get(agg, "sum")
    expr = f'{fn}("{value_column}")' if value_column and value_column in cols else "count(*)"
    rows = db.query(f'''SELECT date_trunc('{gran}', "{date_column}")::date AS p, {expr} AS v
                        FROM data."{tbl}" WHERE "{date_column}" IS NOT NULL
                        GROUP BY 1 ORDER BY 1''')
    series = [[str(r["p"]), clean(r["v"])] for r in rows]
    out = {"columns": ["period", agg if value_column else "count"], "rows": series,
           "granularity": gran}
    ys = [float(v) for _, v in series if v is not None]
    if len(ys) >= 3:
        xs = np.arange(len(ys), dtype=float)
        slope, intercept = np.polyfit(xs, np.array(ys), 1)
        first, last = ys[0], ys[-1]
        out["trend"] = {
            "slope_per_period": float(slope),
            "direction": "rising" if slope > 0 else "falling" if slope < 0 else "flat",
            "change_pct": round(100 * (last - first) / abs(first), 2) if first else None,
            "r": float(np.corrcoef(xs, ys)[0, 1]) if np.std(ys) else 0.0,
        }
        if forecast:
            step = {"day": 1, "week": 7, "month": 30, "quarter": 91, "year": 365}[gran]
            last_p = np.datetime64(series[-1][0])
            out["forecast"] = [
                [str(last_p + np.timedelta64(step * (i + 1), "D")),
                 float(intercept + slope * (len(ys) + i))]
                for i in range(int(forecast))]
    return out


def preview(dataset_id: str, limit: int = 50, offset: int = 0) -> dict:
    tbl = _table(dataset_id)
    cols, rows = db.read_only(
        f'SELECT * FROM data."{tbl}" ORDER BY "_row_id" LIMIT {int(limit)} OFFSET {int(offset)}')
    return {"columns": cols, "rows": [[clean(v) for v in r] for r in rows]}
