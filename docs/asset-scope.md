# Asset scope: who sees which part of the plant

> **Added:** 0.5.0

Access has three axes. The **level** says what a person may do (dashboards, viewer, editor,
admin). The **apps** say where. The **asset scope** says which part of the plant: a contractor of
one unit, or a utilities engineer who should not see U-200, sees only the assets under the roots
an administrator gives them, and everything that hangs from those assets.

## Who has a scope

| Holder | Set in | Meaning |
|---|---|---|
| Person | People › edit › *Assets they see* | The roots of the asset tree they see |
| Group | People › Groups › edit › *Assets members see* | The roots every member sees |

What a person finally sees is the union of their own roots and the roots of every group they are
in **that has a scope**. A group without a scope adds nothing: putting someone in *Shift A* never
widens nor narrows what they see. With no roots anywhere a person sees the whole plant, as before
scopes existed.

- Administrators always see the whole plant, whatever is stored for them.
- An app's own token (`app:<id>`) is not a person: it reads the whole plant, because an app
  computes for everyone. An app that answers a person applies that person's scope (below).
- A root and everything under it is in scope; the asset above a root is not, so for the person
  the tree starts at their roots.
- People › list shows the result in the **Plant** column ("Whole plant" or "N assets and below").
- Joining or leaving a group with a scope changes what a person sees, so only an administrator
  changes the members of such a group (its coordinator manages the members of other groups).

## What follows the assets

| Item | In scope when |
|---|---|
| Asset | It is a root or under one |
| Signal | It is bound to an asset in scope; a derived signal, when its subject is |
| Result, event, run | Its subject (`asset:` or `signal:`) is in scope; an event about no plant item stays visible |
| Action | The person owns or created it, or it names no asset or signal, or one of those it names is in scope (and the usual rule of who sees an action holds, [collaboration.md](collaboration.md)) |
| Reference (`#asset:FIC-101`) | The asset or signal is in scope; otherwise it reads as "Asset FIC-101", like an action of another group |

A signal bound to no asset is out of every scope: a contractor never reads a tag nobody placed.
For the same reason a person with a scope binds only signals they already see to an asset.

Out of scope means **not there**: the platform answers 404 (as for something that does not exist)
and lists leave it out. The search, an asset's page and history, the tree's counts, references,
the assistant and the specialists all read through these rules.

## In the token

A person's API v1 token carries their roots in the claim `assets` (a list of asset ids). With no
claim the person sees the whole plant. Any change of a person's scope, of a scoped group or of its
members ends the tokens issued before it (`tokens_valid_after`), as a change of level or apps
does, so a token never says more than the person may now see.

PlantCraft itself does not trust the claim: it reads the scope from its database on every request.
The claim is for apps that answer people from their own stores (the Historian's trends, View's
panels): they read the roots from the token and keep the assets under them.

## In the apps

`plantcraft-sdk` 0.66.0 gives every app the same helper, `plantcraft_sdk.asset_scope`. An
app's runtime calls `asset_scope(user)` (or `claims_scope(claims, token)` for a bare token): for a
person with the claim it asks PlantCraft, with that person's own token, which assets and signals
they see (`/api/v1/assets` and `/api/v1/signals`, already filtered here) and keeps the answer a
minute; for everyone else it answers "the whole plant" without a request. If PlantCraft cannot
answer, a limited person sees nothing of the plant rather than all of it. The scope answers
`asset(id)`, `signal(id)`, `subject("asset:<id>")`, `refs([...])` and `all_signals([...])`;
`limited(user)` says whether a person has a scope at all.

What each app keeps to the person's part (anything else answers 404 or is left out of lists):

| App | What follows the scope |
|---|---|
| Historian | the direct reads (`/api/v1/signals`, series, values, batches), the Points pages and their trends, the trend and point widgets, the search, the CSV of points, the export package |
| View | saved dashboards and reports read as the person (never with View's own token), so a card on another part says it cannot read; kept PDFs are the person's own or those its editors sent them |
| Analytics | loops (the asset of the same id, or every signal of a loop defined there), results, runs, executions and their groups, signal quality, the asset page, the search, the widgets |
| Alarms | alarms on the part's assets or signals: lists, summary, journal, performance, the asset page, the search, notifications sent, actions (acknowledge, shelve, out of service) |
| Models | simulations and studies fed by plant signals: seen by who sees every signal they read; a simulation on no plant data is everyone's |
| Documents | a document about assets (linked or confirmed by a person) only when one of them is in the part, in the list, the page, the search and the assistant's tools; a document about no asset is everyone's |

A public link or a scheduled send reads later with the app's own token, past the person's part,
so a limited person does not set one up: View answers 403 to a new public link, to a report with
a schedule and to a change of a scheduled report.
