"""
Social links are the one place attacker-controlled text (a token deployer's registrations) reaches a public
page, so these tests are adversarial: every value that is not a clean https link / known-host handle must
be dropped, and nothing may be 'repaired' into a different destination.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import social_links as so
from db import get_client
from main import app


# ------------------------------------------------------------------ website

def test_websites_are_normalised_and_fragments_dropped():
    assert so.website("https://argus.world") == "https://argus.world"
    assert so.website("https://Foci.Family/path?a=1#frag") == "https://foci.family/path?a=1"
    assert so.website("https://a.example:443/") == "https://a.example"
    assert so.website("  https://argus.world/  ") == "https://argus.world"
    assert so.website("https://xn--80ak6aa92e.com") == "https://xn--80ak6aa92e.com"        # punycode is fine
    assert so.website("https://sub.domain.co.uk/x") == "https://sub.domain.co.uk/x"


@pytest.mark.parametrize("bad", [
    None, 123, "", "   ", "argus.world", "http://argus.world", "javascript:alert(1)", "JaVaScRiPt:alert(1)",
    "data:text/html,<script>alert(1)</script>", "//evil.com", "ftp://evil.com", "file:///etc/passwd",
    "https://user:pass@evil.com", "https://evil.com@good.com", "https://good.com\\@evil.com",
    "https://evil.com:8443", "https://localhost", "https://127.0.0.1", "https://192.168.0.1/x", "https://[::1]/",
    "https://nodot", "https://-bad.com", "https://bad-.com", "https://a..com",
    "https://аррӏе.com",                         # cyrillic lookalike host: not punycode, not ASCII
    "https://exa mple.com", "https://a.example/<script>", 'https://a.example/"onmouseover="x', "https://a.example/\nHost: x",
    "https://a.example/" + "x" * 200, "https://" + "a" * 70 + ".com",
])
def test_unsafe_or_malformed_websites_are_dropped(bad):
    assert so.website(bad) is None


# ------------------------------------------------------------------ platform handles

def test_x_handles_and_urls_become_x_com_links():
    for good in ("arguspad", "@arguspad", "https://x.com/arguspad", "https://twitter.com/arguspad/status/1", "https://www.x.com/arguspad?s=20"):
        assert so.x_url(good) == "https://x.com/arguspad"


@pytest.mark.parametrize("bad", ["", None, "intent", "https://x.com/intent/tweet", "a" * 16, "bad handle", "a-b", "a.b",
                                 "https://evil.com/arguspad", "http://x.com/arguspad", "https://x.com.evil.com/arguspad",
                                 "javascript:alert(1)", "https://x.com/", "@", "x.com/arguspad"])
def test_bad_x_values_are_dropped(bad):
    assert so.x_url(bad) is None


def test_telegram_and_discord_and_github_are_rebuilt_on_the_platforms_own_host():
    assert so.telegram_url("argus_chat") == so.telegram_url("@argus_chat") == so.telegram_url("https://t.me/argus_chat") == "https://t.me/argus_chat"
    assert so.discord_url("https://discord.gg/abc123") == "https://discord.gg/abc123"
    assert so.discord_url("https://discord.com/invite/abc-123") == "https://discord.gg/abc-123"
    assert so.github_url("https://github.com/foci-labs/repo.name") == "https://github.com/foci-labs/repo.name"
    assert so.github_url("https://github.com/foci-labs") == "https://github.com/foci-labs"
    for bad in ("abc", "joinchat", "https://t.me/joinchat/xyz", "https://evil.com/argus_chat", "a b", None):
        assert so.telegram_url(bad) is None
    for bad in ("discord.gg/abc", "https://discord.gg/a", "https://evil.com/invite/abc", "https://discord.gg/abc/def",
                "https://discord.com/other/abc", "http://discord.gg/abc", None):
        assert so.discord_url(bad) is None
    for bad in ("https://github.com/a/b/c", "https://gitlab.com/a", "https://github.com/", "https://github.com/-bad", "github.com/a", None):
        assert so.github_url(bad) is None


# ------------------------------------------------------------------ combining curated and self-reported

def test_curated_wins_and_is_flagged_and_self_reported_fills_the_gaps():
    out = so.build_socials({"website": "https://argus.world/"},
                           {"website": "https://phish.example", "twitter": "arguspad", "telegram": "argus_chat"})
    assert out == [
        {"kind": "website", "url": "https://argus.world", "curated": True},
        {"kind": "x", "url": "https://x.com/arguspad", "curated": False},
        {"kind": "telegram", "url": "https://t.me/argus_chat", "curated": False},
    ]


def test_an_invalid_curated_value_falls_back_to_a_valid_self_reported_one_and_junk_is_dropped():
    out = so.build_socials({"website": "javascript:alert(1)", "x": "@curated"},
                           {"website": "https://ok.example", "twitter": "ignored", "discord": "http://discord.gg/abc", "github": "https://github.com/a/b"})
    kinds = {o["kind"]: o for o in out}
    assert kinds["website"] == {"kind": "website", "url": "https://ok.example", "curated": False}
    assert kinds["x"] == {"kind": "x", "url": "https://x.com/curated", "curated": True}        # curated 'x' key is accepted
    assert "discord" not in kinds and "github" not in kinds                                      # github is curated-only


def test_nothing_in_nothing_out_and_odd_inputs_never_crash():
    assert so.build_socials(None, None) == [] and so.build_socials({}, {}) == []
    assert so.build_socials("junk", ["junk"]) == [] and so.build_socials({"website": 5}, {"twitter": {"a": 1}}) == []


def test_github_is_only_taken_from_curated_values():
    assert so.build_socials(None, {"github": "https://github.com/a/b"}) == []
    assert so.build_socials({"github": "https://github.com/a/b"}, None)[0]["kind"] == "github"


# ------------------------------------------------------------------ API integration

PROJECTS = [
    {"id": "tok", "name": "Tok", "category": "meme", "contracts": ["0xAAA"], "socials": {}},
    {"id": "pad", "name": "Pad", "category": "launchpad", "contracts": ["0xbbb"], "socials": {"website": "https://argus.world/"}},
    {"id": "dex", "name": "Dex", "category": "dex", "contracts": ["0xccc"], "socials": {}},
    {"id": "evil", "name": "Evil", "category": "token", "contracts": ["0xddd"], "socials": None},
]
ROWS = [
    {"contract_address": "0xaaa", "website": "https://tok.example", "twitter": "tok", "telegram": None, "discord": None},
    {"contract_address": "0xbbb", "website": "https://phish.example", "twitter": "pad", "telegram": None, "discord": None},
    {"contract_address": "0xccc", "website": "https://not-for-defi.example", "twitter": "x", "telegram": None, "discord": None},
    {"contract_address": "0xddd", "website": "javascript:alert(1)", "twitter": "https://evil.com/x", "telegram": "no", "discord": "<script>"},
]


@pytest.fixture(autouse=True)
def _dep():
    app.dependency_overrides[get_client] = lambda: "dummy"
    yield
    app.dependency_overrides.clear()


def _patch(monkeypatch, rows=None, boom=False):
    import routes.projects as pr
    monkeypatch.setattr(pr, "fetch_projects", lambda c: [dict(p, created_at=None, seeded=p["id"] == "pad") for p in PROJECTS])
    monkeypatch.setattr(pr, "fetch_project", lambda c, pid: next((dict(p, created_at=None, seeded=pid == "pad") for p in PROJECTS if p["id"] == pid), None))
    monkeypatch.setattr(pr, "fetch_all_latest_scores", lambda c: [])
    monkeypatch.setattr(pr, "fetch_latest_scores_for_project", lambda c, pid: [])
    monkeypatch.setattr(pr, "fetch_market_data", lambda c: [])
    monkeypatch.setattr(pr, "fetch_market_for_address", lambda c, a: None)
    monkeypatch.setattr(pr, "fetch_holders", lambda c: [])
    monkeypatch.setattr(pr, "fetch_holders_for_address", lambda c, a: None)
    def raising(*a, **k): raise RuntimeError("relation token_socials does not exist")
    monkeypatch.setattr(pr, "fetch_socials", raising if boom else (lambda c: list(rows or [])))
    monkeypatch.setattr(pr, "fetch_socials_for_address", raising if boom else (lambda c, a: next((r for r in (rows or []) if r["contract_address"] == a), None)))


def test_list_and_detail_return_validated_links_with_the_curated_flag(monkeypatch):
    _patch(monkeypatch, ROWS)
    c = TestClient(app)
    body = {p["id"]: p for p in c.get("/projects").json()}
    assert body["tok"]["socials"] == [{"kind": "website", "url": "https://tok.example", "curated": False},
                                      {"kind": "x", "url": "https://x.com/tok", "curated": False}]
    assert body["pad"]["socials"][0] == {"kind": "website", "url": "https://argus.world", "curated": True}   # curated beats the phishing site
    assert {"kind": "x", "url": "https://x.com/pad", "curated": False} in body["pad"]["socials"]
    assert body["dex"]["socials"] == []                          # self-reported links never apply to non-token projects
    assert body["evil"]["socials"] == []                         # every hostile value dropped
    assert c.get("/projects/tok").json()["socials"][0]["url"] == "https://tok.example"


def test_a_social_links_outage_does_not_break_projects_but_curated_links_still_show(monkeypatch):
    _patch(monkeypatch, boom=True)
    c = TestClient(app)
    r = c.get("/projects")
    assert r.status_code == 200
    body = {p["id"]: p for p in r.json()}
    assert body["tok"]["socials"] == [] and body["pad"]["socials"] == [{"kind": "website", "url": "https://argus.world", "curated": True}]
    assert c.get("/projects/tok").status_code == 200
