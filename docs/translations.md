# Translations

The suite is written in English. Every text a person reads is English in the code, wrapped in
`t()`, and is its own catalog key; a translation is a catalog file next to the code that uses it.
A text missing from a catalog shows in English. Brazilian Portuguese (`pt-BR`) is the first
language; another one is a new catalog file per module plus its line in the language lists below.

## Switched off by default

An installation offers other languages only when `PLANTCRAFT_TRANSLATIONS=1`. PlantCraft then
sets the `plantcraft_translations` cookie for every page of the suite (the apps share its
origin); without it every page draws English and the language setting shows English only.

## One language for the whole suite

A person picks the language once (Preferences, or the top bar of PlantCraft). The choice is kept
in this browser and in the `processcraft_language` cookie, so every app draws in it and every
server answers in it, downloads and reports included. App servers take the page's choice only
(`X-Language` header or that cookie), never the browser's own `Accept-Language`.

## Where the catalogs are

| Module | Screens | Server |
| --- | --- | --- |
| Shared components | `ui/src/locales/<lang>.json` | |
| SDK | | `sdk/python/plantcraft_sdk/locales/<lang>.json` |
| PlantCraft | `frontend/src/locales/<lang>.json` | `plantcraft/i18n/locales/<lang>.json` |
| An app | `apps/<app>/frontend/src/locales/<lang>.json` | `apps/<app>/src/<package>/locales/<lang>.json` |

Each is a flat JSON object, English text to translation, and a translation keeps the `{name}`
fields of its English text. A module's catalog is merged over the shared one under it: an app's
screens over the shared components', an app's server over the SDK's.

## How a module uses them

- Screens: `i18n.ts` calls `createI18n({ "pt-BR": catalog })` from `@plantcraft/ui` and exports
  its `t` and `locale` (`Intl` and `localeCompare` use `locale`). The shared components take the
  same translator.
- Server: the app's `i18n.py` calls `use_catalogs(Path(__file__).with_name("locales"))` and
  re-exports `t` from `plantcraft_sdk.i18n`; the app server sets each request's language
  (`LanguageMiddleware`, added by `plantcraft_sdk.server.web.mount`).
- Text is translated when it is produced (`t()` inside the function, not at import).

## The check

`python -m plantcraft_sdk.i18n_check <folder>` finds every `locales` folder under the folder and
counts the English texts its code passes to `t()` against each catalog. It fails on a broken
catalog (not flat, an empty translation, `{fields}` that differ). `--missing` lists what is not
translated; `--strict` also fails on it, the gate once a language is complete. `make ci` runs it
for the platform (`make i18n`) and in every app (`make standard`).
