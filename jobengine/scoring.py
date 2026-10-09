"""Explainable job scoring: skills (30) + role (20) + resume similarity (20) + location/mode (15) + experience (15)."""
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .skills import canon, extract_skills
from .textutil import has_term, tokens

log = logging.getLogger(__name__)

EXP_RANGE = {"fresher": (0, 1), "0-1 year": (0, 1), "1-3 years": (1, 3), "3+ years": (3, 99)}
ENTRY = ("fresher", "freshers", "intern", "internship", "entry level", "entry-level", "trainee",
         "graduate", "junior", "0-1 year", "0 to 1 year")
NO_SPONSOR = ("no sponsorship", "unable to sponsor", "cannot sponsor", "will not sponsor",
              "not sponsor", "without sponsorship", "do not provide sponsorship", "sponsorship is not available")
ONSITE = ("on-site", "onsite", "on site", "work from office", "in-office", "in office")


@dataclass
class Result:
    score: float
    reasons: list = field(default_factory=list)
    gaps: list = field(default_factory=list)


def _csv(s):
    return [x.strip().lower() for x in (s or "").split(",") if x.strip()]


def required_years(text: str):
    """Smallest 'N years' figure that sits next to the word 'experience'; None if absent."""
    t = text.lower()
    found = []
    for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:(?:-|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)", t):
        window = t[max(0, m.start() - 60): m.end() + 60]
        if "experience" in window:
            found.append(int(m.group(1)))
    return min(found) if found else None


def detect_modes(text: str) -> set:
    modes = set()
    if has_term(text, "remote") or has_term(text, "work from home") or has_term(text, "wfh"):
        modes.add("remote")
    if has_term(text, "hybrid"):
        modes.add("hybrid")
    if any(has_term(text, x) for x in ONSITE):
        modes.add("onsite")
    return modes


# ---------- similarity backends ----------
def _tfidf_sims(doc: str, texts: list) -> list:
    corpus = [tokens(doc)] + [tokens(t) for t in texts]
    n = len(corpus)
    df = Counter()
    for toks in corpus:
        df.update(set(toks))
    idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}
    vecs = []
    for toks in corpus:
        v = {w: (1 + math.log(c)) * idf[w] for w, c in Counter(toks).items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norm for w, x in v.items()})
    base = vecs[0]
    return [sum(x * base.get(w, 0.0) for w, x in v.items()) for v in vecs[1:]]


_model = None


def _embedding_sims(doc: str, texts: list) -> list:
    global _model
    from sentence_transformers import SentenceTransformer  # optional dependency
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    vecs = _model.encode([doc] + texts, normalize_embeddings=True)
    return [float(vecs[0] @ v) for v in vecs[1:]]


def similarities(doc: str, texts: list, backend: str = "tfidf") -> list:
    if not texts or not doc.strip():
        return [0.0] * len(texts)
    if backend == "embeddings":
        try:
            return _embedding_sims(doc, texts)
        except Exception as e:  # missing package, no model download, etc.
            log.warning("embeddings backend unavailable (%s); falling back to tfidf", e)
    return _tfidf_sims(doc, texts)


# ---------- scoring ----------
def score_jobs(profile: dict, jobs: list, backend: str = "tfidf") -> list:
    wanted, roles, locs = _csv(profile.get("skills")), _csv(profile.get("roles")), _csv(profile.get("locations"))
    resume = profile.get("resume_text") or ""
    doc = resume or " ".join(wanted)
    sims = similarities(doc, [f"{j['title']} {j['title']} {j.get('description') or ''}" for j in jobs], backend)
    have = {canon(w) for w in wanted} | set(extract_skills(resume))
    allowed = {m for m, k in (("remote", "remote"), ("hybrid", "hybrid"), ("onsite", "onsite")) if profile.get(k, 1)}
    user_max = EXP_RANGE.get((profile.get("experience") or "fresher").lower(), (0, 1))[1]
    return [_score_one(j, s, wanted, roles, locs, have, allowed, user_max, profile.get("sponsorship"))
            for j, s in zip(jobs, sims)]


def _score_one(j, sim, wanted, roles, locs, have, allowed, user_max, sponsorship) -> Result:
    title = (j["title"] or "").lower()
    text = f"{j['title']} {j.get('description') or ''} {j.get('location') or ''}".lower()
    reasons = []
    job_skills = extract_skills(text)

    # skills (30)
    hits = [w for w in wanted if has_term(text, w) or canon(w) in job_skills]
    skill = 30 * min(1.0, len(hits) / max(1, min(len(wanted), 10))) if wanted else 0
    if hits:
        reasons.append(f"Matches {len(hits)} of your skills: {', '.join(hits[:5])}")

    # role (20): title match counts fully, description match half; no roles set = no points
    if any(has_term(title, r) for r in roles):
        role = 20
        reasons.append("Role matches a target role in the title")
    elif any(has_term(text, r) for r in roles):
        role = 10
        reasons.append("Target role mentioned in the description")
    else:
        role = 0

    # resume similarity (20)
    semantic = min(20.0, sim / 0.25 * 20)
    if sim >= 0.1:
        reasons.append(f"Resume similarity {sim:.2f}")

    # location / work mode (15)
    modes = detect_modes(text)
    loc_ok = any(has_term(text, x) for x in locs)
    if modes and not (modes & allowed):
        loc = 0
        reasons.append("Warning: work mode not in your preferences")
    elif "remote" in modes and "remote" in allowed:
        loc = 15
        reasons.append("Remote role")
    elif loc_ok:
        loc = 15
        reasons.append("Location matches")
    elif modes:
        loc = 5
    else:
        loc = 0

    # experience (15)
    req = required_years(text)
    entry = any(has_term(text, x) for x in ENTRY)
    capped = None
    if req is None:
        exp = 15 if (entry and user_max <= 1) else 7
        if entry and user_max <= 1:
            reasons.append("Entry-level friendly")
    elif req <= user_max:
        exp = 15
        reasons.append(f"Experience requirement ({req}+ yrs) fits")
    elif req <= user_max + 1:
        exp = 7
        reasons.append(f"Warning: asks for {req}+ years of experience")
    else:
        exp = 0
        capped = 40
        reasons.append(f"Warning: asks for {req}+ years of experience")

    total = skill + role + semantic + loc + exp
    if capped is not None:
        total = min(total, capped)
    if sponsorship == "Yes" and any(p in text for p in NO_SPONSOR):
        total = min(total, 30)
        reasons.append("Warning: job does not offer visa sponsorship")

    gaps = [s for s in job_skills if s not in have][:6]
    return Result(round(total, 1), reasons, gaps)
