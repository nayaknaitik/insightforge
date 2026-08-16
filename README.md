# InsightForge

Give it raw data. It cleans the data, stores it in Postgres, shows you what it
changed, publishes the table to Power BI, turns the same data into a searchable
knowledge base, and then lets you ask questions about it in plain English.

Everything it uses is free: Postgres on your own machine, and Groq's free API for
the language model.

---

## The flow, in five steps

| Station | What happens | Where the code lives |
|---|---|---|
| 1. Ingest | You upload a file, paste text, or type rows into a grid. | `frontend/src/pages/Ingest.tsx` |
| 2. Transform | Headers are cleaned, blank rows and duplicates removed, column types worked out, bad cells set to NULL. | `backend/app/etl.py` |
| 3. Profile | Statistics per column: min, max, average, median, how much is missing, most common values. | `backend/app/etl.py` (`profile_table`) |
| 4. Index | The table is rewritten as searchable text: a dataset card, a schema card, one card per column, narrated batches of rows, and pre-computed insights. This is the RAG source. | `backend/app/rag.py` |
| 5. Ask | A Groq-hosted model answers questions using retrieval **plus** live SQL and statistics against your table. | `backend/app/assistant.py` |

"RAG" means retrieval-augmented generation: before the model answers, the system
searches your own data and pastes the most relevant parts into the prompt, so the
answer is grounded in your rows instead of the model's memory.

---

## Running it

```bash
cd ~/Desktop/insightforge
./start.sh
```

Then open <http://localhost:5177>.

`start.sh` checks Postgres, creates the `insightforge` database if it is missing,
installs dependencies on the first run, starts the API on port 8077 and the web
app on port 5177.

### Put your Groq key in

Open `backend/.env` and fill in one line:

```
GROQ_API_KEY=gsk_your_key_here
```

Get a free key at <https://console.groq.com/keys>. Restart the API after saving.
Everything except the "Ask" page works without a key.

The model is configurable:

```
GROQ_MODEL=llama-3.3-70b-versatile     # main model
GROQ_FALLBACK_MODEL=llama-3.1-8b-instant  # used automatically if the main one errors
```

### Running the pieces by hand

```bash
# API
cd backend && .venv/bin/uvicorn app.main:app --port 8077 --reload

# web app
cd frontend && npm run dev

# self-check on the risky logic (types, coercion, SQL guard)
cd backend && .venv/bin/python test_pipeline.py
```

---

## What lives where

```
insightforge/
├── backend/
│   ├── app/
│   │   ├── main.py        FastAPI routes (upload, datasets, chat, Power BI)
│   │   ├── etl.py         parse → clean → infer types → load → profile
│   │   ├── rag.py         builds and searches the knowledge base
│   │   ├── assistant.py   Groq tool-calling loop
│   │   ├── analysis.py    read-only SQL guard + named statistical analyses
│   │   ├── db.py          connection pool
│   │   └── config.py      environment settings
│   ├── schema.sql         control tables (created automatically on boot)
│   └── test_pipeline.py   runnable checks
├── frontend/src/
│   ├── pages/Ingest.tsx   station 1
│   ├── pages/Dataset.tsx  stations 2–4 + Power BI
│   ├── pages/Ask.tsx      station 5
│   ├── Chart.tsx          chart rendering
│   └── ui.tsx             shared pieces
├── sample-data/           a deliberately messy retail file to try
└── start.sh
```

### Database layout

Two schemas inside one Postgres database:

- `core` — the control plane: `datasets`, `dataset_columns`, `etl_runs`,
  `rag_chunks`, `conversations`, `messages`.
- `data` — one physical, properly typed table per dataset, named
  `ds_<your name>_<id>`. This is the table Power BI connects to.

---

## Connecting Power BI

Open a dataset, go to the **Power BI** tab. Four ways, in order of preference:

1. **PostgreSQL connector** — Home ▸ Get Data ▸ PostgreSQL database, then paste
   the server and database shown on that tab. Choose *Import* for speed or
   *DirectQuery* so the report always reflects the live table.
2. **`.pbids` file** — download it and double-click; Power BI Desktop opens
   straight onto this database.
3. **Web (JSON) feed** — Home ▸ Get Data ▸ Web, paste the feed URL. No database
   driver needed.
4. **CSV export** — for Excel, Sheets, or an offline copy.

---

## What the assistant can actually do

The model is not asked to guess numbers. It is given four tools and must use them:

- `search_data` — semantic search over your dataset's knowledge base.
- `run_sql` — one read-only `SELECT` against your table. Writes, DDL and
  dangerous functions are rejected before the query reaches Postgres, the
  transaction is read-only, and there is a statement timeout.
- `analyze` — named analyses: `describe`, `correlation`, `outliers`,
  `distribution`, `group_summary`, `trend` (with optional forecast).
- `make_chart` — turns the latest result into a chart the page renders.

Every answer shows the steps it took, the SQL it ran, the tables it produced and
the pieces of your data it read.

---

## API, if you want to use it directly

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Postgres and LLM status |
| `POST` | `/api/datasets/upload` | multipart file upload → runs the pipeline |
| `POST` | `/api/datasets/manual` | JSON body: `text`, or `columns` + `rows` |
| `GET` | `/api/datasets` | list datasets |
| `GET` | `/api/datasets/{id}` | dataset, columns, ETL runs, chunk counts |
| `GET` | `/api/datasets/{id}/preview` | paged rows |
| `POST` | `/api/datasets/{id}/query` | run read-only SQL |
| `POST` | `/api/datasets/{id}/analyze` | named analysis |
| `POST` | `/api/datasets/{id}/search` | retrieval test |
| `POST` | `/api/datasets/{id}/reindex` | rebuild the knowledge base |
| `POST` | `/api/chat` | ask a question |
| `GET` | `/api/powerbi/{id}/connection` | connection details |
| `GET` | `/api/powerbi/{id}/dataset.pbids` | Power BI launch file |
| `GET` | `/api/powerbi/{id}/feed` | JSON feed |
| `GET` | `/api/datasets/{id}/export.csv` | CSV export |

Interactive docs while the API is running: <http://127.0.0.1:8077/docs>.

---

## Deliberate limits

- Retrieval uses TF-IDF (word-frequency similarity) computed in memory, not
  vector embeddings. It needs no downloads and no paid API. If a dataset ever
  grows past roughly 50,000 chunks, switch to `pgvector` plus an embedding model.
- Uploads are capped at 50 MB and 200,000 rows; SQL results at 500 rows and a
  15-second timeout. All four numbers are in `backend/.env`.
- There are no user accounts. This is a local tool; anyone who can reach the API
  can read every dataset.
