"""The pages of PlantCraft's site: content and markup (build.py wraps each in page/template.html).

Marks and pictures are files beside the pages (assets/img, assets/shots, assets/clips); no inline
style or script anywhere, for the Content Security Policy (sitechat/app.py).
"""
# ruff: noqa: E501


def svg(p):
    return "assets/img/" + p


def jpg(n):
    return ("assets/shots/" if n.startswith("app-") else "assets/clips/") + n + ".jpg"


CLIPS = [
    ("dashboards", "Monitor your KPIs"),
    ("process", "See your plant"),
    ("analytics", "Find the problems"),
    ("alarms", "Handle alarms"),
    ("reports", "Share reports"),
    ("sources", "Collect the data"),
    ("desk", "Manage your day"),
]
APPS = [
    (
        "histcraft",
        "Historian",
        "app-historian",
        "Years of plant data, any period in milliseconds.",
        [
            "Reads PI Web API, OPC UA, MQTT, Modbus TCP, SQL and CSV",
            "Compression, hourly, daily and monthly rollups",
            "Imports history once or on a schedule",
        ],
    ),
    (
        "linkcraft",
        "Analytics",
        "app-analytics",
        "Algorithms that find what is wrong, for every asset.",
        [
            "Blocks or Python, run on a schedule",
            "Disturbances, bad data, energy use, equipment problems",
            "Each result shows how it was reached",
        ],
    ),
    (
        "dashcraft",
        "View",
        "dashboards",
        "Dashboards, process displays and reports.",
        [
            "Built by anyone, shared with the shift",
            "Process diagrams with live values",
            "Scheduled reports by e-mail",
        ],
    ),
    (
        "alarmcraft",
        "Alarms",
        "app-alarms",
        "The alarm list, cleaned up.",
        [
            "Rules, priorities and shelving",
            "Alarm performance numbers",
            "Rules created from past events",
        ],
    ),
    (
        "modelcraft",
        "Models",
        None,
        "Models of the process, on its own data.",
        [
            "Soft sensors and process models",
            "Optimisation studies",
            "Results shared with every app",
        ],
    ),
    (
        "doccraft",
        "Documents",
        None,
        "Manuals and procedures the assistant can cite.",
        [
            "Search across the plant's documents",
            "Answers with the page they came from",
            "Stays on your servers",
        ],
    ),
    (
        "desk",
        "Desk",
        "desk",
        "Each person's day in one place.",
        ["Actions, calendar, notes and to-dos", "What needs you today", "The assistant chat"],
    ),
    (
        "operations",
        "Operations",
        None,
        "For IT and partners.",
        [
            "Health, logs, backups and updates",
            "Support requests with answer times",
            "Partner access with an end date",
        ],
    ),
]
IC = {
    "srv": '<path d="M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01"/>',
    "ro": '<path d="M3 12h11M10 7l5 5-5 5M19 4v16"/>',
    "lock": '<path d="M6 11h12v9H6zM9 11V8a3 3 0 0 1 6 0v3"/>',
    "ai": '<path d="M8 7h8a5 5 0 0 1 0 10H8A5 5 0 0 1 8 7zM8 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z"/>',
    "code": '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13 6l-2 12"/>',
    "book": '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 19V5"/>',
    "grid": '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
    "key": '<path d="M14 10a4 4 0 1 1-1.2-2.8L21 15v3h-3v-2h-2v-2"/>',
    "check": '<path d="M4 12l5 5L20 6"/>',
    "bolt": '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    "page": '<path d="M6 3h9l4 4v14H6zM14 3v5h5"/>',
    "build": '<path d="M14 6l4 4-9 9H5v-4zM12 8l4 4"/>',
    "clock": '<path d="M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z"/>',
    "term": '<path d="M4 6l5 5-5 5M11 18h9"/>',
    "wand": '<path d="M5 19L17 7M15 5l1-2 1 2 2 1-2 1-1 2-1-2-2-1zM6 9l.7-1.3L8 7l-1.3-.7L6 5l-.7 1.3L4 7l1.3.7z"/>',
    "sun": '<path d="M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/>',
    "open": '<path d="M7 11V7a5 5 0 0 1 9.6-2M6 11h12v9H6z"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "chat": '<path d="M4 4h16v12H9l-5 4z"/>',
}


