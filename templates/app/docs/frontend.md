# The interface

The interface is a Vite + React + TypeScript app on `@plantcraft/ui`, the suite's shared
interface. It is built into `frontend/dist` and served by the app under its prefix. Every app of
the suite looks and behaves the same because they all draw the same frame and blocks: use them,
and do not restyle them.

```sh
cd frontend && npm ci && npm run dev     # Vite on its own port, for quick work on a page
make frontend                            # what CI runs: install, build, test
```

`@plantcraft/ui` is installed from `vendor/plantcraft-ui-<version>.tgz`, never from the npm
registry; the build needs no internet.

## The frame

`App.tsx` draws `SuiteShell`: the sidebar with the app's pages, the launcher to the other apps,
the search (Ctrl+K), messages, the profile menu, help and the guided tour. You give it:

```tsx
<SuiteShell
  app="starter"                 // the app id
  appName="StarterCraft"        // the name in the frame and the browser tab
  nav={NAV}                     // the sidebar (pages.tsx)
  path={path} href={href} navigate={navigate}
  user={me ? { name: me.name, role: t(me.role) } : null}
  helpTo="/help"
  tour={tour}
>
  {/* the page for the current path */}
</SuiteShell>
```

The routes are a plain function of the path (`Route` in `App.tsx`): no router library. `nav.ts`
keeps paths under the prefix: `href("/notes/1")` is `/starter/notes/1`, `navigate()` changes page
without a reload, `Link` is an `<a>` that does both.

## A page

A page is a component that loads its data through `api.ts` and shows one of three states:

```tsx
export function NotesPage({ me }: { me: Me }) {
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.notes().then(setNotes).catch((err) => setError(message(err))); }, []);
  if (error) return <ErrorBox text={error} />;
  if (!notes) return <Loading />;
  return <>
    <Heading eyebrow={t("Starter")} title={t("Notes")} detail={t("Notes on the plant's assets, newest first.")} />
    {me.can_edit && <NoteForm onSaved={...} />}
    <NoteList notes={notes} />
  </>;
}
```

To add a page: the component in its own file, its path in `Route` (`App.tsx`), its entry in `NAV`
(`pages.tsx`, with an icon from `lucide-react`), its calls in `api.ts` and its types in
`types.ts`. Show the editing controls only when `me.can_edit`; the server refuses anyway.

## The blocks you will use most

| Block | For |
|---|---|
| `Heading` | The page header: eyebrow, title, one line of detail |
| `DataTable` | Every list: sort, filter by column, search, pages, an empty state |
| `ErrorBox`, `Loading` | The error and loading states |
| `FormSection`, `FormFooter`, and the `panel`, `form-grid`, `button` classes | Forms |
| `ConfirmDialog` / `confirmAction`, `askText`, `showToast` | Confirmations, a quick question, a short notice |
| `PageTabs` | Tabs inside a page |
| `AssetSearch`, `SignalSearch`, `SourcePicker` | Picking an asset or a signal from PlantCraft |
| `PeriodPicker`, `timeFigure`, `Plot` | Time windows and charts of signals |
| `Pill`, `Health` | A status (`ok`, `warning`, `alarm`, `unknown`) |
| `formatAgo`, `formatDate`, `formatNumber` (from `./i18n`) | Times and numbers as the whole suite writes them |

The list of everything is `ui/src/index.ts` in the PlantCraft repository, and the official apps
(`apps/` there) show each block in use.

## Calling the server

`api.ts` creates one client for the app:

```ts
const client = createApiClient({ app: "starter", href });
export const api = {
  notes: (asset?: string) => request<Note[]>(`/api/notes${query({ asset })}`),
  create: (draft: NoteDraft) => request<Note>("/api/notes", jsonBody("POST", draft)),
  remove: (noteId: string) => request<void>(`/api/notes/${id(noteId)}`, { method: "DELETE" }),
};
```

The client sends the person's token, renews it, and sends the browser to sign in when it expires.
An error carries the server's `detail`; `message(err)` turns it into the line a person reads.

## Help and the guided tour

- **Help**: every Markdown file in `docs/help/` is a help page, served by `/api/help` and shown
  under Help. List each page with its folder in `HELP_CATEGORIES` (`src/starter/meta.py`).
- **Tour**: `tourSteps()` in `pages.tsx` opens the first time a person opens the app. Each step
  points at an element of a page; wrap its words in `tt()` so the tour can be translated.

## Rules

- No outside URLs at run time: no CDN, web font or image from the internet. Fonts, icons and
  scripts are bundled. `tests/test_suite_rules.py` fails on them.
- Every string a person reads goes through `t()` ([translations.md](translations.md)).
- No copies of the shared blocks: `tests/test_suite_rules.py` fails on a file that redoes what
  `@plantcraft/ui` already has.
- The page works on a phone: `DataTable` and the frame already fold; check your own layouts at
  narrow widths (`tests/e2e/test_display_sizes.py`).
