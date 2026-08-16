import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PG_HOST = os.getenv("PGHOST", "localhost")
PG_PORT = os.getenv("PGPORT", "5432")
PG_DB = os.getenv("PGDATABASE", "insightforge")
PG_USER = os.getenv("PGUSER", os.getenv("USER", "postgres"))
PG_PASSWORD = os.getenv("PGPASSWORD", "")

DSN = os.getenv("DATABASE_URL") or (
    f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    if PG_PASSWORD
    else f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DB}"
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant").strip()
# Optional: point the client at any OpenAI-compatible endpoint instead of Groq.
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "").strip()

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_ROWS = int(os.getenv("MAX_ROWS", "200000"))
SQL_ROW_LIMIT = int(os.getenv("SQL_ROW_LIMIT", "500"))
SQL_TIMEOUT_MS = int(os.getenv("SQL_TIMEOUT_MS", "15000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