def ico(k, c="ico"):
    return f'<svg class="{c}" viewBox="0 0 24 24" aria-hidden="true">{IC[k]}</svg>'


GH = '<svg viewBox="0 0 24 24"><path d="M12 .5a11.5 11.5 0 0 0-3.64 22.4c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5z"/></svg>'
LI = '<svg viewBox="0 0 24 24"><path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9.5h4V21H3zM9.5 9.5h3.8v1.6h.06c.53-1 1.83-2.06 3.77-2.06 4.03 0 4.77 2.65 4.77 6.1V21h-4v-5.1c0-1.22-.02-2.79-1.7-2.79-1.7 0-1.96 1.33-1.96 2.7V21h-4z"/></svg>'
XX = '<svg viewBox="0 0 24 24"><path d="M17.75 3h3.07l-6.7 7.66L22 21h-6.17l-4.83-6.32L5.47 21H2.4l7.17-8.2L2 3h6.33l4.37 5.77zm-1.08 16.18h1.7L7.4 4.73H5.58z"/></svg>'
YT = '<svg viewBox="0 0 24 24"><path d="M23 7.2a3 3 0 0 0-2.1-2.1C19 4.6 12 4.6 12 4.6s-7 0-8.9.5A3 3 0 0 0 1 7.2 31 31 0 0 0 .5 12a31 31 0 0 0 .5 4.8 3 3 0 0 0 2.1 2.1c1.9.5 8.9.5 8.9.5s7 0 8.9-.5a3 3 0 0 0 2.1-2.1 31 31 0 0 0 .5-4.8 31 31 0 0 0-.5-4.8zM9.75 15.02V8.98L15.5 12z"/></svg>'

PILLARS = [
    (
        "open",
        "01",
        "Open",
        "Free and open source, all of it.",
        "open",
        "All of it open, and yours to extend.",
        "Each result shows how it was reached, in blocks and Python you can read, change and share.",
        [
            ("code", "Apache-2.0", "Use it, change it, ship it in your products. No paid edition."),
            (
                "book",
                "Open algorithms",
                "Open Python from public literature: check, cite, improve.",
            ),
            ("grid", "A complete suite", "Data, analytics, alarms, dashboards, models, documents."),
            ("key", "Yours stays yours", "What you create can stay closed. No need to open it."),
        ],
        "vis-open",
    ),
    (
        "secure",
        "02",
        "Secure",
        "On your network, read-only.",
        "shield",
        "Ready for your security team.",
        "PlantCraft runs inside your network and only reads plant data. A two-page security guide shows how it follows IEC 62443, the international standard for industrial cybersecurity.",
        [
            (
                "srv",
                "On your own servers",
                "One signed bundle, even with no internet. No telemetry.",
            ),
            ("ro", "Read-only to the plant", "Reads OPC UA, PI, MQTT, Modbus, SQL. Never writes."),
            ("lock", "Protected by default", "HTTPS, sign-in, audit log, isolated calculations."),
            (
                "ai",
                "AI you configure",
                "Off until you turn it on. Your provider or your own model.",
            ),
        ],
        "vis-secure",
    ),
    (
        "llm",
        "03",
        "LLM-first",
        "An assistant that checks.",
        "chat",
        "An assistant that finds the problems with you.",
        "Instead of searching through results and charts, ask. It checks the results, points to what needs attention and suggests what to do first.",
        [
            ("check", "Checks the results", "Reads data, results, documents and history."),
            ("bolt", "Suggests actions", "What is wrong, why, what first. You confirm."),
            ("build", "Helps you build", "Proposes algorithms, rules, dashboards and models."),
            ("page", "On every page", "Ask about the loop, alarm or report you are on."),
        ],
        "vis-llm",
    ),
    (
        "fast",
        "04",
        "Fast",
        "Running in minutes.",
        "clock",
        "Running in minutes. Useful the same day.",
        "No project before the first result. A few commands install it, the assistant helps you set it up, and the first findings arrive the same day.",
        [
            ("clock", "About 10 minutes", "To install, with a demo plant to try everything."),
            ("term", "Works offline", "One signed file, checked before it installs."),
            ("wand", "Assisted setup", "The assistant drafts your assets and signals."),
            ("sun", "Same day", "First findings on process, equipment, energy and data quality."),
        ],
        "vis-fast",
    ),
]

