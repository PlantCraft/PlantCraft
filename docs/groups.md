# Groups of people

> **Added:** 2026-10-22 (owner decision: groups belong to the platform, every app reuses them)

A group is a name for several people: **U-100 operations**, **Instrumentation and control**. It
lives in PlantCraft once; the apps never keep a copy. They read it through API v1 and refer to
it as `group:<id>`, the same way they refer to a person as `user:<username>`.

| Field | Example | What it is for |
|---|---|---|
| Name | U-100 operations | Shown in pickers, on profiles and in messages |
| Kind | `department`, `area`, `discipline`, `team` or `company` | A part of the organization with its manager, an area of the plant (a unit, a shift), an engineering discipline, any other team, or an outside company working at the plant (an integrator, a contractor) |
| Last day of access (company) | `2026-12-31` | From the next day nobody in the company, or in a group under it, signs in, and their open sessions end (`GroupStore.access_ended`); empty: no end |
| Sponsor at the plant (company) | `rui.planta` | The plant's person who answers for the company (never one of its members); shown in Operations › Partners |
| Under (optional) | `operations` | The group it sits under: groups form a tree |
| Description | Control room and field operators, all shifts | One line about the group |
| Asset (optional) | `U-100` | The part of the asset tree an area group covers (a label: it limits nothing) |
| Assets members see (optional) | `U-100` | The roots of the asset tree the members see: a group with it limits what its members see of the plant ([asset-scope.md](asset-scope.md)) |
| Coordinator (optional) | marina.costa | The group's leader: changes its members without being an administrator, sees the work of the groups below; always a member |
| Members | rafael.souza, marina.costa | People (active ones receive notifications); a person may be in several groups |

## The tree and who sees what

Added 2026-10-23 (owner): groups have a hierarchy, **Operations › U-100 operations › Shift A**.
A group's coordinator leads it and every group below it. `GroupStore.scope(username)` answers
what a person sees of other people's work: their own groups plus every group below one they lead,
and the people of those led groups. Actions use it ([collaboration.md](collaboration.md)); an
administrator sees everything. A group cannot move under itself or a group below it, the tree is
8 levels deep at most, and deleting a group moves the groups under it up a level.

## Where people see them

- **People › Groups** (`/users/groups`, administrators): the groups in tree order, create, edit
  and delete. **People › edit** sets the groups a person is in.
- **A group's page** (`/groups/<id>`, everyone signed in): its members and coordinator; the
  coordinator changes the members there.
- **A person's page** (`/people/<username>`): the groups they belong to.
- References: `#group:<id>` in an action or a message links to the group's page.

## For the apps

- `GET /api/v1/groups` and `GET /api/v1/people` fill the pickers (`RecipientPicker` in
  `@plantcraft/ui`); people come without email or phone.
- `POST /api/v1/notifications` with `group:<id>` reaches every active member
  ([notifications.md](notifications.md)).
- Every change is in the audit log (`group.created`, `group.updated`, `group.members`,
  `group.deleted`).

Routes: `GET /api/groups`, `GET /api/groups/{id}` (everyone signed in), `POST /api/groups`,
`PUT /api/groups/{id}`, `DELETE /api/groups/{id}` (administrators), `PUT /api/groups/{id}/members`
(the coordinator or an administrator). The store is `plantcraft/groups` (layer 1).
