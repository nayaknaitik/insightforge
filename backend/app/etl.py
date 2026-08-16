"""ETL: parse whatever the user gave us, clean it, infer real types, load it
into a typed Postgres table, then profile it.

Everything the pipeline does is recorded as a step so the UI can show the user
exactly what happened to their data.
"""

from __future__ import annotations

import io
import json
import math
import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from . import db
from .config import MAX_ROWS

NULL_TOKENS = {
    "", "na", "n/a", "n.a.", "nan", "none", "null", "nil", "-", "--", "?",
    "unknown", "undefined", "missing", "#n/a", "#na", "(blank)", "\\n",
}
BOOL_TRUE = {"true", "t", "yes", "y"}
BOOL_FALSE = {"false", "f", "no", "n"}
INT_RE = re.compile(r"^[+-]?\d+$")
NUM_CLEAN_RE = re.compile(r"[,\s ₹$€£¥%]")
DATEISH_RE = re.compile(r"[-/:]|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)


# ---------------------------------------------------------------- extract ---

def parse_source(filename: str, raw: bytes) -> pd.DataFrame:
    """Bytes -> DataFrame of strings. Every column comes in as text so that we
    control type inference ourselves instead of guessing twice."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(io.BytesIO(raw), dtype=str, engine="openpyxl")
        return df.astype(str).where(df.notna(), None)
    text = raw.decode("utf-8-sig", errors="replace")
    if name.endswith(".json") or text.lstrip()[:1] in "[{":
        return parse_records(json.loads(text))
    sep = "\t" if name.endswith((".tsv", ".tab")) else None  # None => sniff
    return pd.read_csv(
        io.StringIO(text), sep=sep, engine="python", dtype=str,
        keep_default_na=False, na_values=[], skip_blank_lines=True,
    )


def parse_records(payload: Any) -> pd.DataFrame:
    """JSON body -> DataFrame. Accepts a list of objects, a list of lists with a
    header row, or an object wrapping one of those."""
    if isinstance(payload, dict):
        for key in ("data", "rows", "records", "items", "results"):
            if key in payload:
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list) or not payload:
        raise ValueError("No rows found in the submitted data.")
    if isinstance(payload[0], dict):
        return pd.DataFrame(payload).astype(object)
    header = [str(c) for c in payload[0]]
    return pd.DataFrame(payload[1:], columns=header).astype(object)


# -------------------------------------------------------------- transform ---

def clean_name(raw: str, taken: set[str]) -> str:
    s = re.sub(r"[^0-9a-z]+", "_", str(raw).strip().lower()).strip("_")
    s = re.sub(r"_+", "_", s)[:58] or "column"
    if s[0].isdigit():
        s = f"c_{s}"
    base, i = s, 2
    while s in taken:
        s = f"{base}_{i}"
        i += 1
    taken.add(s)
    return s


def norm_cell(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    return None if s.lower() in NULL_TOKENS else s


def to_number(s: str) -> float | None:
    t = NUM_CLEAN_RE.sub("", s)
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        f = float(t)
    except ValueError:
        return None
    return None if math.isinf(f) or math.isnan(f) else f


def infer_type(values: list[str], name: str, n_rows: int) -> str:
    """Decide the semantic type of a column from its non-null string values."""
    if not values:
        return "text"
    sample = values[:5000]
    low = {v.lower() for v in sample}
    if low <= (BOOL_TRUE | BOOL_FALSE):
        return "boolean"
    if all(INT_RE.match(NUM_CLEAN_RE.sub("", v) or "x") for v in sample):
        distinct = len(set(sample))
        if distinct == len(sample) and n_rows > 5 and re.search(r"(^|_)(id|no|num|code)$", name):
            return "identifier"
        return "integer"
    if sum(to_number(v) is not None for v in sample) >= 0.98 * len(sample):
        return "numeric"
    dateish = [v for v in sample if DATEISH_RE.search(v)]
    if len(dateish) >= 0.9 * len(sample):
        parsed = pd.to_datetime(pd.Series(sample), errors="coerce", format="mixed", dayfirst=False)
        if parsed.notna().mean() >= 0.9:
            return "datetime"
    distinct = len(set(sample))
    # categorical means "a small set of repeating labels", not just "few rows"
    if distinct < len(sample) and distinct <= max(25, 0.05 * len(sample)) and distinct < 200:
        return "categorical"
    if distinct == len(sample) and n_rows > 20:
        return "identifier"
    return "text"


PG_TYPE = {
    "integer": "BIGINT", "numeric": "DOUBLE PRECISION", "boolean": "BOOLEAN",
    "datetime": "TIMESTAMP", "categorical": "TEXT", "text": "TEXT", "identifier": "TEXT",
}


def coerce(values: list[str | None], semantic: str) -> tuple[list[Any], int]:
    """String column -> typed column. Returns (values, cells_nulled_by_coercion)."""
    out: list[Any] = []
    lost = 0
    for v in values:
        if v is None:
            out.append(None)
            continue
        if semantic == "boolean":
            lv = v.lower()
            out.append(True if lv in BOOL_TRUE else False if lv in BOOL_FALSE else None)
        elif semantic == "integer":
            n = to_number(v)
            out.append(int(n) if n is not None else None)
        elif semantic == "numeric":
            out.append(to_number(v))
        elif semantic == "datetime":
            ts = pd.to_datetime(v, errors="coerce", format="mixed", dayfirst=False)
            out.append(None if pd.isna(ts) else ts.to_pydatetime().replace(tzinfo=None))
        else:
            out.append(v)
        if out[-1] is None:
            lost += 1
    return out, lost


# ------------------------------------------------------------------- load ---

def run_pipeline(dataset_id: str, name: str, df: pd.DataFrame, source_kind: str,
                 source_name: str, description: str = "") -> dict:
    """Full ELT for one dataset. Writes metadata rows as it goes so the UI can
    poll status. Raises on failure after marking the dataset as errored."""
    steps: list[dict] = []
    started = datetime.now()

    def step(title: str, detail: str, metric: Any = None) -> None:
        steps.append({"title": title, "detail": detail, "metric": metric,
                      "at": datetime.now().isoformat(timespec="seconds")})

    table = f"ds_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')[:32] or 'data'}_{dataset_id[:8]}"
    db.execute(
        """INSERT INTO core.datasets (id, name, description, source_kind, source_name,
                                      table_name, status)
           VALUES (%s,%s,%s,%s,%s,%s,'etl')""",
        (dataset_id, name, description, source_kind, source_name, table),
    )
    run = db.one(
        "INSERT INTO core.etl_runs (dataset_id, status, rows_in) VALUES (%s,'running',%s) RETURNING id",
        (dataset_id, len(df)),
    )
    run_id = run["id"]

    try:
        rows_in = len(df)
        step("Extract", f"Read {rows_in:,} rows and {len(df.columns)} columns from {source_name or source_kind}.", rows_in)
        if rows_in == 0:
            raise ValueError("The source contains no data rows.")
        if rows_in > MAX_ROWS:
            df = df.head(MAX_ROWS)
            step("Truncate", f"Source exceeded the {MAX_ROWS:,} row limit; kept the first {MAX_ROWS:,}.", MAX_ROWS)

        # 1. normalise headers
        taken: set[str] = set()
        originals = [str(c) for c in df.columns]
        names = [clean_name(c, taken) for c in originals]
        renamed = sum(1 for a, b in zip(originals, names) if a != b)
        step("Standardise columns", f"Renamed {renamed} header(s) to snake_case, de-duplicated collisions.", renamed)

        # 2. normalise cells to str|None
        cols: dict[str, list[str | None]] = {}
        for name_, orig in zip(names, originals):
            cols[name_] = [norm_cell(v) for v in df[orig].tolist()]

        # 3. drop empty columns
        empty_cols = [c for c, vals in cols.items() if all(v is None for v in vals)]
        for c in empty_cols:
            cols.pop(c)
        idx = [i for i, n in enumerate(names) if n not in empty_cols]
        names = [names[i] for i in idx]
        originals = [originals[i] for i in idx]
        if empty_cols:
            step("Drop empty columns", f"Removed {len(empty_cols)} column(s) with no values: {', '.join(empty_cols[:6])}.", len(empty_cols))
        if not names:
            raise ValueError("Every column in the source was empty.")

        # 4. drop empty rows + exact duplicates
        n = len(next(iter(cols.values())))
        keep, seen, blank, dupes = [], set(), 0, 0
        for i in range(n):
            row = tuple(cols[c][i] for c in names)
            if all(v is None for v in row):
                blank += 1
                continue
            if row in seen:
                dupes += 1
                continue
            seen.add(row)
            keep.append(i)
        if blank:
            step("Drop blank rows", f"Removed {blank:,} completely empty row(s).", blank)
        if dupes:
            step("De-duplicate", f"Removed {dupes:,} exact duplicate row(s).", dupes)
        for c in names:
            cols[c] = [cols[c][i] for i in keep]
        rows_out = len(keep)
        if rows_out == 0:
            raise ValueError("Nothing survived cleaning — the source had no usable rows.")

        # 5. infer + coerce types
        typed: dict[str, list[Any]] = {}
        semantics: dict[str, str] = {}
        coerced_total = 0
        for c in names:
            non_null = [v for v in cols[c] if v is not None]
            sem = infer_type(non_null, c, rows_out)
            semantics[c] = sem
            values, lost = coerce(cols[c], sem)
            coerced_total += lost
            typed[c] = values
        kinds = ", ".join(f"{k}×{list(semantics.values()).count(k)}" for k in dict.fromkeys(semantics.values()))
        step("Infer types", f"Detected column types ({kinds}).", len(names))
        if coerced_total:
            step("Quarantine bad cells", f"{coerced_total:,} cell(s) did not match their column type and were set to NULL.", coerced_total)

        # 6. create + load the physical table
        ddl_cols = ", ".join(f'"{c}" {PG_TYPE[semantics[c]]}' for c in names)
        with db.conn() as c:
            c.execute(f'DROP TABLE IF EXISTS data."{table}"')
            c.execute(f'CREATE TABLE data."{table}" ("_row_id" BIGSERIAL PRIMARY KEY, {ddl_cols})')
            collist = ", ".join(f'"{x}"' for x in names)
            with c.cursor().copy(f'COPY data."{table}" ({collist}) FROM STDIN') as cp:
                for i in range(rows_out):
                    cp.write_row([typed[col][i] for col in names])
        step("Load", f'Loaded {rows_out:,} rows into Postgres table data."{table}".', rows_out)

        # 7. profile
        profiles = profile_table(table, names, semantics)
        with db.conn() as c:
            c.execute("DELETE FROM core.dataset_columns WHERE dataset_id = %s", (dataset_id,))
            for pos, col in enumerate(names):
                p = profiles[col]
                c.execute(
                    """INSERT INTO core.dataset_columns
                       (dataset_id, position, name, original_name, pg_type, semantic_type,
                        null_count, distinct_count, stats)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (dataset_id, pos, col, originals[names.index(col)], PG_TYPE[semantics[col]],
                     semantics[col], p["null_count"], p["distinct_count"], json.dumps(p, default=jsonify)),
                )
        step("Profile", f"Computed statistics, null rates and top values for {len(names)} columns.", len(names))

        filled = sum(rows_out - profiles[c]["null_count"] for c in names)
        quality = round(100 * filled / max(1, rows_out * len(names)), 1)

        db.execute(
            """UPDATE core.datasets SET status='indexing', row_count=%s, column_count=%s,
               quality_score=%s, updated_at=now() WHERE id=%s""",
            (rows_out, len(names), quality, dataset_id),
        )
        db.execute(
            "UPDATE core.etl_runs SET status='success', rows_out=%s, steps=%s, finished_at=now() WHERE id=%s",
            (rows_out, json.dumps(steps), run_id),
        )
        return {"table": table, "columns": names, "semantics": semantics,
                "profiles": profiles, "rows": rows_out, "quality": quality,
                "steps": steps, "seconds": round((datetime.now() - started).total_seconds(), 2)}

    except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
        db.execute(
            "UPDATE core.etl_runs SET status='error', error=%s, steps=%s, finished_at=now() WHERE id=%s",
            (str(exc), json.dumps(steps), run_id),
        )
        db.execute("UPDATE core.datasets SET status='error', error=%s, updated_at=now() WHERE id=%s",
                   (str(exc), dataset_id))
        raise


