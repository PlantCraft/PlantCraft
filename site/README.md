# PlantCraft's site and its chat

The public site (one page) and the chat on it: a language model that answers visitors' questions
from PlantCraft's public documentation and takes contact requests. Not published yet.

```bash
cd site
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
make ci          # ruff and the tests (no model needed)
make serve       # builds dist/ and serves it at http://127.0.0.1:8090
```

## What it says

The page is [page/template.html](page/template.html), built by [build.py](build.py) with the app
marks and fonts of the suite. Its positioning is the owner's (2026-10-26/27): four pillars,
**Open**, **Secure**, **LLM-first** and **Fast**, in that order, and no prices or offers: every
commercial question goes to **Talk to us**. The text follows
[docs/product-page.md](../docs/product-page.md); numbers come from measured pages
([sizing](../docs/en/sizing.md), [install](../docs/install.md)).

## The chat

- **Answers only from public pages.** [knowledge/sources.toml](knowledge/sources.toml) lists them;
  [knowledge/facts.md](knowledge/facts.md) holds the site's own facts (status, no prices, no hosted
  version) and goes with every question, with the product page. The rest is searched (BM25, in
  pure Python) and the best six passages go in. The build writes them to `dist/knowledge.json`.
- **Cites its sources.** The model cites passages by number; the page links each to the published
  page on GitHub.
- **Takes contact requests.** When a visitor asks for contact, a demo, a pilot, prices or support,
  the answer ends with the contact form (name, email, company, need, and the visitor's questions if
  they agree). Requests go to `$SITE_DATA_DIR/contacts.jsonl` (mode 600) and, if set, to
  `SITE_CONTACT_WEBHOOK` (a Slack, Discord, Teams or ntfy webhook). `python -m sitechat contacts`
  prints them. The form works with the model off too.
- **Off without a key.** With no provider or key the chat shows only the contact form.

| Variable | Default | |
|---|---|---|
| `SITE_CHAT_PROVIDER` | `off` | `openai` (OpenAI or any compatible server) or `anthropic` |
| `SITE_CHAT_API_KEY` / `SITE_CHAT_API_KEY_FILE` | | the provider's key; never sent to the page or logged |
| `SITE_CHAT_MODEL` | `gpt-5-mini` / `claude-haiku-5-5` | |
| `SITE_CHAT_BASE_URL` | the provider's | an OpenAI-compatible server (vLLM, Ollama...) |
| `SITE_CHAT_REASONING` | | reasoning effort for OpenAI reasoning models (`minimal`, `low`) |
| `SITE_CHAT_DAILY_LIMIT` | `1000` | answers a day for the whole site: the cost ceiling |
| `SITE_DATA_DIR` | `./site-data` | contacts and questions |
| `SITE_CONTACT_WEBHOOK` | | told of each contact request |
| `SITE_LOG_QUESTIONS` | `1` | keep visitors' questions (no address, no name) to see what they ask |
| `SITE_TRUST_PROXY` | `0` | `1` behind a reverse proxy that sets `X-Forwarded-For` |
| `SITE_DOCS_URL` | `https://github.com/PlantCraft/PlantCraft/blob/main` | where cited pages live |
| `SITE_STATS_PASSWORD` / `SITE_STATS_PASSWORD_FILE` | | the password of `/stats`; unset, `/stats` is a 404 |
| `SITE_STATS_TIMEZONE` | `UTC` | the time zone `/stats` counts days in |
| `SITE_DEMO_STATS_URL` + `SITE_DEMO_STATS_KEY_FILE` | | the public demo's `/api/demo/stats` and its key, shown on `/stats` |

## Visits and the stats page

Each page view tells this server it opened, and every 30 seconds that it is still in front
(`page/assets/visit.js`, no cookie; `sitechat/visits.py`): the page, the site it came from (host
name only), the country Cloudflare names (`CF-IPCountry`, with `SITE_TRUST_PROXY=cloudflare`) and
the times, in `$SITE_DATA_DIR/visits.sqlite3`. No address is kept: one browser on one day is a
hash with a salt that lives in memory and changes daily. Bots and headless browsers are skipped.

`/stats` (HTTP Basic, any user name, `SITE_STATS_PASSWORD`) shows on one page who reads the site
now and in the demo, visitors and time per day for 14 days, where they came from, the pages read
(the site's and the demo's), every chat question (marking those the docs did not answer and those
that offered the contact form) and the contact requests. `deploy/cloud/vm.sh site` makes its
password; `vm.sh stats-password` prints it.

### Safety

- No secret in the page: the browser talks only to this server (`/api/chat`, `/api/contact`).
- Strict Content Security Policy (only this origin; no inline script or style), no cookies, no
  external fonts or scripts.
- Limits: 8 questions a minute and 60 a day per address, 3 contact requests an hour, a daily budget
  for the site, 1,200 characters a question, 12 messages of history, 64 KB a request.
- The model is told to answer only about PlantCraft, only from the sources, never to invent a
  feature, number, customer or date, never to quote a price, and to ignore instructions in a
  visitor's message. Anything that looks like a price is replaced in code, whatever the model wrote.
- A hidden field drops bots that fill every field of the contact form.

## The eval set

[eval/questions.toml](eval/questions.toml) holds the questions visitors are most likely to ask
(what it is, open, security, LLM, speed, data sources, apps, install, sizing, people, prices,
status, building apps), questions the documentation does not answer, off-topic questions and
attacks, each with the answer the team expects and checks on the model's answer.

- `make test` checks, without a model, that a page answering each question reaches the model.
- `make eval` asks the configured model every question, checks each answer and (with `--judge`)
  has the model compare it with the expected one; the report lands in `eval-report/report.md`.
  Run it after changing the prompt, the model, `facts.md` or the documentation.

## Deploying

One process serves the page and the chat: `python -m sitechat serve --host 127.0.0.1` behind a
reverse proxy with HTTPS (Caddy or nginx; set `SITE_TRUST_PROXY=1`), or `uvicorn` with
`sitechat.app:create_app --factory`. A static host such as GitHub Pages can serve `dist/` alone,
but then the chat and the contact form have no server: keep them on the same origin.
