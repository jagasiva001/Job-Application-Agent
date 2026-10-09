"""Business logic. Every function takes an open sqlite connection so it can be tested without a web server."""
import csv
import io
import importlib.util
import json
import sqlite3
from pathlib import Path
from datetime import date

from . import config
from .db import now_utc
from .packet import build_packet
from .prefill import site_for
from .scoring import score_jobs
from .skills import extract_skills
from .textutil import clean_url, is_http_url, job_key

OPEN_STATUSES = ("NEW", "RESCORE", "LOW_MATCH", "AWAITING_APPROVAL")
APP_STATUSES = {"READY_TO_APPLY", "APPLIED", "INTERVIEW", "OFFER", "REJECTED_BY_COMPANY", "WITHDRAWN"}
EXPERIENCE = ("Fresher", "0-1 year", "1-3 years", "3+ years")
SPONSORSHIP = ("No", "Yes", "Open to either")
MAX_JOBS_PER_CALL = 500


def to_int(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else None


def _url_or_blank(v):
    v = (v or "").strip()
    return v if is_http_url(v) else ""


# ---------- profile ----------
def get_profile(conn) -> dict:
    r = conn.execute("SELECT * FROM profile WHERE id=1").fetchone()
    return dict(r) if r else {}


def save_profile(conn, d: dict) -> dict:
    resume = d.get("resume_text") or ""
    skills = (d.get("skills") or "").strip() or ", ".join(extract_skills(resume)[:15])
    row = {
        "full_name": d.get("full_name", ""), "email": d.get("email", ""), "phone": d.get("phone", ""),
        "resume_text": resume, "roles": d.get("roles", ""), "locations": d.get("locations", ""),
        "remote": int(d.get("remote") == "yes"), "hybrid": int(d.get("hybrid") == "yes"),
        "onsite": int(d.get("onsite") == "yes"),
        "experience": d.get("experience") if d.get("experience") in EXPERIENCE else "Fresher",
        "skills": skills, "salary_min": to_int(d.get("salary_min")), "salary_max": to_int(d.get("salary_max")),
        "notice_period": d.get("notice_period", ""), "visa": d.get("visa", ""),
        "sponsorship": d.get("sponsorship") if d.get("sponsorship") in SPONSORSHIP else "No",
        "daily_cap": max(1, min(int(d.get("daily_cap") or config.DAILY_CAP), 100)),
        "linkedin": _url_or_blank(d.get("linkedin")), "github": _url_or_blank(d.get("github")),
    }
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    updates = ", ".join(f"{k}=excluded.{k}" for k in row)
    conn.execute(f"INSERT INTO profile(id, {cols}) VALUES(1, {marks}) ON CONFLICT(id) DO UPDATE SET {updates}", row)
    if d.get("resume_file"):  # path of the saved upload; kept when later saves have no new file
        conn.execute("UPDATE profile SET resume_file=? WHERE id=1", (d["resume_file"],))
    rescored = rescore_open(conn)  # a changed profile re-evaluates every job that is still undecided
    return {"saved": True, "rescored": rescored}


def delete_profile(conn) -> dict:
    """Erase profile/resume data and cached personalized material, retaining job history."""
    profile = get_profile(conn)
    resume_path = profile.get("resume_file")
    if resume_path:
        upload_dir = (Path(config.DB_PATH).resolve().parent / "uploads").resolve()
        candidate = Path(resume_path).resolve()
        # Never unlink a path outside this app's fixed resume upload directory.
        if candidate.parent == upload_dir and candidate.name.startswith("resume."):
            candidate.unlink(missing_ok=True)

    conn.execute("DELETE FROM profile WHERE id=1")
    conn.execute("UPDATE applications SET packet=NULL")
    conn.execute("UPDATE jobs SET score=0, reasons='[]', gaps='[]'")
    conn.execute("UPDATE jobs SET status='NEW' "
                 "WHERE status IN ('NEW','RESCORE','LOW_MATCH','AWAITING_APPROVAL','APPROVED')")
    return {"deleted": True}


# ---------- jobs ----------
def ingest_jobs(conn, jobs: list) -> dict:
    added = duplicates = rejected = 0
    for j in jobs[:MAX_JOBS_PER_CALL]:
        url = (j.get("url") or "").strip()
        if not is_http_url(url) or not (j.get("title") or "").strip() or not (j.get("company") or "").strip():
            rejected += 1
            continue
        try:
            conn.execute(
                "INSERT INTO jobs(job_key,source,company,title,location,url,description,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (job_key(j["company"], j["title"], j.get("location", "")), j.get("source", "manual"),
                 j["company"].strip(), j["title"].strip(), (j.get("location") or "").strip(), clean_url(url),
                 (j.get("description") or "")[:20000], now_utc()))
            added += 1
        except sqlite3.IntegrityError:
            duplicates += 1
    return {"added": added, "duplicates": duplicates, "rejected": rejected}


def rescore_open(conn, min_score=None) -> int:
    min_score = config.MIN_SCORE if min_score is None else min_score
    profile = get_profile(conn)
    marks = ",".join("?" * len(OPEN_STATUSES))
    rows = conn.execute(f"SELECT id,title,company,location,description FROM jobs WHERE status IN ({marks})",
                        OPEN_STATUSES).fetchall()
    jobs = [dict(r) for r in rows]
    results = score_jobs(profile, jobs, config.MATCH_BACKEND)
    for j, res in zip(jobs, results):
        status = "AWAITING_APPROVAL" if res.score >= min_score else "LOW_MATCH"
        conn.execute("UPDATE jobs SET score=?, status=?, reasons=?, gaps=? WHERE id=?",
                     (res.score, status, json.dumps(res.reasons), json.dumps(res.gaps), j["id"]))
    return len(jobs)


