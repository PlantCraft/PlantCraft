"""The site's chat without a real model: search, limits, the price guard, contacts and the page."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import build
from sitechat import chat
from sitechat.app import Settings, create_app
from sitechat.evaluation import check, load, retrieval_misses, run
from sitechat.guard import Window, has_price
from sitechat.knowledge import Knowledge, passages_of
from sitechat.llm import ModelError, make_model

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def knowledge() -> Knowledge:
    return Knowledge.from_repository(ROOT)


class FakeModel:
    """Answers with a fixed text and keeps what it was sent."""

    name = "fake"

    def __init__(self, text: str = "PlantCraft is open [2] and free [1].", fail: bool = False):
        self.text = text
        self.fail = fail
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system, messages, max_tokens):
        self.calls.append((system, messages))
        if self.fail:
            raise ModelError("down")
        return self.text


def client(tmp_path, knowledge, model=None, **kw) -> TestClient:
    settings = Settings(model=model, knowledge=knowledge, data_dir=tmp_path, **kw)
    return TestClient(create_app(settings))


# --- knowledge ----------------------------------------------------------------------------------


def test_every_listed_page_exists_and_is_cut(knowledge):
    assert len(knowledge.core) >= 5
    assert len(knowledge.searched) > 100
    assert all(len(p.text) <= 2800 for p in knowledge.searched)


def test_passages_follow_headings():
    md = "# Title\n\nIntro.\n\n## A\n\nText a.\n\n```bash\n# not a heading\n```\n\n### B\n\nText b."
    ps = passages_of("x.md", md)
    assert [(p.title, p.heading) for p in ps] == [("Title", ""), ("Title", "A"), ("Title", "A › B")]
    assert "# not a heading" in ps[1].text


def test_search_finds_the_page_that_answers_each_eval_question(knowledge):
    assert retrieval_misses(knowledge, load()) == []


def test_portuguese_words_reach_english_pages(knowledge):
    sources = {p.source for p in knowledge.search("requisitos de servidor e memória")}
    assert "docs/requirements.md" in sources


def test_knowledge_round_trips(tmp_path, knowledge):
    knowledge.dump(tmp_path / "k.json")
    again = Knowledge.load(tmp_path / "k.json")
    assert again.search("LDAP") == knowledge.search("LDAP")


# --- the answer ---------------------------------------------------------------------------------


def test_answer_cites_renumbered_sources(knowledge):
    model = FakeModel("Free [2], open [2][1]. Unknown [40].")
    a = chat.answer(model, knowledge, [{"role": "user", "content": "Is it free?"}], "https://x/b")
    assert a.text == "Free [1], open [1][2]. Unknown."
    assert [s.path for s in a.sources] == [knowledge.core[1].source, knowledge.core[0].source]
    assert all(s.url.startswith("https://x/b/") for s in a.sources)
    system = model.calls[0][0]
    assert "SOURCES" in system and "Never give a price" in system


def test_contact_mark_becomes_a_flag(knowledge):
    a = chat.answer(FakeModel("Talk to the team.\n[[CONTACT]]"), knowledge, _q("A pilot?"), "u")
    assert a.contact and "[[CONTACT]]" not in a.text


@pytest.mark.parametrize(
    "text", ["Use the contact form below.", "Fale com a equipe pelo formulário de contato."]
)
def test_sending_to_the_team_opens_the_form(knowledge, text):
    assert chat.answer(FakeModel(text), knowledge, _q("support?"), "u").contact


def test_plain_answer_does_not_open_the_form(knowledge):
    assert not chat.answer(FakeModel("It reads OPC UA [1]."), knowledge, _q("OPC?"), "u").contact


@pytest.mark.parametrize(
    "text",
    ["It is R$ 5.000 por mês", "about $5,000", "US$ 10k", "2000 dollars", "€300", "5 mil reais"],
)
def test_a_price_is_never_shown(knowledge, text):
    a = chat.answer(FakeModel(text), knowledge, _q("price?"), "u")
    assert not has_price(a.text) and a.contact and not a.grounded


def test_no_false_price_alarm():
    assert not has_price("8,000 signals on 4 vCPU and 16 GB, 21 ms p95, ISA-18.2, 443")


def test_model_failure_offers_contact(knowledge):
    a = chat.answer(FakeModel(fail=True), knowledge, _q("hi"), "u")
    assert a.contact and not a.grounded and a.failed


def test_a_model_that_fails_once_is_asked_again(knowledge):
    class Flaky(FakeModel):
        def complete(self, system, messages, max_tokens):
            self.fail = not self.calls
            return super().complete(system, messages, max_tokens)

    model = Flaky()
    a = chat.answer(model, knowledge, _q("What is PlantCraft?"), "u")
    assert len(model.calls) == 2 and not a.failed


def test_openai_reasoning_models_get_room_to_think():
    model = make_model("openai", "k")
    assert model.reasoning_effort == "low"
    assert make_model("openai", "k", name="gpt-4.1").reasoning_effort == ""


def test_eval_stops_when_the_model_stops_answering(knowledge):
    with pytest.raises(ModelError):
        run(FakeModel(fail=True), knowledge, load()[:5], "u")


def test_eval_checks():
    q = {"must": ["apache", "free|gratis"], "must_not": ["$"], "contact": True}
    assert check(q, chat.Answer("Apache, free", contact=True)) == []
    assert check(q, chat.Answer("Apache $5", contact=False)) == [
        "missing 'free|gratis'",
        "has '$'",
        "should offer the contact form",
    ]


def _q(text):
    return [{"role": "user", "content": text}]


# --- the server ---------------------------------------------------------------------------------


def test_off_without_a_model(tmp_path, knowledge):
    c = client(tmp_path, knowledge)
    assert c.get("/api/chat/status").json() == {"assistant": False}
    r = c.post("/api/chat", json={"messages": _q("What is it?")})
    assert r.json()["assistant"] is False and r.json()["contact"] is True


def test_no_key_means_off():
    assert make_model("openai", "") is None
    assert make_model("off", "k") is None
    assert make_model("anthropic", "k").name
    with pytest.raises(ValueError):
        make_model("other", "k")


def test_chat_answers_and_logs_the_question_without_address(tmp_path, knowledge):
    c = client(tmp_path, knowledge, FakeModel())
    r = c.post("/api/chat", json={"messages": _q("Is it free?")})
    body = r.json()
    assert r.status_code == 200 and body["assistant"] and body["sources"]
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    logged = [json.loads(x) for x in (tmp_path / "questions.jsonl").read_text().splitlines()]
    assert logged[0]["question"] == "Is it free?" and "address" not in logged[0]


def test_chat_input_limits(tmp_path, knowledge):
    c = client(tmp_path, knowledge, FakeModel())
    assert c.post("/api/chat", json={"messages": _q("x" * 1300)}).status_code == 422
    last_bot = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert c.post("/api/chat", json={"messages": last_bot}).status_code == 422
    assert (
        c.post("/api/chat", json={"messages": [{"role": "system", "content": "x"}]}).status_code
        == 422
    )
    big = {"messages": _q("y" * 70_000)}
    assert c.post("/api/chat", json=big).status_code == 413


def test_rate_limit_per_address(tmp_path, knowledge):
    c = client(tmp_path, knowledge, FakeModel())
    codes = [c.post("/api/chat", json={"messages": _q("free?")}).status_code for _ in range(10)]
    assert codes[:8] == [200] * 8 and codes[8] == 429


def test_daily_budget_for_the_whole_site(tmp_path, knowledge):
    c = client(tmp_path, knowledge, FakeModel(), daily_limit=2, trust_proxy=True)
    codes = [
        c.post(
            "/api/chat", json={"messages": _q("free?")}, headers={"X-Forwarded-For": f"10.0.0.{i}"}
        ).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


def test_rate_limit_per_visitor_behind_a_cloudflare_tunnel(tmp_path, knowledge):
    """Through the tunnel every request comes from one address: the visitor is CF-Connecting-IP."""

    c = client(tmp_path, knowledge, FakeModel(), trust_proxy="cloudflare")

    def ask(visitor):
        headers = {"CF-Connecting-IP": visitor, "X-Forwarded-For": "203.0.113.9"}
        return c.post("/api/chat", json={"messages": _q("free?")}, headers=headers).status_code

    assert [ask("198.51.100.1") for _ in range(9)][-1] == 429
    assert ask("198.51.100.2") == 200


def test_trust_proxy_setting():
    from sitechat.app import _trust_proxy

    assert _trust_proxy("Cloudflare") == "cloudflare"
    assert _trust_proxy("1") is True and _trust_proxy("0") is False


def test_window_forgets_old_events():
    w = Window(2, 60)
    assert w.allow("a", 0) and w.allow("a", 1) and not w.allow("a", 2)
    assert w.allow("a", 61)


def test_contact_is_kept_private_and_validated(tmp_path, knowledge):
    c = client(tmp_path, knowledge)
    ok = {"name": "Ana", "email": "ana@plant.example", "company": "Acme", "need": "A pilot"}
    assert c.post("/api/contact", json=ok).json() == {"ok": True}
    path = tmp_path / "contacts.jsonl"
    saved = json.loads(path.read_text())
    assert saved["email"] == "ana@plant.example" and "website" not in saved
    assert path.stat().st_mode & 0o777 == 0o600
    bad = c.post("/api/contact", json={**ok, "email": "not-an-email"})
    assert bad.status_code == 422 and bad.json()["fields"] == ["email"]


def test_contact_honeypot_and_limit(tmp_path, knowledge):
    c = client(tmp_path, knowledge)
    ok = {"name": "Ana", "email": "ana@plant.example", "need": "Hi"}
    assert c.post("/api/contact", json={**ok, "website": "spam"}).json() == {"ok": True}
    assert not (tmp_path / "contacts.jsonl").exists()
    codes = [c.post("/api/contact", json=ok).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


# --- the page -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dist(tmp_path_factory) -> Path:
    return build.build(tmp_path_factory.mktemp("site") / "dist", "PlantCraft", "b-1", draft=False)


def test_page_is_served_with_its_chat(tmp_path, knowledge, dist):
    c = client(tmp_path, knowledge, FakeModel(), dist=dist)
    page = c.get("/")
    assert page.status_code == 200 and "Talk to us" in page.text
    assert c.get("/assets/chat.js").status_code == 200
    assert (dist / "knowledge.json").exists()


def test_page_has_no_external_resource_inline_code_or_price(dist):
    html = (dist / "index.html").read_text()
    css = (dist / "assets/site.css").read_text()
    for tag in re.findall(r"<(?:script|link|img|source)\b[^>]*>", html):
        assert not re.search(r'(src|href|srcset)="(https?:)?//', tag), tag
    assert "<style" not in html and not re.search(r"<script>(?!</script>)", html)
    assert not re.search(r"\son\w+=", html), "no inline event handlers (CSP)"
    assert "url(http" not in css and "@import" not in css
    assert not has_price(html)
    for pillar in ("Open", "Secure", "LLM-first", "Fast"):
        assert f"<b>{pillar}</b>" in html


def test_privacy_robots_and_security_txt(dist):
    privacy = (dist / "privacy.html").read_text()
    assert "No cookies" in privacy and "%%" not in privacy
    assert 'href="privacy.html"' in (dist / "index.html").read_text()
    assert (dist / "robots.txt").read_text() == "User-agent: *\nAllow: /\n"
    security = (dist / ".well-known/security.txt").read_text()
    assert "Contact: https://github.com/PlantCraft/PlantCraft/security/advisories/new" in security
    assert "Expires: " in security
    assert "noindex" not in (dist / "index.html").read_text()
    assert "Try the live demo" not in (dist / "index.html").read_text()


def test_a_site_online_before_its_launch(tmp_path):
    out = build.build(
        tmp_path / "dist",
        "PlantCraft",
        "b-1",
        draft=False,
        demo_url="https://demo.plant.example/",
        contact="team@plant.example",
        noindex=True,
    )
    html = (out / "index.html").read_text()
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert 'href="https://demo.plant.example/">Try the live demo</a>' in html
    assert (out / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    assert "noindex" in (out / "privacy.html").read_text()
    assert "mailto:team@plant.example" in (out / "privacy.html").read_text()
    assert "Contact: mailto:team@plant.example" in (out / ".well-known/security.txt").read_text()


def test_stylesheets_and_scripts_carry_their_hash(tmp_path):
    html = (build.build(tmp_path / "dist", "PlantCraft", "b", False) / "index.html").read_text()
    assert re.search(r'href="assets/site\.css\?v=[0-9a-f]{10}"', html)
    assert re.search(r'src="assets/showcase\.js\?v=[0-9a-f]{10}"', html)
    assert re.search(r'data-mp4="assets/clips/desk\.mp4\?v=[0-9a-f]{10}"', html)
    assert re.search(r'data-poster="assets/clips/desk\.jpg\?v=[0-9a-f]{10}"', html)


# --- visits and the stats page ------------------------------------------------------------------

BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"}


def _stats(c, password="s3cret"):
    return c.get("/stats", auth=("owner", password))


def test_page_views_are_counted_without_address(tmp_path, knowledge):
    c = client(tmp_path, knowledge, trust_proxy="cloudflare")
    head = {**BROWSER, "CF-Connecting-IP": "203.0.113.7", "CF-IPCountry": "BR"}
    r = c.post(
        "/api/visit", json={"id": "abc123xyz", "page": "/", "ref": "www.google.com"}, headers=head
    )
    assert r.status_code == 204 and r.headers["cache-control"] == "no-store"
    c.post("/api/visit", json={"id": "abc123xyz"}, headers=head)
    # Bots and junk ids are not people.
    c.post(
        "/api/visit", json={"id": "bot12345", "page": "/"}, headers={"User-Agent": "Googlebot/2.1"}
    )
    c.post("/api/visit", json={"id": "<script>", "page": "/"}, headers=BROWSER)
    raw = (tmp_path / "visits.sqlite3").read_bytes()
    assert b"203.0.113.7" not in raw
    from sitechat.visits import Visits

    rows = Visits(tmp_path).since(0)
    assert len(rows) == 1 and rows[0]["country"] == "BR" and rows[0]["referrer"] == "www.google.com"


def test_one_visitor_a_day_and_their_time(tmp_path):
    from sitechat.visits import Visits

    v = Visits(tmp_path)
    v.hit("view1aaaa", address="a", agent="Firefox", page="/", now=1000)
    v.hit("view1aaaa", address="a", agent="Firefox", now=1090)
    v.hit("view2aaaa", address="a", agent="Firefox", page="/privacy.html", now=1100)
    v.hit("view2aaaa", address="a", agent="Firefox", now=1300)
    v.hit("view3aaaa", address="b", agent="Firefox", page="/", now=1200)
    # Not heard from for longer than GONE_SECONDS: closed, a late call does not stretch it.
    v.hit("view3aaaa", address="b", agent="Firefox", now=1200 + 3600)
    rows = v.since(0)
    assert len({r["visitor"] for r in rows}) == 2
    from zoneinfo import ZoneInfo

    from sitechat.stats import summary

    data = summary(rows, "off", [], [], ZoneInfo("UTC"), now=1300)
    assert data["online"] == 1
    today = data["days"][0]
    assert today["visitors"] == 2 and today["views"] == 3
    # Visitor a: 1000 to 1300; visitor b: one moment.
    assert today["site_time"] == "2 min 30 s (mean 2 min 30 s)"


def test_stats_page_needs_its_password(tmp_path, knowledge):
    assert client(tmp_path, knowledge).get("/stats").status_code == 404
    c = client(tmp_path, knowledge, stats_password="s3cret")
    r = c.get("/stats")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert _stats(c, "wrong").status_code == 401
    for _ in range(10):
        _stats(c, "wrong")
    assert _stats(c, "wrong").status_code == 429


def test_stats_page_shows_site_demo_chat_and_contacts(tmp_path, knowledge, monkeypatch):
    from sitechat import stats

    c = client(
        tmp_path,
        knowledge,
        FakeModel(),
        stats_password="s3cret",
        stats_timezone="America/Sao_Paulo",
    )
    c.post("/api/visit", json={"id": "abc123xyz", "page": "/"}, headers=BROWSER)
    click = {"id": "abc123xyz", "click": "Try the live demo → demo.plant.example/"}
    c.post("/api/visit", json=click, headers=BROWSER)
    c.post("/api/visit", json=click, headers=BROWSER)
    # A click of a page view never opened is not counted.
    c.post("/api/visit", json={**click, "id": "unknown99"}, headers=BROWSER)
    c.post("/api/chat", json={"messages": _q("Does it run offline?")})
    c.post(
        "/api/contact",
        json={"name": "Ana", "email": "ana@plant.example", "need": "A pilot <b>now</b>"},
    )
    import time as clock

    now = clock.time()
    monkeypatch.setattr(
        stats.DemoSource,
        "read",
        lambda self, days=31: {
            "now": {"taken": 3, "waiting": 1, "seats": 10},
            "visits": [{"started": now - 600, "seconds": 420, "waited": 30}],
            "pages": [{"page": "/link/loops/:id", "visits": 1}],
        },
    )
    r = _stats(c)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    page = r.text
    assert "reading the site now" in page and "<b>1</b>" in page
    assert "<b>3</b><span>in the demo now, of 10 places; 1 waiting" in page
    assert "Does it run offline?" in page and "Ana" in page
    assert "<b>now</b>" not in page, "what visitors wrote is escaped"
    assert "7 min 00 s" in page and "America/Sao_Paulo" in page
    assert "/link/loops/:id" in page
    assert "<td>Try the live demo → demo.plant.example/</td><td>1</td>" in page
    assert "<b>site " in page and "clicked Try the live demo" in page


def test_journeys_put_each_visitors_steps_in_order(tmp_path):
    from zoneinfo import ZoneInfo

    from sitechat.stats import events_csv, journeys
    from sitechat.visits import Visits

    v = Visits(tmp_path)
    v.hit("view1aaaa", address="a", agent="Firefox", page="/", referrer="www.google.com", now=1000)
    v.hit("view1aaaa", address="a", agent="Firefox", click="Install free → #install", now=1015)
    v.hit("view1aaaa", address="a", agent="Firefox", now=1030)
    v.hit("view2aaaa", address="a", agent="Firefox", page="/privacy.html", now=1060)
    demo = {
        "journeys": [
            {
                "visitor": "d1",
                "started": 2000,
                "seconds": 300,
                "waited": 0,
                "pages": [["/", 0], ["/link", 30]],
            }
        ]
    }
    paths = journeys(v.since(0), v.clicked(0), demo)
    assert [p["source"] for p in paths] == ["demo", "site"]
    site = paths[1]
    assert [what for _, what in site["steps"]] == [
        "opened / (from www.google.com)",
        "clicked Install free → #install",
        "opened /privacy.html",
    ]
    assert site["seconds"] == 60
    rows = events_csv(paths, ZoneInfo("UTC")).splitlines()
    assert rows[0] == "source,visitor,time,seconds_into_visit,step"
    assert rows[1].startswith("site,") and rows[-1].endswith(",opened /link")


def test_the_events_file_needs_the_password(tmp_path, knowledge):
    c = client(tmp_path, knowledge, stats_password="s3cret")
    assert c.get("/stats/events.csv").status_code == 401
    r = c.get("/stats/events.csv", auth=("owner", "s3cret"))
    assert r.status_code == 200 and r.text.startswith("source,visitor")
    assert r.headers["cache-control"] == "no-store"


def test_stats_page_without_the_demo(tmp_path, knowledge):
    c = client(tmp_path, knowledge, stats_password="s3cret")
    assert "demo: not set up" in _stats(c).text


def test_every_page_counts_its_visits(dist):
    for page in ("index.html", "privacy.html"):
        assert re.search(r'src="assets/visit\.js\?v=\w+"', (dist / page).read_text()), page


def test_the_demo_is_asked_with_its_key_and_a_user_agent_of_its_own(monkeypatch):
    import io
    import urllib.error

    from sitechat import stats

    sent = []

    def answer(request, timeout):
        sent.append(request)
        return io.BytesIO(b'{"now": {}, "visits": []}')

    monkeypatch.setattr(stats.urllib.request, "urlopen", answer)
    source = stats.DemoSource("https://demo.plant.example/api/demo/stats", "k")
    assert source.read(15) == {"now": {}, "visits": []}
    assert sent[0].full_url.endswith("?days=15")
    assert sent[0].get_header("Authorization") == "Bearer k"
    assert sent[0].get_header("User-agent") == stats.USER_AGENT

    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(stats.urllib.request, "urlopen", refuse)
    assert source.read() == "not reachable (HTTP 403)"


# --- the server's health (health.py) ------------------------------------------------------------


def _sample(at, **over):
    sample = {
        "at": at,
        "cpu": 20.0,
        "cores": 4,
        "load": [0.5, 0.4, 0.3],
        "memory": {"total": 16 * 2**30, "used": 6 * 2**30, "swap_used": 0},
        "disk": {"total": 200 * 2**30, "free": 120 * 2**30},
        "containers": [
            {
                "name": "processcraft",
                "state": "running",
                "health": "healthy",
                "restarts": 0,
                "wanted": True,
                "cpu": 12.0,
                "mem": 2**30,
            },
            {
                "name": "ops-backup",
                "state": "exited",
                "health": "",
                "restarts": 0,
                "wanted": False,
                "cpu": 0.0,
                "mem": 0.0,
            },
        ],
        "units": {"cloudflared": "active", "plantcraft-site": "active"},
        "probes": [
            {"name": "demo (internet)", "url": "https://demo.example/", "code": 200, "seconds": 0.4}
        ],
        "tunnel": {"requests": at, "errors": 0.0},
    }
    sample.update(over)
    return sample


def test_a_healthy_sample_has_no_problem_and_one_offs_are_not_watched():
    from sitechat.health import problems

    assert problems(_sample(1000), _sample(970), []) == {}


def test_problems_are_named_and_alert_once_when_they_last_then_once_when_gone():
    from sitechat.health import Alerts, problems

    down = _sample(1000)
    down["probes"][0].update(code=502)
    down["containers"][0].update(state="restarting")
    down["units"]["cloudflared"] = "failed"
    found = problems(down, _sample(970), [])
    assert sorted(found) == ["container:processcraft", "probe:demo (internet)", "unit:cloudflared"]
    assert "HTTP 502" in found["probe:demo (internet)"][1]

    sent = []
    alerts = Alerts(sent.extend)
    assert alerts.update(found) == []  # one sample is not an outage yet
    assert {a["key"] for a in alerts.update(found)} == set(found)
    assert alerts.update(found) == []  # said once
    back = alerts.update({})
    assert {a["state"] for a in back} == {"ok"} and len(back) == 3
    assert len(sent) == 6


def test_a_restart_full_disk_and_5xx_share_are_problems():
    from sitechat.health import problems, traffic

    now = _sample(1300, disk={"total": 100, "free": 5})
    now["containers"][0]["restarts"] = 1
    recent = [_sample(1000 + 30 * i) for i in range(10)]
    recent[-1]["tunnel"] = {"requests": 1270.0, "errors": 0.0}
    now["tunnel"] = {"requests": 1300.0, "errors": 30.0}  # 10% of 300
    found = problems(now, recent[-1], recent)
    assert {"restart:processcraft", "disk", "errors"} <= set(found)
    # A counter that went down: cloudflared restarted; it counts from zero again.
    rate = traffic([_sample(0), _sample(60, tunnel={"requests": 30.0, "errors": 3.0})])
    assert rate["requests"] == 30 and rate["error_pct"] == 10


def test_an_alert_is_a_push_with_a_link_to_the_stats(monkeypatch):
    from sitechat import health

    sent = []
    monkeypatch.setattr(
        health.urllib.request,
        "urlopen",
        lambda r, timeout: sent.append(r) or __import__("io").BytesIO(),
    )
    notify = health.Notifier("https://ntfy.sh/topic", "me@example.com", "plant.example")
    notify([{"key": "disk", "state": "problem", "line": "disk 5% free"}])
    request = sent[0]
    assert request.full_url == "https://ntfy.sh/topic" and request.data == b"PROBLEM: disk 5% free"
    assert request.get_header("Priority") == "high"
    assert request.get_header("Click") == "https://plant.example/stats"
    assert request.get_header("Email") == "me@example.com"
    health.Notifier("")([{"key": "disk", "state": "ok", "line": "x"}])  # no topic: only the log
    assert len(sent) == 1


def test_a_refused_email_never_costs_the_push(monkeypatch):
    import io
    import urllib.error

    from sitechat import health

    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        if request.get_header("Email"):
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"code":40035}')
            )
        return io.BytesIO()

    monkeypatch.setattr(health.urllib.request, "urlopen", urlopen)
    notify = health.Notifier("https://ntfy.sh/topic", "me@example.com", "plant.example")
    assert notify.send("PlantCraft: something is wrong", "PROBLEM: x", urgent=True)
    assert [r.get_header("Email") for r in sent] == ["me@example.com", None]


def test_stats_page_shows_the_server_now(tmp_path, knowledge):
    import time

    now = time.time()
    rows = [_sample(now - 600 + 30 * i) for i in range(20)]
    rows[-1]["containers"][0].update(state="restarting")
    (tmp_path / "health.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "alerts.jsonl").write_text(
        json.dumps(
            {
                "at": now - 30,
                "key": "container:processcraft",
                "state": "problem",
                "line": "processcraft is restarting",
            }
        )
        + "\n"
    )
    c = client(tmp_path, knowledge, stats_password="s3cret")
    page = _stats(c).text
    assert "Server now" in page and "processcraft is restarting" in page
    assert "0 of 1</b> services running" in page and "ops-backup" not in page
    assert "<svg class='spark'" in page and "requests (site + demo" in page
    r = c.get("/stats/now.json", auth=("x", "s3cret"))
    assert r.status_code == 200
    body = r.json()
    assert (
        body["health"]["stale"] is False
        and body["health"]["open"][0]["key"] == "container:processcraft"
    )
    assert c.get("/stats/now.json").status_code == 401


def test_stats_page_says_when_the_watch_stopped(tmp_path, knowledge):
    (tmp_path / "health.jsonl").write_text(json.dumps(_sample(1000.0)) + "\n")
    c = client(tmp_path, knowledge, stats_password="s3cret")
    assert "the watch (plantcraft-watch) stopped" in _stats(c).text
