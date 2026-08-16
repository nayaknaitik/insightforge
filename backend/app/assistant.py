"""The RAG assistant.

Groq hosts the model. The model never sees the whole table - it gets retrieved
context plus four tools it can call in a loop:

  search_data  - pull more chunks out of the user's own data (the RAG part)
  run_sql      - read-only SQL against the loaded table (the exact-numbers part)
  analyze      - named statistical analyses (describe/correlate/outliers/trend/...)
  make_chart   - turn the most recent result table into a chart the UI renders
"""

from __future__ import annotations

import json
import re
from typing import Any

from groq import Groq

from . import analysis, db, rag
from .config import GROQ_API_KEY, GROQ_BASE_URL, GROQ_FALLBACK_MODEL, GROQ_MODEL

MAX_STEPS = 8
CHART_TYPES = ("bar", "line", "area", "pie", "scatter")

TOOLS = [
    {"type": "function", "function": {
        "name": "search_data",
        "description": "Semantic search over the user's dataset knowledge base: the dataset "
                       "card, column profiles, narrated rows and pre-computed insights. Use it "
                       "for questions about what the data contains, its meaning or its quality.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to look for, in plain language."}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "Run one read-only SELECT against the dataset table in Postgres. Use it "
                       "whenever the answer needs exact numbers, filters, joins or aggregations. "
                       "Always double-quote column names.",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "A single SELECT statement."},
            "purpose": {"type": "string", "description": "One line on what this query answers."}},
            "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "analyze",
        "description": "Run a named statistical analysis on the dataset.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string",
                     "enum": ["describe", "correlation", "outliers", "distribution",
                              "group_summary", "trend"]},
            "column": {"type": "string", "description": "Target column (outliers, distribution)."},
            "columns": {"type": "array", "items": {"type": "string"},
                        "description": "Columns for describe/correlation."},
            "dimension": {"type": "string", "description": "Grouping column for group_summary."},
            "measure": {"type": "string", "description": "Numeric column to aggregate."},
            "date_column": {"type": "string", "description": "Date column for trend."},
            "agg": {"type": "string", "enum": ["sum", "avg", "count", "min", "max"]},
            "granularity": {"type": "string", "enum": ["day", "week", "month", "quarter", "year"]},
            "forecast": {"type": "integer", "description": "Periods to project forward on a trend."},
            "method": {"type": "string", "enum": ["iqr", "zscore"]}},
            "required": ["kind"]}}},
    {"type": "function", "function": {
        "name": "make_chart",
        "description": "Render the most recent result table as a chart in the user interface. "
                       "Call it after run_sql or analyze when a picture helps.",
        "parameters": {"type": "object", "properties": {
            "chart_type": {"type": "string", "enum": list(CHART_TYPES)},
            "title": {"type": "string"},
            "x": {"type": "string", "description": "Column from the last result used for the x axis / labels."},
            "y": {"type": "array", "items": {"type": "string"},
                  "description": "One or more numeric columns from the last result."}},
            "required": ["chart_type", "title", "x", "y"]}}},
]

SYSTEM = """You are InsightForge, a senior data analyst embedded in an analytics platform.
You answer questions about ONE dataset that the user uploaded and that has already been
cleaned, typed and loaded into PostgreSQL.

CONTEXT ABOUT THE DATASET
{context}

RULES
1. Never invent numbers. Every figure you state must come from a tool result in this
   conversation. If a tool has not produced it yet, call a tool.
2. Prefer run_sql for anything countable. The table is data."{table}". Column names are
   case-sensitive: always wrap them in double quotes. Add a LIMIT to exploratory queries.
3. Use analyze for statistics (describe, correlation, outliers, distribution, group_summary,
   trend with optional forecast) instead of hand-rolling the SQL.
4. Call make_chart whenever a comparison, breakdown or time series would read better as a
   picture. Chart columns must exactly match the column names of the most recent result.
5. If a question is ambiguous, pick the most useful interpretation, say which one you picked,
   and answer it. Do not stall.
6. Answer in Markdown. Lead with the direct answer in one or two sentences, then the
   supporting detail, then a short "What this means" takeaway. Use compact tables for small
   result sets. Keep it tight - no filler.
7. If the data genuinely cannot answer the question, say so plainly and say what extra column
   or dataset would be needed.
8. Never write image links or made-up URLs. Charts appear only through make_chart, and the
   interface renders them under your answer - do not describe them as attachments.

AVAILABLE COLUMNS
{columns}
"""


