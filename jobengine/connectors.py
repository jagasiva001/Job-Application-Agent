"""Fetch jobs from public company job-board APIs (Greenhouse, Lever). Respect each site's terms."""
import html
import json
import re
import urllib.error
import urllib.request

UA = "AgenticJobEngine/4.0 (personal job search)"
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_DESC = 8000


def strip_html(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()[:MAX_DESC]


def parse_greenhouse(data: dict, board: str) -> list:
    out = []
    for j in (data or {}).get("jobs", []):
        out.append({"source": f"greenhouse:{board}", "company": board, "title": j.get("title", ""),
                    "location": (j.get("location") or {}).get("name", ""), "url": j.get("absolute_url", ""),
                    "description": strip_html(j.get("content", ""))})
    return out


def parse_lever(data: list, company: str) -> list:
    out = []
    for j in data or []:
        out.append({"source": f"lever:{company}", "company": company, "title": j.get("text", ""),
                    "location": (j.get("categories") or {}).get("location", ""), "url": j.get("hostedUrl", ""),
                    "description": (j.get("descriptionPlain") or strip_html(j.get("description", "")))[:MAX_DESC]})
    return out


def _get_json(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch(kind: str, token: str) -> list:
    if not _TOKEN.match(token or ""):
        raise ValueError("Invalid board name (letters, digits, - and _ only).")
    if kind == "greenhouse":
        return parse_greenhouse(_get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"), token)
    if kind == "lever":
        return parse_lever(_get_json(f"https://api.lever.co/v0/postings/{token}?mode=json"), token)
    raise ValueError("Unknown connector. Use 'greenhouse' or 'lever'.")
