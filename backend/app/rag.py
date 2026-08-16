"""RAG layer.

The user's own data becomes the knowledge base. We turn the loaded table into
natural-language chunks (dataset card, schema card, one card per column, and
narrated row batches), then retrieve with TF-IDF cosine similarity blended with
Postgres full-text search.

No embedding API, no model download - it stays free and works offline.
ponytail: TF-IDF over an in-memory matrix. Swap in pgvector + a real embedding
model if a dataset ever exceeds ~50k chunks.
"""

from __future__ import annotations

import re
from threading import Lock

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from . import db
from .etl import PG_TYPE

_cache: dict[str, tuple] = {}
_lock = Lock()
ROWS_PER_CHUNK = 8
MAX_ROW_CHUNKS = 1500


def _fmt(v) -> str:
    if v is None:
        return "unknown"
    if isinstance(v, float):
        return f"{v:,.4g}"
    return str(v)


def build_chunks(dataset_id: str, meta: dict, profiles: dict, table: str,
                 columns: list[str], semantics: dict[str, str]) -> int:
    """Write the retrievable knowledge base for one dataset. Returns chunk count."""
    chunks: list[tuple[str, str, str]] = []  # (kind, ref, content)
    name = meta["name"]
    rows = meta["row_count"]

    # 1. dataset card
    types = ", ".join(f"{c} ({semantics[c]})" for c in columns)
    chunks.append(("overview", "dataset", (
        f"Dataset '{name}' is stored in the Postgres table data.\"{table}\". "
        f"It has {rows:,} rows and {len(columns)} columns. "
        f"Description: {meta.get('description') or 'none provided'}. "
        f"Columns and their types: {types}. "
        f"Data completeness score: {meta.get('quality_score', 0)}%."
    )))

    # 2. schema card - the exact contract the SQL tool must obey
    lines = [f'  "{c}" {PG_TYPE[semantics[c]]} -- {semantics[c]}, '
             f'{profiles[c]["null_pct"]}% null, {profiles[c]["distinct_count"]} distinct'
             for c in columns]
    chunks.append(("schema", "schema", (
        f'SQL schema for dataset "{name}":\nCREATE TABLE data."{table}" (\n'
        + "\n".join(lines) + "\n);\n"
        f"Query it with: SELECT ... FROM data.\"{table}\";"
    )))

    # 3. one card per column
    for col in columns:
        p = profiles[col]
        sem = semantics[col]
        parts = [f'Column "{col}" of dataset "{name}" (table data."{table}") holds {sem} values.',
                 f'{p["total"] - p["null_count"]:,} of {p["total"]:,} rows have a value '
                 f'({p["null_pct"]}% missing), with {p["distinct_count"]:,} distinct values.']
        if sem in ("integer", "numeric") and p.get("mean") is not None:
            parts.append(
                f'Minimum {_fmt(p.get("mn"))}, maximum {_fmt(p.get("mx"))}, average {_fmt(p.get("mean"))}, '
                f'median {_fmt(p.get("med"))}, standard deviation {_fmt(p.get("sd"))}, '
                f'quartiles Q1 {_fmt(p.get("q1"))} and Q3 {_fmt(p.get("q3"))}, '
                f'total sum {_fmt(p.get("sum_val"))}.')
        if sem == "datetime":
            parts.append(f'Values range from {p.get("min")} to {p.get("max")}.')
        if p.get("top_values"):
            tv = "; ".join(f'{t["value"]} ({t["count"]:,} rows)' for t in p["top_values"][:8])
            parts.append(f"Most frequent values: {tv}.")
        elif p.get("samples"):
            parts.append(f'Example values: {", ".join(p["samples"])}.')
        chunks.append(("column", col, " ".join(parts)))

    # 4. narrated row batches - lets the assistant quote individual records
    with db.conn() as c:
        cur = c.execute(
            f'SELECT "_row_id", {", ".join(chr(34) + x + chr(34) for x in columns)} '
            f'FROM data."{table}" ORDER BY "_row_id" LIMIT {ROWS_PER_CHUNK * MAX_ROW_CHUNKS}')
        batch: list[str] = []
        first = None
        for r in cur:
            if first is None:
                first = r["_row_id"]
            batch.append(f'Row {r["_row_id"]}: '
                         + "; ".join(f'{col} = {_fmt(r[col])}' for col in columns))
            if len(batch) >= ROWS_PER_CHUNK:
                chunks.append(("rows", f"{first}-{r['_row_id']}",
                               f'Records from dataset "{name}".\n' + "\n".join(batch)))
                batch, first = [], None
        if batch:
            chunks.append(("rows", f"{first}+", f'Records from dataset "{name}".\n' + "\n".join(batch)))

    # 5. auto-insights: what stands out without being asked
    for ins in auto_insights(name, table, columns, semantics, profiles):
        chunks.append(("insight", "auto", ins))

    with db.conn() as c:
        c.execute("DELETE FROM core.rag_chunks WHERE dataset_id = %s", (dataset_id,))
        with c.cursor().copy(
            "COPY core.rag_chunks (dataset_id, kind, ref, content) FROM STDIN") as cp:
            for kind, ref, content in chunks:
                cp.write_row([dataset_id, kind, ref, content])
    with _lock:
        _cache.pop(dataset_id, None)
    return len(chunks)