_THINK = re.compile(r"<think>.*?</think>\s*", re.S | re.I)
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _tidy(text: str) -> str:
    """Strip reasoning tags and hallucinated image links - charts are rendered
    by the interface from make_chart, never from a URL the model invents."""
    return _IMG.sub("", _THINK.sub("", text or "")).strip()


def _client() -> Groq:
    if not GROQ_API_KEY:
        raise RuntimeError(
            "No GROQ_API_KEY set. Put your key in backend/.env as GROQ_API_KEY=gsk_... "
            "and restart the API.")
    return Groq(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL or None, timeout=120.0)


def _context(dataset_id: str, question: str) -> tuple[str, list[dict]]:
    hits = rag.retrieve(dataset_id, question, k=10)
    blocks = [f"[{h['kind']}:{h['ref']}]\n{h['content']}" for h in hits]
    return "\n\n".join(blocks) if blocks else "(no indexed context yet)", hits


def _result_table(payload: dict) -> dict | None:
    if isinstance(payload, dict) and payload.get("columns") and payload.get("rows") is not None:
        return {"columns": payload["columns"], "rows": payload["rows"]}
    return None


def _shrink(payload: Any, max_rows: int = 40) -> Any:
    """Keep tool output small enough to stay inside the context window."""
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list) and len(payload["rows"]) > max_rows:
        out = dict(payload)
        out["rows"] = payload["rows"][:max_rows]
        out["note"] = f"Showing the first {max_rows} of {len(payload['rows'])} rows."
        return out
    return payload


def ask(dataset_id: str, question: str, history: list[dict] | None = None) -> dict:
    ds = db.one("SELECT * FROM core.datasets WHERE id=%s", (dataset_id,))
    if not ds:
        raise ValueError("Dataset not found.")
    cols = db.query("SELECT name, semantic_type, pg_type FROM core.dataset_columns "
                    "WHERE dataset_id=%s ORDER BY position", (dataset_id,))
    col_lines = "\n".join(f'  "{c["name"]}"  {c["pg_type"]}  ({c["semantic_type"]})' for c in cols)
    context, hits = _context(dataset_id, question)

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM.format(context=context, table=ds["table_name"],
                                                    columns=col_lines)}]
    for h in (history or [])[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})

    client = _client()
    steps: list[dict] = []
    tables: list[dict] = []
    charts: list[dict] = []
    sqls: list[dict] = []
    last_table: dict | None = None
    model = GROQ_MODEL

    for _ in range(MAX_STEPS):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=TOOLS, tool_choice="auto",
                temperature=0.2, max_tokens=2600)
        except Exception as exc:  # model retired / rate limited -> try the fallback once
            if model == GROQ_MODEL and GROQ_FALLBACK_MODEL and GROQ_FALLBACK_MODEL != GROQ_MODEL:
                model = GROQ_FALLBACK_MODEL
                steps.append({"tool": "model", "detail": f"Falling back to {model}: {exc}"})
                continue
            raise
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.function.name,
                                                      "arguments": c.function.arguments}}
                                        for c in calls]} if calls else
                        {"role": "assistant", "content": msg.content or ""})
        if not calls:
            return {"answer": _tidy(msg.content) or "(no answer produced)", "steps": steps,
                    "tables": tables, "charts": charts, "sql": sqls,
                    "citations": [{"kind": h["kind"], "ref": h["ref"],
                                   "excerpt": h["content"][:400], "score": round(h["score"], 3)}
                                  for h in hits], "model": model}

        for call in calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                payload, step = _dispatch(dataset_id, name, args, last_table, tables, charts, sqls)
                if name in ("run_sql", "analyze"):
                    t = _result_table(payload)
                    if t:
                        last_table = t
            except Exception as exc:  # tool errors go back to the model so it can retry
                payload = {"error": str(exc)}
                step = {"tool": name, "detail": str(exc), "ok": False, "args": args}
            steps.append(step)
            messages.append({"role": "tool", "tool_call_id": call.id, "name": name,
                             "content": json.dumps(_shrink(payload), default=str)[:12000]})

    return {"answer": "I ran out of analysis steps before finishing. Try narrowing the question.",
            "steps": steps, "tables": tables, "charts": charts, "sql": sqls,
            "citations": [], "model": model}


