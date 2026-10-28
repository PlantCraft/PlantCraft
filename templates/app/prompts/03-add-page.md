# 03: Add a page

```text
Read AGENTS.md and frontend/src/NotesPage.tsx. Add a page <Page> that shows <what, for whom>,
with <the actions a person takes there>.

- Use @plantcraft/ui only (page header, table with filters, forms, empty and error states, the
  help link); do not restyle it. Every string through t() from frontend/src/i18n.ts.
- Add it to NAV in frontend/src/pages.tsx and to the routes in App.tsx; calls go in api.ts.
- A test in frontend/src/pages.test.tsx, and a browser journey in tests/e2e/ when a person
  completes a task on the page.
- Show me: `make dev`, open the page, take a screenshot with Playwright, look at it, fix what is
  off. `make ci` and `make e2e` green.
```
