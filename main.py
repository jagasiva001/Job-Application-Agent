import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from jobengine import agent, config, connectors, db, prefill, resume, security, service, ui

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jobengine")


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    if not config.APP_PASSWORD:
        log.warning("APP_PASSWORD is not set: anyone who can reach this server can read your profile. Keep it on localhost.")
    yield


def require_auth(request: Request):
    if not security.basic_auth_ok(request.headers.get("authorization"), config.APP_USER, config.APP_PASSWORD):
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": 'Basic realm="job-engine"'})


app = FastAPI(title="Agentic Job Application Engine", version="4.2.0", lifespan=lifespan,
              dependencies=[Depends(require_auth)])


@app.middleware("http")
async def block_cross_site_posts(request: Request, call_next):
    if request.method == "POST" and not security.origin_ok(request.headers.get("origin"), request.headers.get("host")):
        return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    return await call_next(request)


def get_conn():
    with db.connect() as conn:
        yield conn


class JobIn(BaseModel):
    source: str = "manual"
    url: str
    company: str
    title: str
    location: str = ""
    description: str = ""


class FetchIn(BaseModel):
    kind: str
    token: str


class StatusIn(BaseModel):
    status: str
    follow_up: Optional[str] = None
    notes: Optional[str] = None


def _check(code: str):
    errors = {"not_found": (404, "Not found"), "bad_state": (409, "Not allowed in the job's current status"),
              "bad_status": (400, "Unknown status"), "bad_date": (400, "follow_up must be YYYY-MM-DD"),
              "unsupported_site": (400, "Pre-fill supports Greenhouse and Lever pages only. Use Open job instead."),
              "disabled": (400, "Pre-fill is disabled here (PREFILL_ENABLED=0). Run the app on your own computer to use it."),
              "missing_dependency": (400, "Install it first: pip install -r requirements-prefill.txt && python -m playwright install chromium")}
    if code != "ok":
        status, msg = errors[code]
        raise HTTPException(status, msg)


@app.get("/health")
def health():
    return {"status": "ok", "match_backend": config.MATCH_BACKEND}


@app.get("/", response_class=HTMLResponse)
def home(conn=Depends(get_conn)):
    return ui.render_home(service.get_profile(conn))


@app.post("/profile")
async def save_profile(
    full_name: str = Form(""), email: str = Form(""), phone: str = Form(""),
    roles: str = Form(""), locations: str = Form(""), remote: str = Form("no"),
    hybrid: str = Form("no"), onsite: str = Form("no"), experience: str = Form("Fresher"),
    skills: str = Form(""), salary_min: str = Form(""), salary_max: str = Form(""),
    notice_period: str = Form(""), visa: str = Form(""), sponsorship: str = Form("No"),
    daily_cap: int = Form(25), resume_text: str = Form(""),
    linkedin: str = Form(""), github: str = Form(""),
    resume_file: Optional[UploadFile] = File(None, alias="resume"),
    conn=Depends(get_conn),
):
    saved_file = None
    if resume_file is not None and resume_file.filename:
        data = await resume_file.read()
        if len(data) > config.MAX_RESUME_BYTES:
            raise HTTPException(413, "Resume file is larger than 5 MB")
        try:
            resume_text = resume.extract_text(resume_file.filename, data)
            saved_file = resume.save_original(data, resume_file.filename)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception:
            log.exception("resume parsing failed")
            raise HTTPException(400, "Could not read that file. Paste the text instead.")
    service.save_profile(conn, dict(
        full_name=full_name, email=email, phone=phone, roles=roles, locations=locations, remote=remote,
        hybrid=hybrid, onsite=onsite, experience=experience, skills=skills, salary_min=salary_min,
        salary_max=salary_max, notice_period=notice_period, visa=visa, sponsorship=sponsorship,
        daily_cap=daily_cap, resume_text=resume_text,
        linkedin=linkedin, github=github, resume_file=saved_file))
    return RedirectResponse("/", status_code=303)


@app.post("/profile/delete")
def delete_profile(conn=Depends(get_conn)):
    return service.delete_profile(conn)


@app.get("/api/profile")
def api_profile(conn=Depends(get_conn)):
    p = service.get_profile(conn)
    p["resume_chars"] = len(p.pop("resume_text", "") or "")  # never echo the full resume over the API
    return p


@app.post("/jobs")
def ingest(jobs: list[JobIn], conn=Depends(get_conn)):
    result = service.ingest_jobs(conn, [j.model_dump() for j in jobs])
    service.rescore_open(conn)
    return result


@app.post("/connectors/fetch")
def fetch_board(body: FetchIn, conn=Depends(get_conn)):
    try:
        jobs = connectors.fetch(body.kind, body.token)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.warning("connector failed: %s", e)
        raise HTTPException(502, "Could not fetch that board. Check the name and try again.")
    result = service.ingest_jobs(conn, jobs)
    service.rescore_open(conn)
    return {**result, "fetched": len(jobs)}


@app.post("/score")
def score_all(conn=Depends(get_conn)):
    return {"rescored": service.rescore_open(conn), "minimum_score": config.MIN_SCORE}


@app.get("/api/jobs")
def api_jobs(conn=Depends(get_conn)):
    return service.list_jobs(conn)


@app.post("/jobs/{job_id}/approve")
def approve_job(job_id: int, conn=Depends(get_conn)):
    _check(service.approve(conn, job_id))
    return {"job_id": job_id, "status": "APPROVED"}


@app.post("/jobs/{job_id}/reject")
def reject_job(job_id: int, conn=Depends(get_conn)):
    _check(service.reject(conn, job_id))
    return {"job_id": job_id, "status": "REJECTED"}


@app.post("/run-batch")
def run_batch(conn=Depends(get_conn)):
    return service.queue_batch(conn, db.local_day())


@app.post("/jobs/{job_id}/prefill")
def prefill_job(job_id: int, conn=Depends(get_conn)):
    _check(service.prefill_check(conn, job_id))
    prefill.launch_detached(job_id)
    return {"started": True, "note": "A browser window is opening on the computer running this app. "
                                     "Review everything and click Submit yourself."}


@app.get("/applications")
def applications(conn=Depends(get_conn)):
    return service.list_applications(conn)


@app.post("/applications/{job_id}/status")
def application_status(job_id: int, body: StatusIn, conn=Depends(get_conn)):
    _check(service.set_application_status(conn, job_id, body.status, db.local_day(), body.follow_up, body.notes))
    return {"job_id": job_id, "status": body.status}


@app.get("/jobs/{job_id}/packet")
def job_packet(job_id: int, conn=Depends(get_conn)):
    packet = service.get_packet(conn, job_id)
    if packet is None:
        raise HTTPException(404, "No packet yet. Approve the job and click Prepare approved.")
    return packet


@app.post("/jobs/{job_id}/agent-review")
def agent_review(job_id: int, conn=Depends(get_conn)):
    try:
        return {"job_id": job_id, "review": agent.review_job(conn, job_id)}
    except LookupError:
        raise HTTPException(404, "Job not found")
    except agent.AgentUnavailable as e:
        raise HTTPException(503, str(e))
    except agent.AgentProviderError as e:
        raise HTTPException(502, str(e))


@app.get("/report")
def report(conn=Depends(get_conn)):
    return service.report(conn, db.local_day())


@app.get("/export.csv")
def export(conn=Depends(get_conn)):
    return PlainTextResponse(service.export_csv(conn), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=applications.csv"})
