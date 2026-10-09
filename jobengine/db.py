import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS profile(
    id INTEGER PRIMARY KEY CHECK(id=1),
    full_name TEXT, email TEXT, phone TEXT, resume_text TEXT,
    roles TEXT, locations TEXT, remote INTEGER DEFAULT 1,
    hybrid INTEGER DEFAULT 1, onsite INTEGER DEFAULT 1,
    experience TEXT, skills TEXT, salary_min INTEGER, salary_max INTEGER,
    notice_period TEXT, visa TEXT, sponsorship TEXT,
    daily_cap INTEGER DEFAULT 25, auto_apply INTEGER DEFAULT 0,
    linkedin TEXT, github TEXT, resume_file TEXT
);
CREATE TABLE IF NOT EXISTS jobs(
    id INTEGER PRIMARY KEY, job_key TEXT UNIQUE, source TEXT, company TEXT,
    title TEXT, location TEXT, url TEXT, description TEXT,
    score REAL DEFAULT 0, status TEXT DEFAULT 'NEW',
    reasons TEXT DEFAULT '[]', gaps TEXT DEFAULT '[]', created_at TEXT
);
CREATE TABLE IF NOT EXISTS applications(
    id INTEGER PRIMARY KEY, job_id INTEGER UNIQUE, status TEXT,
    submitted_at TEXT, confirmation TEXT, error TEXT,
    queued_at TEXT, queued_day TEXT, applied_at TEXT, applied_day TEXT,
    follow_up TEXT, notes TEXT, packet TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

# columns added after v3: added to existing databases on startup
V4_COLUMNS = {
    "profile": {"linkedin": "TEXT", "github": "TEXT", "resume_file": "TEXT"},
    "jobs": {"gaps": "TEXT DEFAULT '[]'", "created_at": "TEXT"},
    "applications": {"queued_at": "TEXT", "queued_day": "TEXT", "applied_at": "TEXT",
                     "applied_day": "TEXT", "follow_up": "TEXT", "notes": "TEXT", "packet": "TEXT"},
}


@contextmanager
def connect(path=None):
    # FastAPI may create a sync dependency in its worker thread and then pass
    # the connection to an async endpoint running on the event-loop thread.
    # The profile endpoint is async because it can parse an uploaded resume.
    conn = sqlite3.connect(path or config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()  # v3 leaked connections; this always closes


def init_db(path=None):
    with connect(path) as c:
        c.executescript(CREATE_SQL)
        for table, cols in V4_COLUMNS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols.items():
                if name not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        if c.execute("PRAGMA user_version").fetchone()[0] < 4:
            # v3 marked approved jobs REQUIRES_BROWSER without applying; put them back in the approved queue
            c.execute("UPDATE jobs SET status='APPROVED' WHERE status='REQUIRES_BROWSER'")
            c.execute("DELETE FROM applications WHERE status='REQUIRES_BROWSER'")
            c.execute("PRAGMA user_version=4")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_day() -> str:
    """Today's date in APP_TIMEZONE (falls back to UTC if the tz database is missing)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(config.TIMEZONE)).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()
