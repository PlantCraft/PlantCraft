# AI assistant access (MCP)

PlantCraft can serve a **read-only MCP server**, so a person can connect their own AI assistant
(Claude Desktop, Claude Code or any client of the [Model Context Protocol](https://modelcontextprotocol.io/))
and ask it about the plant: "which loops of the crude unit are oscillating?", "plot FIC-101 over
the last week and tell me what changed", "what alarms did the compressor raise this month?".

The suite is meant to be used with AI. This server is how an assistant reads the plant without
anyone exporting data by hand. It also keeps the security rules: off by default, read-only, the
person's own access, nothing outside the plant's network unless the person's assistant is there.

## What an administrator does

**Settings › AI assistant access (MCP)**:

- **Turn on**: off by default. Turn it on only when IT agrees that people may use AI assistants
  with plant data. `PLANTCRAFT_MCP=off` in the installation's settings keeps it off for good,
  and the page then says why.
- **A token lasts at most (days)**: 30 by default, 365 at most.
- The table lists every person's tokens, when each was last used, and a **Revoke** button.

Turning it off stops every token at once (the server answers 404, as if it were not there).
Turning it on again revives the tokens that have not expired and were not revoked.

## What a person does

On their profile page (user menu › My profile), under **AI assistant**:

1. **Create token**, with a label such as "Claude on my laptop". The token (`pcat_...`) is shown
   once, with the command or JSON that connects the assistant to it.
2. Give it to the assistant. In Claude Code:

   ```bash
   claude mcp add --transport http plantcraft https://<server>/mcp \
     --header "Authorization: Bearer pcat_..."
   ```

   In other clients, the JSON form:

   ```json
   {"mcpServers": {"plantcraft": {"type": "http", "url": "https://<server>/mcp",
     "headers": {"Authorization": "Bearer pcat_..."}}}}
   ```

3. **Revoke** a token when it is no longer used or may have leaked. A person holds at most 10
   active tokens.

## What the assistant can read

Each tool is one read of API v1 ([api-v1.md](api-v1.md)), answered as the token's owner:

| Tool | What it reads |
|---|---|
| `whoami`, `list_apps` | Who the assistant reads as; the installed apps they may open |
| `search_assets`, `get_asset`, `list_asset_types` | The plant tree (units, equipment, control loops), signals by role, relations, the type catalog |
| `search_signals`, `get_signal`, `signal_value`, `signal_stats`, `read_series` | Signals, a recent value (last, mean, min, max, std), a period's exact statistics (every point kept: mean, min and max with their times) and history (up to 20 signals, about 1 000 points each by default, 366 days at most) |
| `latest_results`, `result_history`, `count_results` | What the apps publish: Analytics' loop health and signal quality, Alarms' states, others; one unit's results (`under`), and results counted per unit or area by status, most problems first |
| `recent_events`, `list_runs`, `list_actions` | Findings, alarms raised and cleared, runs, follow-up actions (all, or one asset's, by status) |
| `search_knowledge` | The texts the apps write for assistants (how an algorithm or a block works, a run's report) |
| `list_object_kinds`, `list_app_objects`, `get_app_object` | The apps' own objects (Analytics' blocks and algorithms, Models' models), as notebooks read them (`/api/v1/apps/<app>/objects/<kind>`): listed with their total, found by words or fields (`where active=true`: Alarms' active alarms), long fields left out, one read whole |

Nothing writes: there is no tool that changes a setpoint, an asset, an alarm or anything else.
Every tool declares `readOnlyHint`.

## How it is protected

- **Off by default**, and the installation can forbid it (`PLANTCRAFT_MCP=off`).
- **The person's own access.** Every call issues a short token for the owner at that moment and
  runs the API v1 route inside PlantCraft, so the assistant sees exactly what the person sees.
  A dashboards-only account cannot read through it. A person who is deactivated or loses access
  stops at once.
- **Tokens like app keys**: 256 random bits, only the SHA-256 is stored, shown once, with an
  expiry. Revoking takes effect on the next call.
- **Audited**: creating and revoking a token, changing the switch, and every tool call (tool and
  arguments) go to the audit log under the person's name.
- **Bounded answers**: a tool's answer is at most 60 000 characters, lists at most 200 items,
  history at most 20 signals.
- **No other site's pages**: a request whose `Origin` is another site is refused (DNS rebinding).
- **Offline**: the server is part of PlantCraft, behind the same HTTPS proxy, on the plant's
  network. It never calls out. The assistant is the only thing that may be outside, and where it
  runs is the person's and their IT's decision.

## Protocol

Streamable HTTP, `POST /mcp`, JSON-RPC 2.0, protocol versions `2025-06-18` (preferred),
`2025-03-26` and `2024-11-05`. The server answers each request with one JSON object. It has no
session and no server-sent stream (`GET /mcp` is 405). It serves `initialize`, `ping`,
`tools/list` and `tools/call`; a notification is answered 202. The protocol is written in
`plantcraft/assistant_access/mcp.py` without a new dependency.

## The same tokens in a notebook

While Notebooks are on (docs/en/notebooks.md), a person can also create a token from
Notebooks › Run on your computer, even with the MCP server off. It lets the `plantcraft-notebook`
package read API v1 as that person from Jupyter on their computer, read-only. It is listed and
revoked like any other token.