CHATS = [
    {
        "q": "Why did the furnace outlet temperature alarm fire at 14:05?",
        "a": "TIC-201 rose 6 °C in 12 minutes. The fuel valve FV-201 stayed at 62 % while its controller asked for less: it looks stuck. Same pattern on Monday. First step: ask maintenance to stroke-test FV-201.",
        "pts": [40, 41, 40, 42, 41, 43, 47, 52, 55, 57, 56, 55],
    },
    {
        "q": "What should we fix first this week?",
        "a": "Three issues cost the most: furnace efficiency is 3 % below last month, analyzer AT-210 has been frozen since Friday, and the valve on PIC-022 is sticking. I opened a draft action for each, ordered by impact.",
        "pts": [21, 14, 9, 6, 4, 3, 2, 2, 1, 1, 1, 1],
    },
    {
        "q": "What changed in column C-100 since Monday?",
        "a": "The reflux ratio went from 2.4 to 2.9 on Tuesday at 09:10, after a setpoint change by the shift. Top purity improved 0.3 %, steam use rose 4 %. No alarms linked to it.",
        "pts": None,
    },
]

VIS = {
    "vis-open": """<div class="vis vopen"><div class="goal"><span class="gk">Goal <em id="extag"></em></span><b id="exgoal"></b></div>
<div class="chain" id="chain"></div>
<div class="dview" id="dview" data-v="data"><div class="dtop"><span id="dstep"></span><span class="dhint" id="dhint"></span><div class="dseg"><button type="button" class="on" data-v="data">Data</button><button type="button" data-v="py">Python</button></div></div>
<div class="dd"><div id="dplot"></div><p id="dtext"></p></div><pre class="py" id="py"></pre></div>
<div class="vfoot"><span class="rdot" id="exdot"></span><span class="rlab">Result</span><b id="exres"></b><button type="button" class="mini" id="nextex">Next example →</button></div></div>""",
    "vis-secure": """<div class="vis net"><div class="zone plant"><span class="zl">Plant control network</span><div class="node">DCS / PLC</div><div class="node">PI · OPC UA</div></div>
<div class="flow"><span class="dot"></span><span class="dot d2"></span><span class="dot d3"></span><em>read-only</em></div>
<div class="zone site"><span class="zl">Your site network</span><div class="node main"><img src="LOGO" alt="">PlantCraft server</div><div class="node">Engineers · browser</div></div>
<div class="noint"><span>Internet</span><s>not needed</s></div>
<ul class="ticks" id="ticks"><li>Signed bundle checked</li><li>Sign-in required</li><li>Audit log on</li><li>Backup before update</li></ul></div>""",
    "vis-llm": """<div class="vis vchat"><div class="vh"><span>Assistant · demo plant</span><button class="mini" id="nextq">Next question →</button></div><div class="msgs" id="msgs"></div>
<div class="ask"><div>Ask about the plant…</div><a class="btn p sm" href="%%DEMO_URL%%">Try it in the live demo</a></div></div>""",
    "vis-fast": """<div class="vis term"><div class="vh dark"><span>plant-server</span><span id="clock">00:00</span></div><pre id="term"></pre><div class="bar"><i id="prog"></i></div><ul class="finds" id="finds"></ul></div>""",
}

