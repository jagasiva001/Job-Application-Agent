import os
from pathlib import Path

try:  # .env support (python-dotenv is in requirements.txt)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

APP_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(APP_DIR / "job_engine.db"))
DAILY_CAP = int(os.getenv("DAILY_CAP", "25"))
MIN_SCORE = float(os.getenv("MIN_MATCH_SCORE", "50"))
TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
MATCH_BACKEND = os.getenv("MATCH_BACKEND", "tfidf")  # tfidf | embeddings (optional, needs sentence-transformers)
APP_USER = os.getenv("APP_USER", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")  # empty = no login (localhost only!)
MAX_RESUME_BYTES = 5 * 1024 * 1024
PREFILL_ENABLED = os.getenv("PREFILL_ENABLED", "1") == "1"  # needs a visible browser on the machine running the app
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AGENT_MODEL = os.getenv("AGENT_MODEL", "gpt-5.5")