def jsonify(v: Any) -> Any:
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return str(v)


# ---------------------------------------------------------------- profile ---

def profile_table(table: str, names: list[str], semantics: dict[str, str]) -> dict[str, dict]:
    """Per-column statistics computed in Postgres, not in Python."""
    out: dict[str, dict] = {}
    with db.conn() as c:
        total = c.execute(f'SELECT count(*) AS n FROM data."{table}"').fetchone()["n"]
        for col in names:
            sem = semantics[col]
            q = f'''SELECT count(*) FILTER (WHERE "{col}" IS NULL) AS nulls,
                           count(DISTINCT "{col}") AS distincts FROM data."{table}"'''
            base = c.execute(q).fetchone()
            p: dict[str, Any] = {
                "null_count": int(base["nulls"]), "distinct_count": int(base["distincts"]),
                "total": total, "semantic_type": sem,
                "null_pct": round(100 * base["nulls"] / max(1, total), 2),
            }
            if sem in ("integer", "numeric"):
                agg = c.execute(f'''
                    SELECT min("{col}") AS mn, max("{col}") AS mx, avg("{col}") AS mean,
                           stddev_samp("{col}") AS sd,
                           percentile_cont(0.25) WITHIN GROUP (ORDER BY "{col}") AS q1,
                           percentile_cont(0.50) WITHIN GROUP (ORDER BY "{col}") AS med,
                           percentile_cont(0.75) WITHIN GROUP (ORDER BY "{col}") AS q3,
                           sum("{col}") AS sum_val
                    FROM data."{table}"''').fetchone()
                p.update({k: (float(v) if v is not None else None) for k, v in agg.items()})
                hist = c.execute(f'''
                    SELECT width_bucket("{col}", %s, %s, 10) AS b, count(*) AS n
                    FROM data."{table}" WHERE "{col}" IS NOT NULL GROUP BY 1 ORDER BY 1''',
                    (agg["mn"], (agg["mx"] if agg["mx"] != agg["mn"] else (agg["mn"] or 0) + 1)),
                ).fetchall() if agg["mn"] is not None else []
                p["histogram"] = [{"bucket": int(r["b"]), "count": int(r["n"])} for r in hist]
            elif sem == "datetime":
                agg = c.execute(f'SELECT min("{col}") AS mn, max("{col}") AS mx FROM data."{table}"').fetchone()
                p["min"] = agg["mn"].isoformat() if agg["mn"] else None
                p["max"] = agg["mx"].isoformat() if agg["mx"] else None
            if sem in ("categorical", "boolean", "text", "integer"):
                top = c.execute(f'''
                    SELECT "{col}"::text AS v, count(*) AS n FROM data."{table}"
                    WHERE "{col}" IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT 10''').fetchall()
                p["top_values"] = [{"value": r["v"], "count": int(r["n"])} for r in top]
            sample = c.execute(f'''
                SELECT DISTINCT "{col}"::text AS v FROM data."{table}"
                WHERE "{col}" IS NOT NULL LIMIT 5''').fetchall()
            p["samples"] = [r["v"] for r in sample]
            out[col] = p
    return out


def new_id() -> str:
    return uuid.uuid4().hex
