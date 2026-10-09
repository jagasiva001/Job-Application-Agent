import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DROP_PARAMS = {"gclid", "fbclid", "ref", "refid", "trk", "trkid", "gh_src", "lever-source", "lever-origin"}
_STOP = set("a an and are as at be by for from has have in is it its of on or that the this to was we will with you your our their they not but can".split())


def is_http_url(url: str) -> bool:
    try:
        p = urlsplit((url or "").strip())
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def clean_url(url: str) -> str:
    """Lower-case host, drop fragment and tracking parameters."""
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not (k.lower().startswith("utm_") or k.lower() in _DROP_PARAMS)]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(q), ""))


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def job_key(company: str, title: str, location: str) -> str:
    """Same job from two boards (or with tracking params) gets the same key."""
    raw = "|".join(norm(x) for x in (company, title, location))
    return hashlib.sha256(raw.encode()).hexdigest()


def has_term(text: str, term: str) -> bool:
    """Whole-word match on lower-cased text ('ai' does not match 'maintain')."""
    term = (term or "").strip().lower()
    if not term:
        return False
    return re.search(r"(?<![a-z0-9+#])" + re.escape(term) + r"(?![a-z0-9+#])", text) is not None


def tokens(text: str) -> list:
    return [w for w in re.findall(r"[a-z0-9+#]+", (text or "").lower()) if len(w) > 1 and w not in _STOP]
