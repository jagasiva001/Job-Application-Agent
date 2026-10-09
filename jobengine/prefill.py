"""Pre-fill Greenhouse and Lever application forms in a visible browser.

Safety rules (enforced in code and covered by tests):
  * only fill()/set_input_files() are used: nothing is ever clicked, selected or submitted;
  * only boards.greenhouse.io, job-boards.greenhouse.io and jobs.lever.co (exact host match);
  * the browser stays open so YOU review, answer custom questions, solve any CAPTCHA and press Submit.
Selectors are based on how these forms are commonly built; employers can customise them, so anything not
found is reported as "not filled" instead of guessed.
"""
import argparse
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import config, db
from .textutil import is_http_url

log = logging.getLogger("jobengine.prefill")

GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
LEVER_HOSTS = {"jobs.lever.co"}

SPECS = {
    "greenhouse": [
        ("first_name", [("css", "#first_name"), ("css", "input[name='first_name']"), ("label", r"first name")]),
        ("last_name", [("css", "#last_name"), ("css", "input[name='last_name']"), ("label", r"last name")]),
        ("email", [("css", "#email"), ("css", "input[type='email']"), ("label", r"^email")]),
        ("phone", [("css", "#phone"), ("css", "input[type='tel']"), ("label", r"phone")]),
        ("linkedin", [("label", r"linkedin")]),
        ("github", [("label", r"github")]),
    ],
    "lever": [
        ("full_name", [("css", "input[name='name']"), ("label", r"full name")]),
        ("email", [("css", "input[name='email']"), ("label", r"^email")]),
        ("phone", [("css", "input[name='phone']"), ("label", r"phone")]),
        ("linkedin", [("css", "input[name='urls[LinkedIn]']"), ("label", r"linkedin")]),
        ("github", [("css", "input[name='urls[GitHub]']"), ("label", r"github")]),
    ],
}
RESUME_CANDIDATES = [("css", "input[type='file'][id*='resume' i]"), ("css", "input[type='file'][name*='resume' i]"),
                     ("css", "input[type='file']")]
CAPTCHA_SELECTOR = ".g-recaptcha, .h-captcha, iframe[src*='captcha'], iframe[title*='captcha' i]"

BANNER_JS = """(text) => {
  const d = document.createElement('div'); d.id = 'job-engine-banner';
  d.style.cssText = 'position:fixed;z-index:2147483647;top:10px;right:10px;max-width:340px;background:#172033;color:#fff;' +
    'padding:12px;border-radius:10px;font:13px/1.4 Arial,sans-serif;white-space:pre-wrap;box-shadow:0 4px 18px rgba(0,0,0,.35)';
  d.textContent = text; (document.body || document.documentElement).appendChild(d);
}"""


def site_for(url: str):
    """'greenhouse', 'lever' or None. Exact hostname match, so lookalike hosts and user-info tricks fail."""
    if not is_http_url(url):
        return None
    host = (urlsplit(url.strip()).hostname or "").lower()
    if host in GREENHOUSE_HOSTS:
        return "greenhouse"
    if host in LEVER_HOSTS:
        return "lever"
    return None


def apply_url(url: str, site: str) -> str:
    p = urlsplit(url.strip())
    path = p.path.rstrip("/")
    if site == "lever" and not path.endswith("/apply"):
        path += "/apply"
    return urlunsplit((p.scheme, p.netloc, path or "/", p.query, ""))


def split_name(full: str):
    parts = (full or "").split()
    return (parts[0], " ".join(parts[1:])) if parts else ("", "")


def _locate(page, candidates):
    for kind, spec in candidates:
        loc = page.locator(spec) if kind == "css" else page.get_by_label(re.compile(spec, re.I))
        if loc.count() > 0:
            return loc.first
    return None


def fill_form(page, site: str, profile: dict) -> dict:
    first, last = split_name(profile.get("full_name", ""))
    values = {"first_name": first, "last_name": last, "full_name": (profile.get("full_name") or "").strip(),
              "email": profile.get("email") or "", "phone": profile.get("phone") or "",
              "linkedin": profile.get("linkedin") or "", "github": profile.get("github") or ""}
    report = {"site": site, "filled": [], "skipped": [], "captcha": False}
    for field, candidates in SPECS[site]:
        if not values.get(field):
            report["skipped"].append((field, "not in your profile"))
            continue
        loc = _locate(page, candidates)
        if loc is None:
            report["skipped"].append((field, "field not found on this page"))
            continue
        try:
            loc.fill(values[field], timeout=5000)
            report["filled"].append(field)
        except Exception as e:
            report["skipped"].append((field, f"could not fill ({type(e).__name__})"))

    path = profile.get("resume_file")
    if not path or not os.path.isfile(path):
        report["skipped"].append(("resume", "no resume file saved; upload one in your profile or attach it yourself"))
    else:
        loc = _locate(page, RESUME_CANDIDATES)
        if loc is None:
            report["skipped"].append(("resume", "upload field not found on this page"))
        else:
            try:
                loc.set_input_files(path, timeout=10000)
                report["filled"].append("resume")
            except Exception as e:
                report["skipped"].append(("resume", f"could not attach ({type(e).__name__})"))
    report["captcha"] = page.locator(CAPTCHA_SELECTOR).count() > 0
    return report


def format_report(report: dict) -> str:
    lines = ["Job Engine pre-fill (nothing was submitted)",
             "Filled: " + (", ".join(report["filled"]) or "nothing")]
    if report["skipped"]:
        lines.append("Not filled: " + "; ".join(f"{f} ({why})" for f, why in report["skipped"]))
    if report["captcha"]:
        lines.append("CAPTCHA detected: solve it yourself.")
    lines.append("Your turn: answer the custom questions, check work authorization, then click Submit yourself.")
    return "\n".join(lines)


def run(profile: dict, url: str, headless: bool = False, before_goto=None) -> dict:
    site = site_for(url)
    if not site:
        raise ValueError("Pre-fill supports Greenhouse and Lever application pages only.")
    from playwright.sync_api import sync_playwright  # optional dependency
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_context().new_page()
            if before_goto:
                before_goto(page)
            page.goto(apply_url(url, site), wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector("form", timeout=15000)
            except Exception:
                log.warning("no <form> found within 15s; filling what is there")
            report = fill_form(page, site, profile)
            page.evaluate(BANNER_JS, format_report(report))
            log.info("%s", format_report(report))
            if not headless:
                page.wait_for_event("close", timeout=0)  # stay open until you close the window
            return report
        finally:
            browser.close()


def launch_detached(job_id: int) -> None:
    """Start the browser in a separate process so the web server is not blocked. The profile is read from the
    database by the child, so personal details never appear on a command line."""
    log_file = open(Path(config.DB_PATH).resolve().parent / "prefill.log", "a")
    kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000200}
    subprocess.Popen([sys.executable, "-m", "jobengine.prefill", "--job-id", str(job_id)], cwd=config.APP_DIR,
                     env={**os.environ, "DB_PATH": config.DB_PATH}, stdout=log_file, stderr=subprocess.STDOUT, **kwargs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pre-fill an application form for a prepared job")
    ap.add_argument("--job-id", type=int, required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from . import service
    with db.connect() as conn:
        profile = service.get_profile(conn)
        row = conn.execute("SELECT url FROM jobs WHERE id=?", (args.job_id,)).fetchone()
    if not row:
        print("Job not found")
        return 1
    try:
        run(profile, row["url"])
    except ValueError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