ptabs = "".join(
    f'<button class="ptab{" on" if i == 0 else ""}" data-p="{k}" aria-pressed="{str(i == 0).lower()}"><span class="pico">{ico(ic, "pi")}</span><span class="ptx"><span class="pn">{n}</span><b>{t}</b><span class="ps">{s}</span></span><span class="pgo">›</span><span class="pf"></span></button>'
    for i, (k, n, t, s, ic, _, _, _, _) in enumerate(PILLARS)
)
ppanes = "".join(
    f'''<div class="ppane{" on" if i == 0 else ""}" data-p="{k}"><div class="pl"><h3 class="ph">{h}</h3><p class="pld">{lead}</p><div class="feats">{"".join(f'<div class="feat">{ico(a, "fi")}<div><b>{b}</b><span>{c}</span></div></div>' for a, b, c in feats)}</div></div><div class="pr">{VIS[v].replace("LOGO", svg("logo-mark.svg"))}</div></div>'''
    for i, (k, n, t, s, ic, h, lead, feats, v) in enumerate(PILLARS)
)
apptabs = "".join(
    f'<button class="atab{" on" if k == 0 else ""}" data-i="{k}"><img src="{svg("apps/" + i + ".svg")}" alt=""><span>{n}</span></button>'
    for k, (i, n, _, _, _) in enumerate(APPS)
)
apppanes = "".join(
    f'''<div class="apane{" on" if k == 0 else ""}" data-i="{k}"><div><h3 class="aname"><img src="{svg("apps/" + i + ".svg")}" alt="">{n}</h3><p class="adesc">{d}</p><ul class="check">{"".join(f"<li>{b}</li>" for b in bl)}</ul></div>
<div class="ashot">{f'<img src="{jpg(c)}" alt="" class="zoom"><span class="zh">Click to enlarge</span>' if c else "<span>Screenshot to come</span>"}</div></div>'''
    for k, (i, n, c, d, bl) in enumerate(APPS)
)
_cliptabs = "".join(
    f'<button class="tab{" on" if i == 0 else ""}" data-i="{i}">{l}<span class="f"></span></button>'
    for i, (n, l) in enumerate(CLIPS)
)

PAGES = {}


def page(fn, title, body, js=""):
    PAGES[fn] = (title, body)


def faq(items):
    return (
        '<div class="faqs">'
        + "".join(
            f'<div class="faq"><button>{q}<span>+</span></button><p>{a}</p></div>' for q, a in items
        )
        + "</div>"
    )


def end(h, t, b1, b2):
    return f"""<section class="end"><p class="eyebrow">Talk to us</p><h2>{h}</h2><p class="hint narrow">{t}</p><div class="ctas"><button class="btn p" data-chat="contact">{b1}</button><button class="btn" data-chat="ask">{b2}</button></div></section>"""


TIERS0 = """<div class="tiers">
<div class="tier"><span class="tag">Free</span><div class="amt">Free forever</div><p>The whole suite on your own servers, every app, no limits.</p>
<ol class="steps"><li>Check the <a href="install.html#req">requirements</a>: Docker on Linux, macOS or Windows</li><li>Download the signed bundle</li><li>Run the installer and sign in, about 10 minutes</li></ol>
<div class="tb"><a class="btn p" href="%%GH%%/releases/latest">Download 0.6.0</a><a class="btn" href="install.html">How to install</a></div></div>
<div class="tier hl"><span class="tag">Founding plants <em>3 places</em></span><div class="amt">Free 30-day pilot</div><p>For the first process plants, with us at your side.</p>
<ul class="check"><li>We install and configure it with you</li><li>Connection to your PI, OPC UA or CSV</li><li>First findings and suggested actions, reviewed together</li></ul>
<div class="tb"><a class="btn p" href="pricing.html#pilot">Apply for a pilot</a></div></div>
<div class="tier"><span class="tag">Services and support</span><div class="amt">Per plant</div><p>For plants that run on it every day. Never per user or per tag.</p>
<ul class="check"><li>Installation, monitoring and monthly actions</li><li>Diagnosis, custom apps and training</li><li>Support with answer times, offline updates</li></ul>
<div class="tb"><a class="btn" href="pricing.html">See pricing</a></div></div></div>"""


def TIERSF(b):
    return TIERS0.replace('<a class="btn" href="pricing.html">See pricing</a>', b)


