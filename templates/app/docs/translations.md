# Translations

English is the source of every string a person reads, and it is also the key of the
translation catalogs. Other languages are translations. The suite ships Brazilian Portuguese
(`pt-BR`); PlantCraft decides which language each person sees, for every app at once.

## In the server

```python
from starter.i18n import t

raise HTTPException(404, t("Note not found."))
raise HTTPException(422, t("No asset {asset} in PlantCraft.", asset=asset_id))
```

Call `t()` when the text is produced (inside the function), never at import: the language comes
with each request. The catalog is `src/starter/locales/pt-BR.json`.

## In the interface

```tsx
import { t } from "./i18n";

<h2>{t("New note")}</h2>
<p>{t("Written by {who}, {when}.", { who: note.created_by, when: formatAgo(note.created_at) })}</p>
```

The catalog is `frontend/src/locales/pt-BR.json`. Use `locale` from `./i18n` for `Intl` and
`localeCompare`, and the `format*` helpers for numbers and dates. The tour's words use `tt()`.

## Catalogs

A catalog is a flat JSON object, English to the translation:

```json
{
  "Note not found.": "Nota não encontrada.",
  "No asset {asset} in PlantCraft.": "Não há ativo {asset} no PlantCraft."
}
```

Keep the `{fields}` exactly as in English. Strings the SDK and `@plantcraft/ui` already
translate (sign-in, errors of the frame, the table's buttons) are theirs; do not repeat them.

## The check

`make ci` runs `python -m plantcraft_sdk.i18n_check --strict .`: it finds every `t("...")` in the
code and fails when a catalog is broken (not flat, an empty translation, `{fields}` that differ
from the English) or misses a string. `--missing` lists what is not translated.

## Help pages

A help page in another language sits in a folder named after the language, next to the English
one: `docs/help/pt-BR/<page>.md`. A page without a translation shows in English, so the English
page is the one that must always be there. Product names are never translated; PlantCraft's
`docs/translations-glossary-pt-BR.md` keeps one word for each meaning.

## Another language

The suite's languages are listed by PlantCraft (`SUITE_LANGUAGES`). For a new language, add
`locales/<code>.json` in both places and, when the app package format of PlantCraft PR #179 is
released, list it in `app.toml` `[app] languages` ([packaging.md](packaging.md)).
