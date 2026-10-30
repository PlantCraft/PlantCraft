## What changes

<!-- One or two sentences: what a person sees or can do now. -->

## Why

<!-- The issue, the review note or the problem it answers. A change to the core links an issue
a maintainer agreed to: Closes #123. -->

## Zone

<!-- One zone per pull request (CONTRIBUTING.md, "What is core and what is open"). -->

- [ ] One app (`apps/<app>`, `simulator`, `templates/app`)
- [ ] Content: methods, blocks, examples, docs or translations
- [ ] Core (`plantcraft/`, `frontend/`, `sdk/`, `ui/`, API v1, `deploy/`, CI), with its issue: #

## Checked

- [ ] `make ci` passes in each area this touches (root and `apps/<app>`)
- [ ] Docs, CHANGELOG and translations follow the change
- [ ] A change to API v1 went through `make api-contract`