TIERS = TIERSF('<a class="btn" href="pricing.html">See pricing</a>')
# ---------------- HOME
home = f"""<header class="hero"><h1>The open suite for industrial plants.</h1>
<p class="lead">Your plant's data, analytics, alarms and dashboards on your own servers, <br>with an AI assistant that checks the results with you.</p>
%%SHOWCASE%%</header>
<section id="pillars"><div class="shead"><p class="eyebrow">Why PlantCraft</p><h2>Four reasons, one platform.</h2><p class="hint">Open source and free to use, today and always.</p></div>
<div class="ptabs">{ptabs}</div><div class="pbox">{ppanes}</div></section>
<section id="apps"><div class="shead"><p class="eyebrow">The suite</p><h2>A suite of apps for the whole plant.</h2><p class="hint">Each app takes care of one part of the work: data, analysis, alarms, dashboards, models, documents. <br>They share the same people, assets and data. Use the ones you need.</p></div>
<div class="apps"><div class="atabs">{apptabs}</div><div class="apanes">{apppanes}</div></div></section>
<section id="start"><div class="shead"><p class="eyebrow">Get started</p><h2>Free to use. Help when you want it.</h2></div>{TIERS}
<div class="partner"><div><span class="tag light">Partners</span><h3>Deliver more on an open platform. Keep your work yours.</h3><p>Install and support PlantCraft for your clients, and build your own apps on it, open or closed.</p></div><a class="btn white" href="partners.html">Become a partner</a></div></section>
{end("Tell us about your plant.", "A pilot on your unit, help to install it, training for your team, an app for your process, or a question the documentation does not answer: write to us and we answer personally.", "Talk to us", "Ask the assistant")}"""
page("index.html", "PlantCraft", home + '<div class="lb" id="lb"><img id="lbimg" alt=""></div>')

# ---------------- shared form
NAMES = {
    "Name": "name",
    "Work e-mail": "email",
    "Company and plant": "company",
    "Company and country": "company",
}


def form(title, fields, btn, note):
    """A contact form; forms.js sends it to /api/contact (name, email, company, and the rest
    joined into "need" with the form's title)."""
    out = []
    for i, (label, opts) in enumerate(fields):
        name = NAMES.get(label, f"q{i}")
        need = "" if label in NAMES else f' data-label="{label}"'
        typ = (
            ' type="email" autocomplete="email"'
            if name == "email"
            else (' autocomplete="name"' if name == "name" else "")
        )
        if label.endswith("?"):
            field = f'<textarea name="{name}" rows="3" maxlength="1500"{need} required></textarea>'
        elif opts:
            field = (
                f'<select name="{name}"{need}>'
                + "".join(f"<option>{o}</option>" for o in opts)
                + "</select>"
            )
        else:
            field = f'<input name="{name}"{typ}{need} maxlength="160" required>'
        out.append(f"<label>{label}{field}</label>")
    return (
        f'<form class="form" data-form="{title}" novalidate><b>{title}</b>{"".join(out)}'
        '<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">'
        f'<button class="btn p" type="submit">{btn}</button><span class="fnote" role="status">{note}</span></form>'
    )