def auto_insights(name: str, table: str, columns: list[str], semantics: dict[str, str],
                  profiles: dict) -> list[str]:
    """Cheap, always-true observations that make cold-start answers better."""
    out: list[str] = []
    nums = [c for c in columns if semantics[c] in ("integer", "numeric")]
    cats = [c for c in columns if semantics[c] in ("categorical", "boolean")]
    dates = [c for c in columns if semantics[c] == "datetime"]

    incomplete = sorted((c for c in columns if profiles[c]["null_pct"] > 5),
                        key=lambda c: -profiles[c]["null_pct"])[:5]
    if incomplete:
        out.append(f'Data quality note for "{name}": these columns have missing values - '
                   + ", ".join(f'{c} ({profiles[c]["null_pct"]}% missing)' for c in incomplete) + ".")

    for col in nums[:6]:
        p = profiles[col]
        if p.get("sd") and p.get("mean") is not None and p["sd"] > 0:
            hi = p["mean"] + 3 * p["sd"]
            lo = p["mean"] - 3 * p["sd"]
            try:
                n = db.query(f'SELECT count(*) AS n FROM data."{table}" '
                             f'WHERE "{col}" > %s OR "{col}" < %s', (hi, lo))[0]["n"]
            except Exception:
                continue
            if n:
                out.append(f'Outliers in "{col}" of dataset "{name}": {n:,} rows fall outside '
                           f'3 standard deviations ({lo:,.4g} to {hi:,.4g}). Median is {_fmt(p.get("med"))}.')

    for cat in cats[:3]:
        for num in nums[:3]:
            try:
                rows = db.query(f'''SELECT "{cat}"::text AS k, count(*) AS n, avg("{num}") AS a,
                                           sum("{num}") AS s
                                    FROM data."{table}" WHERE "{cat}" IS NOT NULL
                                    GROUP BY 1 ORDER BY s DESC NULLS LAST LIMIT 5''')
            except Exception:
                continue
            if len(rows) > 1:
                body = "; ".join(f'{r["k"]}: total {_fmt(float(r["s"]) if r["s"] is not None else None)}, '
                                 f'average {_fmt(float(r["a"]) if r["a"] is not None else None)} '
                                 f'across {r["n"]:,} rows' for r in rows)
                out.append(f'Breakdown of "{num}" by "{cat}" in dataset "{name}" (top 5 by total): {body}.')

    for d in dates[:1]:
        for num in nums[:2]:
            try:
                rows = db.query(f'''SELECT date_trunc('month', "{d}")::date AS m, count(*) AS n,
                                           sum("{num}") AS s
                                    FROM data."{table}" WHERE "{d}" IS NOT NULL
                                    GROUP BY 1 ORDER BY 1 LIMIT 24''')
            except Exception:
                continue
            if len(rows) > 2:
                body = "; ".join(f'{r["m"]}: {_fmt(float(r["s"]) if r["s"] is not None else None)}' for r in rows)
                out.append(f'Monthly trend of "{num}" by "{d}" in dataset "{name}": {body}.')
    return out


# -------------------------------------------------------------- retrieval ---

def _matrix(dataset_id: str):
    with _lock:
        hit = _cache.get(dataset_id)
    if hit:
        return hit
    rows = db.query(
        "SELECT id, kind, ref, content FROM core.rag_chunks WHERE dataset_id=%s ORDER BY id",
        (dataset_id,))
    if not rows:
        return None
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True,
                          max_features=60000, token_pattern=r"(?u)\b\w[\w./-]+\b")
    mat = vec.fit_transform([r["content"] for r in rows])
    built = (vec, mat, rows)
    with _lock:
        _cache[dataset_id] = built
    return built


def retrieve(dataset_id: str, question: str, k: int = 8) -> list[dict]:
    """Hybrid retrieval: TF-IDF cosine + Postgres full-text, merged by score."""
    built = _matrix(dataset_id)
    if not built:
        return []
    vec, mat, rows = built
    scores = np.asarray((mat @ vec.transform([question]).T).todense()).ravel()
    # summarised knowledge beats raw rows for analytical questions
    weights = {"insight": 2.0, "column": 1.6, "overview": 1.2, "schema": 1.2, "rows": 0.6}
    scores = scores * np.array([weights.get(r["kind"], 1.0) for r in rows])

    # keyword boost: exact column/value mentions matter more than tf-idf alone
    terms = [t for t in re.findall(r"\w{3,}", question.lower())]
    if terms:
        try:
            fts = db.query(
                """SELECT id, ts_rank(to_tsvector('english', content),
                                      plainto_tsquery('english', %s)) AS r
                   FROM core.rag_chunks WHERE dataset_id=%s
                     AND to_tsvector('english', content) @@ plainto_tsquery('english', %s)
                   ORDER BY r DESC LIMIT 30""", (question, dataset_id, question))
            pos = {r["id"]: i for i, r in enumerate(rows)}
            top = max((f["r"] for f in fts), default=0) or 1
            for f in fts:
                if f["id"] in pos:
                    scores[pos[f["id"]]] += 0.4 * (f["r"] / top)
        except Exception:
            pass

    # always anchor on the schema + overview cards
    order = np.argsort(-scores)[: k * 3]
    picked: list[dict] = []
    for kind in ("schema", "overview"):
        for i, r in enumerate(rows):
            if r["kind"] == kind:
                picked.append({**r, "score": float(scores[i])})
                break
    seen = {p["id"] for p in picked}
    for i in order:
        if rows[i]["id"] in seen or scores[i] <= 0:
            continue
        picked.append({**rows[i], "score": float(scores[i])})
        seen.add(rows[i]["id"])
        if len(picked) >= k:
            break
    return picked


def invalidate(dataset_id: str) -> None:
    with _lock:
        _cache.pop(dataset_id, None)
