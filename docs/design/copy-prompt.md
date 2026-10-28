# Design note: "Copy as prompt" buttons

> **Status:** built (2026-10-23): `plantcraft_sdk.prompts` (SDK 0.15.0), `CopyPrompt`
> (`@plantcraft/ui` 0.19.0), the plant map in PlantCraft, methods, blocks and algorithms in
> Analytics, Modelica classes in Models. Dashboards and alarms are next.

## Why

PlantCraft is meant to be used with AI (see [how-we-build.md](../how-we-build.md)). Many things
a person sees in the suite are code or data an AI assistant can read, explain, change or rebuild:
an Analytics method's Python, a Modelica model, a twin's configuration, a plant map, a dashboard. Today
the person has to find the source and write the context by hand. A **Copy as prompt** button puts
a ready prompt on the clipboard: the thing itself, the context an assistant needs, and the
question, so the person pastes it into the assistant their plant allows and gets a useful answer
the first time.

Nothing leaves the plant by this button: it only fills the clipboard. Whether and where the person
pastes it is theirs (and their IT's) to decide, which keeps the language model off by default.

## Where it appears (first set)

| Module | Object | What the prompt carries | Default question |
|---|---|---|---|
| Analytics | A method (help page and method list) | The method's Python source, its `@method` declaration (inputs, parameters), the SDK contract it implements, its help page | "Explain this method and how to adapt it" |
| Analytics | A protocol | The protocol's blocks as JSON, the methods it uses | "Review this protocol for this loop type" |
| Models | A Modelica class | The `.mo` text, the classes it extends or uses, the runner's limits | "Explain this model / extend it with ..." |
| Twin | A twin | Its JSON (model, inputs, outputs, checks) and the FMU's variables | "Check this twin's bindings" |
| PlantCraft | Plant map import | The import JSON schema, an example, the asset types and roles | "Build the plant map from these manuals" (exists today as text; becomes the button) |
| Dashboards | A dashboard | Its JSON (cards and signal references) and the card schema | "Add a card that shows ..." |
| Alarms | An alarm | Its JSON and the alarm schema | "Suggest limits and deadband" |

## How it is built (once, for every module)

- **`@plantcraft/ui`: `<CopyPrompt build={() => Promise<Prompt>} />`**, a button with the
  suite's icon and a toast ("Prompt copied: paste it into your AI assistant"). It works without
  the clipboard API (falls back to a dialog with the text selected) and never calls the network.
- **A prompt is data**, built by the module's API so it is tested like any endpoint:
  `GET /api/prompts/<kind>/<id>?question=<preset>` answers
  `{title, text, parts: [{label, kind, content}]}`. The SDK gives the template
  (`plantcraft_sdk.prompts.Prompt`: a header saying what PlantCraft is and the module, the
  parts as fenced blocks with their language, the question, and the house rules an assistant
  should follow: read-only on the plant, inputs by signal role, tests for every change).
- **Size limit**: about 30 000 characters; larger parts are cut with a note of what was left out.
- **No secrets, no plant specifics by accident**: the builder never includes keys, passwords,
  endpoints or user names; tags and asset ids are included only when they are the object itself,
  and the toast says so.
- **Languages**: the header and questions follow the interface language; code stays as is.

## Steps

1. SDK: `plantcraft_sdk.prompts` with the template and a test that no secret field ever enters
   a prompt; UI: `CopyPrompt` with its test.
2. Analytics methods and Models classes first (the two the owner named), then the JSON imports
   (plant map, protocols, twins, dashboards, alarms).
3. A help page per module: "Using this module with an AI assistant".
4. Later, when a plant turns a language model on: the same prompt goes to the configured
   specialist instead of the clipboard.