# ---------------- PRICING
GROUPS = [
    (
        "Start",
        "Get running on your plant",
        [
            (
                "srv",
                "Installation and setup",
                "On your servers or a VM we prepare, with sign-in, backups and HTTPS.",
            ),
            (
                "ro",
                "Connection to your data",
                "PI, OPC UA, MQTT, Modbus, SQL or CSV, with assets and signals named.",
            ),
        ],
    ),
    (
        "Run",
        "Keep it useful every day",
        [
            (
                "check",
                "Monitoring and monthly actions",
                "We follow the results and send a short report: what is wrong, what to do first.",
            ),
            (
                "shield",
                "Support and updates",
                "Answer times you can count on, signed offline updates, long-term versions.",
            ),
            (
                "page",
                "Data care",
                "Cleaning, naming and keeping signals and history healthy over time.",
            ),
        ],
    ),
    (
        "Improve",
        "Go further on your process",
        [
            (
                "bolt",
                "Diagnosis",
                "A focused study of one unit: disturbances, bad data, energy, equipment.",
            ),
            (
                "build",
                "Custom apps and models",
                "Algorithms, models and apps for your process, open or kept private.",
            ),
            ("book", "Training", "For engineers, operators and IT, on your plant's own data."),
        ],
    ),
]
srv = "".join(
    f'<div class="sgrp"><div class="sgh"><span>{n:02d}</span><div><b>{g}</b><em>{d}</em></div></div>'
    + "".join(
        f'<div class="srow">{ico(a, "fi")}<div><b>{b}</b><span>{c}</span></div></div>'
        for a, b, c in it
    )
    + "</div>"
    for n, (g, d, it) in enumerate(GROUPS, 1)
)
pricing = f"""<header class="phero"><p class="eyebrow">Pricing</p><h1>Free to use. Pay only for help.</h1>
<p class="lead">The software is free and open source, for every plant. When you want us at your side, we charge per plant, never per user or per tag.</p></header>
<section class="tight">{TIERSF('<a class="btn" href="#services">See the services</a>')}</section>
<section id="services"><div class="shead"><p class="eyebrow">Services</p><h2>What we can do for your plant.</h2><p class="hint">Pick what you need. Each plant gets one price for the year, set by its size.</p></div>
<div class="sgroups">{srv}</div></section>
<section id="pilot"><div class="pilot"><div><p class="eyebrow">Founding plants</p><h2>Three places for a free pilot.</h2>
<p class="hint">30 days on one unit of your plant, with us at your side. Free in money, not in commitment.</p>
<div class="twocol"><div><h4>You get</h4><ul class="check"><li>Installation and connection to your data</li><li>First findings in the first week</li><li>Suggested actions, reviewed together</li><li>A founding price for the year after, agreed up front</li></ul></div>
<div><h4>We ask</h4><ul class="check"><li>A process plant with historian data</li><li>One person who owns the pilot</li><li>About 4 hours of your team's time</li><li>Permission to tell the story, without names if you prefer</li></ul></div></div></div>
{form("Apply for a pilot", [("Name", 0), ("Company and plant", 0), ("Work e-mail", 0), ("What would you like to find first?", 0)], "Send", "We answer personally within 2 working days.")}</div></section>
{end("Ask for a quote.", "Tell us about your plant, how many units and what you need. We answer personally.", "Talk to us", "Ask the assistant")}"""
page("pricing.html", "Pricing · PlantCraft", pricing)

