# Setup guide

> **Updated:** 2026-11-03

A new installation is empty: no model, no source, no assets. The setup guide is a small robot in
the corner of every screen, for administrators, that walks through it one step at a time and,
with a language model, talks the person through each step and applies what they agree on.

## The steps

| Step | Done when (seen by itself) | What the robot can apply |
| --- | --- | --- |
| Connect a language model | the assistant has a model (Settings › Language models) | nothing: before a model it cannot talk, it points to the page |
| The basics | the installation's time zone was chosen (or fixed by the installation file) | the time zone and the person's language (`POST /api/setup-guide/basics`) |
| Connect the plant's data | a source the person added is connected (the collector says so, or the guide's own test answered) | an OPC UA, PI Web API or CSV source, then a first test (`POST /api/setup-guide/connection`) |
| Add the plant's documents (optional, with Documents) | the person says so | nothing: it explains what to add first |
| Build the asset tree | the tree has assets beyond the plant's root | nothing: it explains Draft from tags on Assets › Import |
| Let the apps start | every app's first step (`[[contributes.start]]`) ran for the newest import | the guide's card runs them (`POST /api/asset-file/start/{app}/{step}`) |
| Invite your team | someone besides the administrator can sign in | a person (`POST /api/users`) |
| Send notifications by email (optional) | the person says so | nothing: it says what IT gives and where it goes |

Any step can be skipped and taken back. The state is computed on every read
(`GET /api/setup-guide`, `plantcraft/api/setup_guide.py`); the guide keeps only the marks (done,
skipped) and its last connection tests, in the preference row of the reserved name `@installation`,
and whether each administrator hid the robot, in their own preferences.

## How the robot talks

Each step has a work on the page `processcraft:setup-guide` (`guide-<step>` in
`plantcraft/assistant_works/platform.py`). "Do it with me" opens the assistant beside the page
with that work and the step's facts (what is set, what failed), so the model never asks what the
screen already knows. A step that writes is a `create` work: the model proposes the fields, the
person checks them on the card and clicks Create, and the guide's route applies them as that
person through the same code as the step's own page (so the checks, the audit log and the errors
are that page's). Passwords never go through the chat.

While its card is open the guide reads the state every 5 seconds, so a step done anywhere moves
it on; closed, every minute. The welcome tour waits until the guide is finished or hidden.

## Try it

```bash
simcraft loops serve                       # the OPC UA plant at opc.tcp://127.0.0.1:4840/plantcraft/
python dev/fake_llm.py --port 11999        # a scripted model that knows only the guide's steps
plantcraft --scenario <a copy of deploy/site/site.json with local paths>
```

Then sign in as an administrator, add the provider "OpenAI-compatible" at
`http://127.0.0.1:11999/v1` with any model name on Settings › Language models, and follow the robot.
