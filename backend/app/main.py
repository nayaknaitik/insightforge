"""InsightForge API: upload -> ELT -> Postgres -> profile -> RAG index -> ask."""

from __future__ import annotations

import csv
import io
import json
import traceback
from contextlib import asynccontextmanager
from typing import Any

import pandas as pd
from fastapi import (BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request,
                     UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse

from . import analysis, assistant, db, etl, rag
from .config import (CORS_ORIGINS, GROQ_API_KEY, GROQ_MODEL, MAX_UPLOAD_MB, PG_DB, PG_HOST,
                     PG_PORT, PG_USER)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield
    db.shutdown()


app = FastAPI(title="InsightForge API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def fail(code: int, msg: str):
    raise HTTPException(status_code=code, detail=msg)


# ------------------------------------------------------------------ meta ---

@app.get("/api/health")
def health():
    try:
        db.query("SELECT 1")
        pg = True
    except Exception:
        pg = False
    return {"ok": pg, "postgres": {"ok": pg, "host": PG_HOST, "port": PG_PORT,
                                   "database": PG_DB, "user": PG_USER},
            "llm": {"provider": "groq", "model": GROQ_MODEL, "key_configured": bool(GROQ_API_KEY)},
            "datasets": db.one("SELECT count(*) AS n FROM core.datasets")["n"] if pg else 0}


# -------------------------------------------------------------- ingestion ---

def _index(dataset_id: str, table: str, columns: list[str], semantics: dict, profiles: dict):
    """Background: build the RAG knowledge base, then mark the dataset ready."""
    try:
        meta = db.one("SELECT * FROM core.datasets WHERE id=%s", (dataset_id,))
        n = rag.build_chunks(dataset_id, meta, profiles, table, columns, semantics)
        db.execute("UPDATE core.datasets SET status='ready', updated_at=now() WHERE id=%s", (dataset_id,))
        return n
    except Exception as exc:
        db.execute("UPDATE core.datasets SET status='error', error=%s WHERE id=%s",
                   (f"RAG indexing failed: {exc}", dataset_id))


def _ingest(name: str, description: str, df: pd.DataFrame, kind: str, source: str,
            bg: BackgroundTasks | None) -> dict:
    dataset_id = etl.new_id()
    try:
        result = etl.run_pipeline(dataset_id, name, df, kind, source, description)
    except Exception as exc:
        traceback.print_exc()
        fail(400, f"ETL failed: {exc}")
    args = (dataset_id, result["table"], result["columns"], result["semantics"], result["profiles"])
    if bg:
        bg.add_task(_index, *args)
    else:
        _index(*args)
    return {"id": dataset_id, "status": "indexing", **{k: result[k] for k in
            ("table", "columns", "rows", "quality", "steps", "seconds")}}


@app.post("/api/datasets/upload")
async def upload(bg: BackgroundTasks, file: UploadFile = File(...), name: str = Form(""),
                 description: str = Form("")):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        fail(413, f"File is larger than the {MAX_UPLOAD_MB} MB limit.")
    if not raw:
        fail(400, "The uploaded file is empty.")
    try:
        df = etl.parse_source(file.filename or "", raw)
    except Exception as exc:
        fail(400, f"Could not read that file: {exc}")
    label = name.strip() or (file.filename or "dataset").rsplit(".", 1)[0]
    return _ingest(label, description, df, "upload", file.filename or "", bg)


@app.post("/api/datasets/manual")
def manual(bg: BackgroundTasks, payload: dict = Body(...)):
    name = (payload.get("name") or "Manual dataset").strip()
    rows = payload.get("rows")
    columns = payload.get("columns")
    text = payload.get("text")
    try:
        if text:
            df = etl.parse_source("pasted.csv", text.encode())
            kind, source = "paste", "pasted text"
        elif columns and rows is not None:
            df = pd.DataFrame(rows, columns=[str(c) for c in columns]).astype(object)
            kind, source = "manual", "manual entry grid"
        elif rows:
            df = etl.parse_records(rows)
            kind, source = "manual", "manual entry"
        else:
            fail(400, "Provide either `text`, or `columns` + `rows`.")
    except HTTPException:
        raise
    except Exception as exc:
        fail(400, f"Could not read that data: {exc}")
    return _ingest(name, payload.get("description", ""), df, kind, source, bg)


# --------------------------------------------------------------- datasets ---

@app.get("/api/datasets")
def list_datasets():
    return db.query("""SELECT d.*, (SELECT count(*) FROM core.rag_chunks r WHERE r.dataset_id=d.id) AS chunk_count
                       FROM core.datasets d ORDER BY d.created_at DESC""")


@app.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    ds = db.one("SELECT * FROM core.datasets WHERE id=%s", (dataset_id,))
    if not ds:
        fail(404, "Dataset not found.")
    cols = db.query("SELECT * FROM core.dataset_columns WHERE dataset_id=%s ORDER BY position",
                    (dataset_id,))
    runs = db.query("SELECT * FROM core.etl_runs WHERE dataset_id=%s ORDER BY id DESC", (dataset_id,))
    chunks = db.query("""SELECT kind, count(*) AS n FROM core.rag_chunks WHERE dataset_id=%s
                         GROUP BY kind ORDER BY kind""", (dataset_id,))
    return {"dataset": ds, "columns": cols, "etl_runs": runs,
            "chunks": {c["kind"]: c["n"] for c in chunks},
            "chunk_count": sum(c["n"] for c in chunks)}


@app.get("/api/datasets/{dataset_id}/preview")
def preview(dataset_id: str, limit: int = 50, offset: int = 0):
    try:
        return analysis.preview(dataset_id, min(limit, 500), offset)
    except Exception as exc:
        fail(400, str(exc))


@app.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    ds = db.one("SELECT table_name FROM core.datasets WHERE id=%s", (dataset_id,))
    if not ds:
        fail(404, "Dataset not found.")
    db.execute(f'DROP TABLE IF EXISTS data."{ds["table_name"]}"')
    db.execute("DELETE FROM core.datasets WHERE id=%s", (dataset_id,))
    rag.invalidate(dataset_id)
    return {"deleted": dataset_id}


@app.post("/api/datasets/{dataset_id}/reindex")
def reindex(dataset_id: str):
    ds = db.one("SELECT * FROM core.datasets WHERE id=%s", (dataset_id,))
    if not ds:
        fail(404, "Dataset not found.")
    cols = db.query("SELECT * FROM core.dataset_columns WHERE dataset_id=%s ORDER BY position",
                    (dataset_id,))
    names = [c["name"] for c in cols]
    semantics = {c["name"]: c["semantic_type"] for c in cols}
    profiles = {c["name"]: (c["stats"] if isinstance(c["stats"], dict) else json.loads(c["stats"]))
                for c in cols}
    n = rag.build_chunks(dataset_id, ds, profiles, ds["table_name"], names, semantics)
    db.execute("UPDATE core.datasets SET status='ready', updated_at=now() WHERE id=%s", (dataset_id,))
    return {"chunks": n}


@app.get("/api/datasets/{dataset_id}/chunks")
def chunks(dataset_id: str, limit: int = 50, kind: str = ""):
    q = "SELECT id, kind, ref, content FROM core.rag_chunks WHERE dataset_id=%s"
    params: list[Any] = [dataset_id]
    if kind:
        q += " AND kind=%s"
        params.append(kind)
    q += " ORDER BY id LIMIT %s"
    params.append(min(limit, 300))
    return db.query(q, tuple(params))


@app.post("/api/datasets/{dataset_id}/search")
def search(dataset_id: str, payload: dict = Body(...)):
    hits = rag.retrieve(dataset_id, payload.get("query", ""), int(payload.get("k", 8)))
    return {"matches": hits}


# --------------------------------------------------------------- analysis ---

@app.post("/api/datasets/{dataset_id}/query")
def query_sql(dataset_id: str, payload: dict = Body(...)):
    try:
        return analysis.run_sql(payload.get("sql", ""))
    except Exception as exc:
        fail(400, str(exc))


@app.post("/api/datasets/{dataset_id}/analyze")
def analyze(dataset_id: str, payload: dict = Body(...)):
    kind = payload.get("kind")
    try:
        if kind == "describe":
            return analysis.describe(dataset_id, payload.get("columns"))
        if kind == "correlation":
            return analysis.correlation(dataset_id, payload.get("columns"))
        if kind == "outliers":
            return analysis.outliers(dataset_id, payload["column"], payload.get("method", "iqr"))
        if kind == "distribution":
            return analysis.distribution(dataset_id, payload["column"], int(payload.get("bins", 12)))
        if kind == "group_summary":
            return analysis.group_summary(dataset_id, payload["dimension"], payload.get("measure"),
                                          payload.get("agg", "sum"), int(payload.get("top", 20)))
        if kind == "trend":
            return analysis.trend(dataset_id, payload["date_column"], payload.get("measure"),
                                  payload.get("agg", "sum"), payload.get("granularity", "month"),
                                  int(payload.get("forecast", 0)))
        fail(400, f"Unknown analysis kind: {kind}")
    except HTTPException:
        raise
    except KeyError as exc:
        fail(400, f"Missing parameter: {exc}")
    except Exception as exc:
        fail(400, str(exc))


@app.get("/api/datasets/{dataset_id}/suggestions")
def suggestions(dataset_id: str):
    return {"questions": assistant.suggest(dataset_id)}


# ------------------------------------------------------------------ chat ---

@app.get("/api/conversations")
def conversations(dataset_id: str = ""):
    if dataset_id:
        return db.query("SELECT * FROM core.conversations WHERE dataset_id=%s ORDER BY created_at DESC",
                        (dataset_id,))
    return db.query("SELECT * FROM core.conversations ORDER BY created_at DESC")


@app.get("/api/conversations/{conversation_id}/messages")
def messages(conversation_id: str):
    return db.query("SELECT * FROM core.messages WHERE conversation_id=%s ORDER BY id",
                    (conversation_id,))


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    db.execute("DELETE FROM core.conversations WHERE id=%s", (conversation_id,))
    return {"deleted": conversation_id}


@app.post("/api/chat")
def chat(payload: dict = Body(...)):
    dataset_id = payload.get("dataset_id")
    question = (payload.get("question") or "").strip()
    if not dataset_id or not question:
        fail(400, "dataset_id and question are required.")
    ds = db.one("SELECT status, name FROM core.datasets WHERE id=%s", (dataset_id,))
    if not ds:
        fail(404, "Dataset not found.")
    if ds["status"] not in ("ready", "indexing"):
        fail(409, f'Dataset is not ready yet (status: {ds["status"]}).')

    conv_id = payload.get("conversation_id")
    if not conv_id:
        conv_id = etl.new_id()
        db.execute("INSERT INTO core.conversations (id, dataset_id, title) VALUES (%s,%s,%s)",
                   (conv_id, dataset_id, question[:70]))
    elif not db.one("SELECT 1 AS x FROM core.conversations WHERE id=%s", (conv_id,)):
        db.execute("INSERT INTO core.conversations (id, dataset_id, title) VALUES (%s,%s,%s)",
                   (conv_id, dataset_id, question[:70]))

    history = db.query("SELECT role, content FROM core.messages WHERE conversation_id=%s "
                       "ORDER BY id DESC LIMIT 8", (conv_id,))[::-1]
    db.execute("INSERT INTO core.messages (conversation_id, role, content) VALUES (%s,'user',%s)",
               (conv_id, question))
    try:
        result = assistant.ask(dataset_id, question, history)
    except RuntimeError as exc:
        fail(503, str(exc))
    except Exception as exc:
        traceback.print_exc()
        fail(502, f"Assistant failed: {exc}")
    meta = {k: result[k] for k in ("steps", "tables", "charts", "sql", "citations", "model")}
    db.execute("INSERT INTO core.messages (conversation_id, role, content, meta) "
               "VALUES (%s,'assistant',%s,%s)", (conv_id, result["answer"], json.dumps(meta, default=str)))
    return {"conversation_id": conv_id, **result}


# --------------------------------------------------------------- Power BI ---

def _rows_csv(dataset_id: str) -> tuple[str, io.StringIO]:
    ds = db.one("SELECT name, table_name FROM core.datasets WHERE id=%s", (dataset_id,))
    if not ds:
        fail(404, "Dataset not found.")
    cols, rows = db.read_only(f'SELECT * FROM data."{ds["table_name"]}" ORDER BY "_row_id"')
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows([[analysis.clean(v) for v in r] for r in rows])
    buf.seek(0)
    return ds["name"], buf


@app.get("/api/datasets/{dataset_id}/export.csv")
def export_csv(dataset_id: str):
    name, buf = _rows_csv(dataset_id)
    return StreamingResponse(buf, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{name.replace(chr(34), "")}.csv"'})


@app.get("/api/powerbi/{dataset_id}/feed")
def powerbi_feed(dataset_id: str, top: int = 100000):
    """JSON feed for the Power BI 'Web' connector - no database driver needed."""
    ds = db.one("SELECT table_name FROM core.datasets WHERE id=%s", (dataset_id,))
    if not ds:
        fail(404, "Dataset not found.")
    cols, rows = db.read_only(
        f'SELECT * FROM data."{ds["table_name"]}" ORDER BY "_row_id" LIMIT {int(top)}')
    return {"value": [{c: analysis.clean(v) for c, v in zip(cols, r)} for r in rows]}


@app.get("/api/powerbi/{dataset_id}/connection")
def powerbi_connection(dataset_id: str, request: Request):
    ds = db.one("SELECT name, table_name, row_count, column_count FROM core.datasets WHERE id=%s",
                (dataset_id,))
    if not ds:
        fail(404, "Dataset not found.")
    base = str(request.base_url).rstrip("/")
    return {
        "dataset": ds["name"],
        "direct_query": {"server": f"{PG_HOST}:{PG_PORT}", "database": PG_DB, "user": PG_USER,
                         "schema": "data", "table": ds["table_name"],
                         "native_query": f'SELECT * FROM data."{ds["table_name"]}"'},
        "web_feed": f"{base}/api/powerbi/{dataset_id}/feed",
        "csv": f"{base}/api/datasets/{dataset_id}/export.csv",
        "pbids": f"{base}/api/powerbi/{dataset_id}/dataset.pbids",
        "rows": ds["row_count"], "columns": ds["column_count"],
    }


@app.get("/api/powerbi/{dataset_id}/dataset.pbids")
def powerbi_pbids(dataset_id: str):
    """A .pbids file: double-click it and Power BI Desktop opens straight onto this table."""
    ds = db.one("SELECT name, table_name FROM core.datasets WHERE id=%s", (dataset_id,))
    if not ds:
        fail(404, "Dataset not found.")
    doc = {"version": "0.1", "connections": [{
        "details": {"protocol": "postgresql",
                    "address": {"server": f"{PG_HOST}:{PG_PORT}", "database": PG_DB}},
        "options": {}, "mode": "Import"}]}
    body = json.dumps(doc, indent=2)
    safe = "".join(ch for ch in ds["name"] if ch.isalnum() or ch in "-_ ").strip() or "dataset"
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{safe}.pbids"'})


@app.get("/api/powerbi/{dataset_id}/instructions", response_class=PlainTextResponse)
def powerbi_instructions(dataset_id: str, request: Request):
    c = powerbi_connection(dataset_id, request)
    d = c["direct_query"]
    return (
        f"Connect Power BI Desktop to \"{c['dataset']}\"\n"
        f"{'=' * 60}\n\n"
        f"Option A - PostgreSQL connector (live, recommended)\n"
        f"  1. Home > Get Data > More > Database > PostgreSQL database\n"
        f"  2. Server:   {d['server']}\n"
        f"     Database: {d['database']}\n"
        f"  3. Data Connectivity mode: Import (or DirectQuery for live refresh)\n"
        f"  4. Sign in with user '{d['user']}'\n"
        f"  5. Pick schema '{d['schema']}' > table '{d['table']}' > Load\n\n"
        f"Option B - one-click file\n"
        f"  Download {c['pbids']} and open it with Power BI Desktop.\n\n"
        f"Option C - no driver needed\n"
        f"  Home > Get Data > Web, then paste this URL:\n"
        f"  {c['web_feed']}\n\n"
        f"Option D - static export\n"
        f"  {c['csv']}\n\n"
        f"Advanced: paste this as a native query\n"
        f"  {d['native_query']}\n")