# ---------------- PARTNERS
WHO = [
    (
        "ro",
        "Integration",
        "Install PlantCraft at your clients' plants and connect it to their PI, OPC UA or SQL.",
    ),
    ("chat", "Consulting", "Bring your methods to the plant, with results everyone can check."),
    ("build", "Building apps", "Build apps and models for a sector or a process, open or closed."),
]
who = "".join(
    f'<div class="wcard">{ico(a, "pi")}<b>{b}</b><span>{c}</span></div>' for a, b, c in WHO
)
PROG = [
    ("book", "Training", "Learn to install, connect and build on PlantCraft, with a certificate."),
    ("bolt", "Early access", "New versions and features before they are released."),
    ("chat", "Direct line to us", "Technical help from the people who build the platform."),
    ("grid", "Listed on our site", "Plants looking for help find you in the partner list."),
    ("build", "App template", "A starting point for your own app, with the same look and sign-in."),
    ("key", "Your licence, your price", "Sell your apps and services at your own terms."),
]
partners = f'''<header class="phero"><p class="eyebrow">Partners</p><h1>Go straight to the plant.</h1>
<p class="lead">No vendor in the middle and no licences to resell. Install, connect and build on an open platform, and deliver directly to your clients.</p>
<div class="ctas"><a class="btn p" href="#join">Become a partner</a><a class="btn" href="https://github.com/PlantCraft/plantcraft-app-template">App template on GitHub</a></div></header>
<section class="tight"><div class="wgrid">{who}</div></section>
<section><div class="split"><div><p class="eyebrow">Open platform, your choice</p><h2>Open where it counts. Closed where you need it.</h2>
<p class="hint">Everything PlantCraft publishes is open. The apps, models and settings you create are yours, and you choose the licence.</p>
<ul class="check big"><li><b>Apache-2.0 platform.</b> No paid edition, no lock-in for you or your clients.</li><li><b>Your work stays yours.</b> Your models, rules and settings at a client never become public.</li><li><b>Closed apps.</b> Ship your app as a signed package, with your own licence per plant. <em class="soon">Coming soon</em></li><li><b>Same look and sign-in.</b> Your app runs inside the suite like ours do.</li></ul></div>
<div class="pkg"><div class="pk-h"><img src="{svg("logo-mark.svg")}" alt=""><b>Apps in your PlantCraft</b></div>
<div class="pk"><img src="{svg("apps/histcraft.svg")}" alt=""><div><b>Historian</b><span>PlantCraft · open</span></div><i class="o">Open</i></div>
<div class="pk"><img src="{svg("apps/linkcraft.svg")}" alt=""><div><b>Analytics</b><span>PlantCraft · open</span></div><i class="o">Open</i></div>
<div class="pk"><img src="{svg("apps/doccraft.svg")}" alt=""><div><b>PlantCraft PID</b><span>PlantCraft · P&amp;ID reader</span></div><i class="c">Closed</i></div>
<div class="pk"><div class="ph0">YA</div><div><b>Your app</b><span>Your company · licensed per plant</span></div><i class="c">Closed</i></div>
<div class="pk"><div class="ph0">CO</div><div><b>Client model</b><span>Your company · private</span></div><i class="c">Private</i></div>
<p class="fnote">Signed packages, licence checked offline, permissions reviewed by the plant's admin.</p></div></div></section>
<section><div class="shead"><p class="eyebrow">What you get</p><h2>The partner program.</h2><p class="hint">Free while we grow it with the first partners. No commission.</p></div>
<div class="sgrid s3">{"".join(f'<div class="feat big">{ico(a, "fi")}<div><b>{b}</b><span>{c}</span></div></div>' for a, b, c in PROG)}</div></section>
<section><div class="shead"><p class="eyebrow">How it works</p><h2>From first call to first client.</h2></div>
<div class="howto line"><div><span>1</span><b>Apply</b><p>Tell us about your company, your clients and what you want to deliver. We answer within 2 working days.</p></div><div><span>2</span><b>Get started with us</b><p>A call, then a demo plant installed together, so your team knows the platform.</p></div><div><span>3</span><b>First client</b><p>We stand behind you on your first project: setup, questions and reviews of the results.</p></div></div></section>
<section id="join"><div class="pilot"><div><p class="eyebrow">Become a partner</p><h2>Let's work together.</h2>
<p class="hint">We are choosing the first partners now. A short form, then a call.</p>
<ul class="check big"><li>System integrators, consultants and app builders</li><li>Any country; the product is in English</li><li>No fee to join, no sales targets</li></ul></div>
{form("Apply to be a partner", [("Name", 0), ("Company and country", 0), ("Work e-mail", 0), ("What you do", ["Integration", "Consulting", "Building apps", "More than one"]), ("Which clients or sectors do you serve?", 0)], "Send", "We answer personally within 2 working days.")}</div></section>
{end("Questions first?", "Write to us or ask the assistant. We answer personally.", "Talk to us", "Ask the assistant")}'''
page("partners.html", "Partners · PlantCraft", partners)

