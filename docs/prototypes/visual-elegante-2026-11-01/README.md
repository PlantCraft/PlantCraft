# Prototype: a more refined look (2026-11-01), not for merge

Three stylesheets injected over the real Analytics pages (Overview, a loop, Results, New monitor),
to compare looks before changing `@plantcraft/ui`. The palette is unchanged.

- `refinado.css` (A): tokens only (radii, shadows, lines, title tracking, motion curve).
- `elegante.css` (B): A plus templates for the shared components (sidebar, cards, numbers,
  status, tabs, filters, tables, forms, charts).
- `estudio.css` (C): B with a light sidebar, for comparison only.

How to reproduce: copy `hold_server_test.py` into `apps/link/tests/e2e/`, run it with pytest
(it keeps the e2e server up and writes its URL and a fresh token to `/tmp/claude-0/proto/server.json`),
then `python shoot.py antes,refinado,elegante,estudio light,dark` and `python compose.py`
from a folder holding the CSS files.
