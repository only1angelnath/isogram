"""
social_links.py - turn self-reported / curated social values into links that are safe to render.

Why this module exists: token deployers register their own website, X, Telegram and Discord links with
GeckoTerminal, and the dashboard is public. A hostile deployer could register a phishing site, a
`javascript:` URL, or a lookalike host. Nothing reaches the browser unless it passes these rules:

  - website : https only; no credentials in the URL; no custom port; a real DNS name with a TLD made only of
              a-z, 0-9 and hyphens (so no IP addresses, no `localhost`, no non-ASCII lookalike hosts;
              internationalised names must arrive as punycode `xn--...`); path/query kept, fragment dropped.
  - X / Telegram / Discord / GitHub : rebuilt from a validated handle or invite code on the platform's
              own host (x.com, t.me, discord.gg, github.com); anything else is dropped, so a "twitter" value
              can never point at another site.

Curated links (projects.socials, set by hand for seeded projects) win over self-reported ones, and every
link says which it is so the UI can label self-reported links as unverified.
"""

import re
from typing import Optional
from urllib.parse import urlsplit

MAX_URL = 200
_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f\s\\<>\"'`]")
_HOST = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_TG_HANDLE = re.compile(r"^[A-Za-z0-9_]{4,32}$")
_DISCORD_CODE = re.compile(r"^[A-Za-z0-9-]{2,32}$")
_GH_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_GH_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_X_RESERVED = {"intent", "share", "i", "home", "search", "hashtag", "explore", "login", "settings", "messages"}
_TG_RESERVED = {"joinchat", "share", "addstickers", "s", "proxy", "socks", "setlanguage"}
_X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
_TG_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me", "telegram.dog"}
_DISCORD_HOSTS = {"discord.gg", "www.discord.gg", "discord.com", "www.discord.com"}
_GH_HOSTS = {"github.com", "www.github.com"}


def _clean(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v if v and len(v) <= MAX_URL and not _BAD_CHARS.search(v) else None


def _https(value: str):
    """SplitResult for a well-formed https URL without credentials or a non-default port, else None."""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.netloc or "@" in parts.netloc or port not in (None, 443):
        return None
    return parts


def website(value) -> Optional[str]:
    v = _clean(value)
    parts = _https(v) if v else None
    host = (parts.hostname or "").lower() if parts else ""
    if not parts or not _HOST.match(host):
        return None
    path = parts.path if parts.path not in ("", "/") else ""
    url = f"https://{host}{path}" + (f"?{parts.query}" if parts.query else "")
    return url if len(url) <= MAX_URL else None


def _path_segments(value: str, hosts: set) -> Optional[list]:
    """Path segments of a platform URL on one of `hosts` (https only); None if it is not such a URL."""
    parts = _https(value)
    if not parts or (parts.hostname or "").lower() not in hosts:
        return None
    return [s for s in parts.path.split("/") if s]


def x_url(value) -> Optional[str]:
    v = _clean(value)
    if not v:
        return None
    if "/" in v or v.lower().startswith("http"):
        segs = _path_segments(v, _X_HOSTS)
        v = segs[0] if segs else ""
    v = v[1:] if v.startswith("@") else v
    return f"https://x.com/{v}" if _X_HANDLE.match(v) and v.lower() not in _X_RESERVED else None


def telegram_url(value) -> Optional[str]:
    v = _clean(value)
    if not v:
        return None
    if "/" in v or v.lower().startswith("http"):
        segs = _path_segments(v, _TG_HOSTS)
        v = segs[0] if segs else ""
    v = v[1:] if v.startswith("@") else v
    return f"https://t.me/{v}" if _TG_HANDLE.match(v) and v.lower() not in _TG_RESERVED else None


def discord_url(value) -> Optional[str]:
    v = _clean(value)
    segs = _path_segments(v, _DISCORD_HOSTS) if v else None
    if not segs:
        return None
    parts = urlsplit(v)
    host = (parts.hostname or "").lower()
    code = segs[0] if host.endswith("discord.gg") and len(segs) == 1 else (segs[1] if len(segs) == 2 and segs[0] == "invite" else None)
    return f"https://discord.gg/{code}" if code and _DISCORD_CODE.match(code) else None


def github_url(value) -> Optional[str]:
    v = _clean(value)
    segs = _path_segments(v, _GH_HOSTS) if v else None
    if not segs or len(segs) > 2 or not _GH_OWNER.match(segs[0]) or (len(segs) == 2 and not _GH_REPO.match(segs[1])):
        return None
    return "https://github.com/" + "/".join(segs)


_RULES = (
    ("website", website, ("website",), ("website",)),
    ("x", x_url, ("twitter", "x"), ("twitter",)),
    ("telegram", telegram_url, ("telegram",), ("telegram",)),
    ("discord", discord_url, ("discord",), ("discord",)),
    ("github", github_url, ("github",), ()),
)


def build_socials(curated: Optional[dict], reported: Optional[dict]) -> list:
    """[{kind, url, curated}] in a fixed order. For each kind the curated value wins if it validates;
    otherwise the self-reported one is used if it validates. Invalid values are dropped, never repaired."""
    curated = curated if isinstance(curated, dict) else {}
    reported = reported if isinstance(reported, dict) else {}
    out = []
    for kind, check, curated_keys, reported_keys in _RULES:
        url = next((u for u in (check(curated.get(k)) for k in curated_keys) if u), None)
        is_curated = url is not None
        if url is None:
            url = next((u for u in (check(reported.get(k)) for k in reported_keys) if u), None)
        if url:
            out.append({"kind": kind, "url": url, "curated": is_curated})
    return out