# ---------------- INSTALL
OS = {
    "Linux": [
        "Install Docker Engine 24 or later.",
        "Download the signed bundle.",
        "Open the bundle and run the installer. It checks the signature first.",
        "Open the address it shows and sign in as admin.",
    ],
    "macOS": [
        "Install Docker Desktop and give it 8 GB of memory.",
        "Download the signed bundle.",
        "Open the bundle and run the installer. It checks the signature first.",
        "Open the address it shows and sign in as admin.",
    ],
    "Windows": [
        "Install Docker Desktop with WSL 2.",
        "Download the signed bundle.",
        "Open the bundle in WSL and run the installer. It checks the signature first.",
        "Open the address it shows and sign in as admin.",
    ],
}
ostabs = "".join(
    f'<button class="ostab{" on" if i == 0 else ""}" data-o="{o}">{o}</button>'
    for i, o in enumerate(OS)
)
ospanes = "".join(
    f'<ol class="ost{" on" if i == 0 else ""}" data-o="{o}">'
    + "".join(f"<li><span>{j + 1}</span>{s}</li>" for j, s in enumerate(st))
    + "</ol>"
    for i, (o, st) in enumerate(OS.items())
)
REQ = [
    ("srv", "Server", "Linux, macOS or Windows, one machine or VM"),
    ("grid", "Memory", "8 GB minimum, 16 GB for a full plant"),
    ("page", "Disk", "50 GB, plus about 1 GB per 1,000 signals per year"),
    ("bolt", "Processor", "4 cores"),
    ("ro", "Network", "Read access to your PI, OPC UA or other source. Internet not needed"),
    ("open", "Browser", "Any recent Chrome, Edge, Firefox or Safari"),
]
install = f'''<header class="phero"><p class="eyebrow">Install</p><h1>Running in about 10 minutes.</h1>
<p class="lead">One signed bundle with the whole suite. It works offline, checks itself before installing, and comes with a demo plant so you can try everything.</p></header>
<section class="tight"><div class="dl"><div class="dlm"><img src="{svg("logo-mark.svg")}" alt=""><div><b>PlantCraft 0.6.0</b><span>All 8 apps · demo plant · signed · Apache-2.0</span></div></div>
<div class="dlb"><a class="btn p big" href="%%GH%%/releases/latest">Download 0.6.0</a><a class="btn" href="%%DOCS%%/docs/install.md">Install guide on GitHub</a></div></div></section>
<section id="req"><div class="shead"><p class="eyebrow">Step 1</p><h2>Check the requirements.</h2></div>
<div class="reql">{"".join(f"<div>{ico(a, 'fi')}<b>{b}</b><span>{c}</span></div>" for a, b, c in REQ)}</div></section>
<section><div class="shead"><p class="eyebrow">Step 2</p><h2>Install on your system.</h2></div>
<div class="osbox"><div class="ostabs">{ostabs}</div>{ospanes}<p class="fnote mt">Proxies, HTTPS certificates, backups and updates are in the install guide. <a href="%%DOCS%%/docs/install.md" class="more">Read it on GitHub →</a></p></div></section>
<section><div class="shead"><p class="eyebrow">Step 3</p><h2>Your first day.</h2></div>
<div class="howto"><div><span>1</span><b>Try the demo plant</b><p>Every app is filled with a sample plant, so you can explore before connecting yours.</p></div><div><span>2</span><b>Connect your data</b><p>Add PI, OPC UA or a CSV. The assistant drafts your assets and signals.</p></div><div><span>3</span><b>See the first findings</b><p>Analytics runs on a schedule and the assistant points to what needs attention.</p></div></div></section>
<section><div class="help"><div><b>Rather have us install it?</b><span>Founding plants get installation and setup with us, free for 30 days.</span></div><a class="btn white" href="pricing.html#pilot">Apply for a pilot</a></div></section>
<section id="help"><div class="pilot"><div><p class="eyebrow">Talk to us</p><h2>Stuck somewhere?</h2>
<p class="hint">Tell us where it stopped and what you see. We answer personally.</p>
<ul class="check big"><li>Help with Docker, proxies and certificates</li><li>Help connecting PI, OPC UA or your database</li><li>Or ask the assistant on any page, any time</li></ul></div>
{form("Ask for help", [("Name", 0), ("Work e-mail", 0), ("System", ["Linux", "macOS", "Windows"]), ("Where did it stop?", 0)], "Send", "We answer personally within 2 working days.")}</div></section>'''
page("install.html", "Install · PlantCraft", install)
