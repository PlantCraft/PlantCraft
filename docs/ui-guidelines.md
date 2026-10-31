# Interface rules: one look for the whole suite

The short list every screen of PlantCraft and its apps follows. The detail of each shared piece is in
[app-standard.md, section 10](app-standard.md#10-interface-one-frame-for-every-app); this page is the
checklist to read before drawing a screen and before reviewing one. `tests/test_visual_rules.py`
checks the rules marked *(checked)*.

## Navigation: one place to move

1. **The side menu and the tabs are the only navigation.** A button at the top of a page never goes
   to a page the side menu lists, nor to a tab of the same page *(checked for the menu)*.
2. **An Overview has no buttons at its top**: title, notices, widgets *(checked)*. What the app
   works on is its own page after Overview.
3. Nothing above a page's title (no breadcrumb, no eyebrow) and nothing under it (no line of
   purpose, no description of a dashboard): what a page is for belongs in Help and in its empty
   states. A date or a status that must stay carries `pc-heading-keep`.
4. A link inside the content (an asset, a run, "Open the last run") is fine: it goes to one
   object, not to a menu entry.

## Buttons

5. The page's buttons sit at the right of its title (`Heading`'s `actions`), 8 px apart. At most one
   `button-primary`; the rest `button-secondary`; `button-danger` only to delete or take back;
   `button-ghost` inside rows and cards.
6. Every button is 36 px high (`button-small` 30 px) with a 16 px icon. An icon-only button at the
   top (Refresh, Full screen) is `button button-secondary button-icon` with a title and an
   aria-label. Borderless `icon-button` is for toolbars inside an editor or a panel.
7. Buttons never touch: a row of them is a `heading-actions`, `pc-actions` or `row-actions`, or a
   flex row with `gap: var(--pc-space-2)`.

## Forms

8. A settings page is one `panel form-panel`; each group is a `FormSection` (title and
   explanation left, fields right); fields in `form-grid` (two columns, `field-span` for full
   width, `check` for a checkbox line); Save in a `FormFooter`.
9. Dialogs are the ui's `Dialog`, with `form-grid` and its footer. Asking before an action is
   `confirmAction`, never `window.confirm`; asking for one short text (a name, a number of hours)
   is `askText`, never `window.prompt`; a message after an action (what went wrong, or that
   it worked) is `showToast(text, { tone })`, never `window.alert`.
10. An app never sets its own button heights, gaps or form columns: it asks for a change in `ui/`.

## Lists, widgets, folders and search

11. Tables are `DataTable`, **one line per row**: a second fact goes in its own column, a long
    text is cut with an ellipsis and shown whole on hover or on the object's page. (Older tables
    still stack a `<small>` under a cell; they move to this as their app is reviewed.)
12. A widget row shows the name with "Updated X ago" (or its one detail line) below it.
13. Folders are the shared column at the left (`FolderColumn`), search is the `DataTable` search
    box plus the suite's Ctrl+K search: the same in every app.

## Before a pull request that changes a screen

- Run the app's browser journeys with screenshots (`<APP>_E2E_SCREENSHOTS=folder make e2e`) and
  look at the pages you touched next to another app's page of the same kind.
- `python -m pytest tests/test_visual_rules.py` at the root of the repository.
