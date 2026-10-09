import base64
import binascii
import secrets
from urllib.parse import urlsplit


def origin_ok(origin, host) -> bool:
    """Block cross-site POSTs: if the browser sends an Origin it must match our Host."""
    if not origin:
        return True
    return urlsplit(origin).netloc == (host or "")


def basic_auth_ok(header, user: str, password: str) -> bool:
    if not password:  # auth disabled
        return True
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        u, _, p = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return secrets.compare_digest(u.encode(), user.encode()) & secrets.compare_digest(p.encode(), password.encode())