def _dispatch(dataset_id: str, name: str, args: dict, last_table: dict | None,
              tables: list, charts: list, sqls: list) -> tuple[Any, dict]:
    if name == "search_data":
        hits = rag.retrieve(dataset_id, args.get("query", ""), k=6)
        return ({"matches": [{"kind": h["kind"], "ref": h["ref"], "content": h["content"][:1200]}
                             for h in hits]},
                {"tool": "search_data", "detail": f'Searched the knowledge base for "{args.get("query", "")}" '
                                                  f'({len(hits)} matches).', "ok": True, "args": args})

    if name == "run_sql":
        res = analysis.run_sql(args.get("sql", ""))
        sqls.append({"sql": res["sql"], "purpose": args.get("purpose", ""),
                     "row_count": res["row_count"]})
        tables.append({"title": args.get("purpose") or "Query result",
                       "columns": res["columns"], "rows": res["rows"], "sql": res["sql"]})
        return res, {"tool": "run_sql", "detail": args.get("purpose") or res["sql"],
                     "ok": True, "sql": res["sql"], "rows": res["row_count"]}

    if name == "analyze":
        kind = args.get("kind")
        fn = {
            "describe": lambda: analysis.describe(dataset_id, args.get("columns")),
            "correlation": lambda: analysis.correlation(dataset_id, args.get("columns")),
            "outliers": lambda: analysis.outliers(dataset_id, args["column"], args.get("method", "iqr")),
            "distribution": lambda: analysis.distribution(dataset_id, args["column"]),
            "group_summary": lambda: analysis.group_summary(
                dataset_id, args["dimension"], args.get("measure"), args.get("agg", "sum")),
            "trend": lambda: analysis.trend(
                dataset_id, args["date_column"], args.get("measure") or args.get("column"),
                args.get("agg", "sum"), args.get("granularity", "month"), args.get("forecast", 0)),
        }.get(kind)
        if not fn:
            raise ValueError(f"Unknown analysis kind: {kind}")
        res = fn()
        t = _result_table(res)
        if t:
            tables.append({"title": f"{kind} analysis", **t})
        return res, {"tool": "analyze", "detail": f"Ran {kind} analysis.", "ok": True, "args": args}

    if name == "make_chart":
        if not last_table:
            raise ValueError("Run run_sql or analyze first - there is no result table to chart.")
        x = args.get("x")
        ys = [y for y in (args.get("y") or []) if y in last_table["columns"]]
        if x not in last_table["columns"] or not ys:
            raise ValueError(f'Chart columns must come from the last result: {last_table["columns"]}')
        xi = last_table["columns"].index(x)
        yis = [last_table["columns"].index(y) for y in ys]
        data = [{"label": str(r[xi]), **{y: r[i] for y, i in zip(ys, yis)}}
                for r in last_table["rows"][:200]]
        chart = {"type": args.get("chart_type", "bar"), "title": args.get("title", "Chart"),
                 "x": x, "series": ys, "data": data}
        charts.append(chart)
        return {"ok": True, "points": len(data)}, {
            "tool": "make_chart", "detail": f'Built a {chart["type"]} chart: {chart["title"]}.',
            "ok": True, "args": args}

    raise ValueError(f"Unknown tool: {name}")


def suggest(dataset_id: str) -> list[str]:
    """Starter questions derived from the dataset's own shape."""
    ds = db.one("SELECT name FROM core.datasets WHERE id=%s", (dataset_id,))
    cols = db.query("SELECT name, semantic_type FROM core.dataset_columns WHERE dataset_id=%s "
                    "ORDER BY position", (dataset_id,))
    nums = [c["name"] for c in cols if c["semantic_type"] in ("integer", "numeric")]
    cats = [c["name"] for c in cols if c["semantic_type"] in ("categorical", "boolean")]
    dates = [c["name"] for c in cols if c["semantic_type"] == "datetime"]
    out = [f'Summarise {ds["name"] if ds else "this dataset"} in five bullet points.']
    if cats and nums:
        out.append(f"Which {cats[0]} has the highest total {nums[0]}? Chart the top 10.")
    if nums:
        out.append(f"Show the distribution of {nums[0]} and flag any outliers.")
    if dates and nums:
        out.append(f"How has {nums[0]} trended over {dates[0]}? Forecast the next 3 periods.")
    if len(nums) > 1:
        out.append(f"Is {nums[0]} correlated with {nums[1]}? Explain what drives it.")
    out.append("What data quality problems should I fix before trusting this dataset?")
    return out[:6]
