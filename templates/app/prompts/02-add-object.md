# 02: Add an object

```text
Read AGENTS.md. Add the object <object> to the app: <fields with their limits>, linked to
<the asset | a signal | another object of the app> by id.

- Contract and store in a new package src/<app>/<object>s/ (pydantic model with every limit,
  a Store subclass with its SCHEMA, a service with its rules, as src/<app>/notes/ does), in
  layer 2 of AGENTS.md (docs/backend.md, docs/data.md).
- Routes in api/routers/<object>s.py: list, get, create, change, delete; editors write, viewers
  read (api/deps.py); every change audited as <app>.<object>.<verb>; bad input 422 with a
  message a person can act on, never a 500.
- If people should find it with Ctrl+K, follow docs/recipes/search.md.
- Tests in tests/test_<object>s.py, written first; update LAYERS in tests/test_suite_rules.py
  and the operations floor in tests/floors.toml.
- `make ci` green, then a line in docs/devlog.md and CHANGELOG.md.
```