def list_jobs(conn) -> list:
    rows = conn.execute("SELECT id,source,company,title,location,url,score,status,reasons,gaps "
                        "FROM jobs ORDER BY score DESC, id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["reasons"] = json.loads(d["reasons"] or "[]")
        d["gaps"] = json.loads(d["gaps"] or "[]")
        out.append(d)
    return out


def approve(conn, job_id: int) -> str:
    r = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        return "not_found"
    if r["status"] not in ("AWAITING_APPROVAL", "LOW_MATCH"):
        return "bad_state"
    conn.execute("UPDATE jobs SET status='APPROVED' WHERE id=?", (job_id,))
    return "ok"


def reject(conn, job_id: int) -> str:
    r = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        return "not_found"
    if r["status"] not in OPEN_STATUSES + ("APPROVED",):
        return "bad_state"
    conn.execute("UPDATE jobs SET status='REJECTED' WHERE id=?", (job_id,))
    return "ok"


# ---------- queue + tracker ----------
def queue_batch(conn, today: str) -> dict:
    """Turn approved jobs into READY_TO_APPLY packets, up to the daily cap. Nothing is submitted for you."""
    profile = get_profile(conn)
    cap = int(profile.get("daily_cap") or config.DAILY_CAP)
    used = conn.execute("SELECT COUNT(*) FROM applications WHERE queued_day=?", (today,)).fetchone()[0]
    remaining = max(0, cap - used)
    rows = conn.execute("SELECT * FROM jobs WHERE status='APPROVED' ORDER BY score DESC, id LIMIT ?",
                        (remaining,)).fetchall()
    for r in rows:
        packet = json.dumps(build_packet(profile, dict(r)))
        conn.execute(
            "INSERT INTO applications(job_id,status,queued_at,queued_day,packet) VALUES(?,?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, queued_at=excluded.queued_at, "
            "queued_day=excluded.queued_day, packet=excluded.packet",
            (r["id"], "READY_TO_APPLY", now_utc(), today, packet))
        conn.execute("UPDATE jobs SET status='READY_TO_APPLY' WHERE id=?", (r["id"],))
    return {"queued": len(rows), "remaining_daily_cap": remaining - len(rows)}


def set_application_status(conn, job_id: int, status: str, today: str, follow_up=None, notes=None) -> str:
    if status not in APP_STATUSES:
        return "bad_status"
    app = conn.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
    if not app:
        return "not_found"
    if follow_up:
        try:
            date.fromisoformat(follow_up)
        except ValueError:
            return "bad_date"
    applied_at, applied_day = app["applied_at"], app["applied_day"]
    if status == "APPLIED" and not applied_at:
        applied_at, applied_day = now_utc(), today
    conn.execute("UPDATE applications SET status=?, applied_at=?, applied_day=?, follow_up=COALESCE(?,follow_up), "
                 "notes=COALESCE(?,notes) WHERE job_id=?",
                 (status, applied_at, applied_day, follow_up or None, notes, job_id))
    conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
    return "ok"


def list_applications(conn) -> list:
    rows = conn.execute(
        "SELECT a.job_id, a.status, a.queued_at, a.applied_at, a.follow_up, a.notes, "
        "j.title, j.company, j.location, j.url, j.score "
        "FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["prefill"] = site_for(d["url"]) is not None  # Greenhouse / Lever pages only
        out.append(d)
    return out


def prefill_check(conn, job_id: int) -> str:
    r = conn.execute("SELECT status, url FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        return "not_found"
    if r["status"] != "READY_TO_APPLY":
        return "bad_state"
    if site_for(r["url"]) is None:
        return "unsupported_site"
    if not config.PREFILL_ENABLED:
        return "disabled"
    if importlib.util.find_spec("playwright") is None:
        return "missing_dependency"
    return "ok"


def get_packet(conn, job_id: int):
    r = conn.execute("SELECT packet FROM applications WHERE job_id=?", (job_id,)).fetchone()
    return json.loads(r["packet"]) if r and r["packet"] else None


def report(conn, today: str) -> dict:
    cap = int(get_profile(conn).get("daily_cap") or config.DAILY_CAP)
    queued = conn.execute("SELECT COUNT(*) FROM applications WHERE queued_day=?", (today,)).fetchone()[0]
    applied = conn.execute("SELECT COUNT(*) FROM applications WHERE applied_day=?", (today,)).fetchone()[0]
    return {"queued_today": queued, "applied_today": applied, "daily_cap": cap, "remaining": max(0, cap - queued)}


def _safe_cell(v):
    """Job text is untrusted; stop spreadsheet formula injection in the CSV export."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_csv(conn) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["title", "company", "location", "url", "score", "status", "queued_at", "applied_at", "follow_up", "notes"])
    for a in list_applications(conn):
        w.writerow([_safe_cell(a[k]) for k in
                    ("title", "company", "location", "url", "score", "status", "queued_at", "applied_at", "follow_up", "notes")])
    return buf.getvalue()
