"""What an app adds to PlantCraft, declared once in its ``app.toml`` (``docs/app-standard.md``,
section 4b).

A new app must reach every place of the platform without a change to the platform. So an app
says in ``[contributes]`` what PlantCraft draws for it, and in ``[[publishes.series]]`` the
series it writes to the Historian; PlantCraft keeps the declarations in its registry (one per
app, ``PUT /api/v1/contributions``, sent by the SDK's server when the app starts, beside the
event catalog) and every screen reads the registry instead of asking each app::

    [[contributes.llm]]                  # a use of a language model (Setup > Language models)
    id = "algorithm-draft"
    title = "Draft an algorithm"
    description = "Builds an algorithm from what a person describes."
    reads = "The description and the block catalog; no plant data."
    default = "default"                  # the default model, or "off" until an admin picks one

    [[contributes.widgets]]              # a card of the Overviews and of Desk's Today
    id = "worst-assets"                  # served at <prefix>api/widgets/<id> (docs/widgets.md)
    title = "Worst assets"
    size = "m"
    kind = "list"                        # number, list, split, series or facts
    default = true
    # pick = "Asset"                     # about one thing the person picks (<id>/options)

    [contributes.search]                 # answers <prefix>api/search (Ctrl+K)
    types = ["Block", "Algorithm", "Loop"]

    [[contributes.calendar]]             # a feed of dated items in Desk's calendar
    id = "reviews"
    title = "Loop reviews"

    [[contributes.todo]]                 # a kind of to-do the app may give people
    id = "review-schedule"
    title = "Review a schedule"

    [[contributes.refs]]                 # #protocol:<id> in messages, actions and notes
    kind = "protocol"
    title = "Algorithm"
    url = "/link/algorithms/{id}"

    [[contributes.settings]]             # an installation setting, drawn in Setup > Apps
    key = "workers"
    title = "Workers"
    type = "integer"
    default = 2
    min = 1
    max = 16

    [[contributes.setup]]                # a page of the app listed in PlantCraft's Setup
    title = "Sources"
    path = "/hist/sources"

    [contributes]
    queue = true                         # answers <prefix>api/queue (the suite's work queues)

    [[contributes.assistant.works]]      # what the assistant does on one of the app's pages
    id = "new-block"                     # the work linkcraft:new-block
    pages = ["blocks", "block-new"]      # the page ids the app's pages name in useAssistantPage
    kind = "create"                      # "ask": reads and explains; "create": proposes an object
    title = "Create a block with the assistant"
    instructions = "Collect the block's name, inputs, outputs and formula, then propose it."
    object = "block"
    create = "/link/api/blocks"          # POSTed with the person's session when they click Create
    open = "/link/blocks/{id}"           # the new object's page ("id" of the route's answer)
    [[contributes.assistant.works.fields]]
    key = "name"
    title = "Name"
    required = true

    [[contributes.assistant.tools]]      # a read-only tool the assistant may call (SDK 0.61.0)
    id = "search_documents"              # the model sees doccraft_search_documents
    title = "Search the plant documents"
    description = "Manuals and guides of the plant: causes, procedures, limits. Cite what you use."
    reads = "Passages of the documents the person may open."
    prefetch = "query"                   # called with each question before the model answers (0.73.0)
    [[contributes.assistant.tools.args]] # served as POST <prefix>api/assistant/tools/<id>
    key = "query"
    type = "text"
    title = "What to find"
    required = true

    [[contributes.objects]]              # a kind of object notebooks list, read and run
    kind = "block"                       # served at <prefix>api/objects/block[/<id>]
    title = "Block"
    run = "local"                        # local: on the person's computer; app: in the app's queue

    [contributes.notebooks]              # the app's examples and what runs its objects locally
    examples = true                      # served at <prefix>api/notebooks/examples
    runtime = ["linkcraft", "plantcraft_sdk"]  # packages copied to the person's computer
    entry = "linkcraft.notebook"         # its run(kind, item, plant, app, **options)

    [[contributes.start]]                # a first step once a plant's assets exist (SDK 0.65.0)
    id = "analyze-loops"                 # served as POST <prefix>api/start/<id> (StartIn, StartOut)
    title = "Monitor the loops"
    description = "Reads the loops the import wrote and queues their first monitoring round."
    open = "/link/loops"                 # where the person sees what the step did

    [[publishes.series]]                 # series written to the Historian, in its format
    name = "{schedule}.{output}"
    title = "Schedule outputs"
    type = "number"
    per = "asset"
    retention = "app"

Every table is checked here (``plantcraft-app check`` runs it in CI): unknown keys, repeated
ids and out-of-range values are errors. Only fields are ever added to these tables; PlantCraft
skips, with a warning, a table it does not know (an app newer than the platform), and tells
apps what it offers in ``GET /api/v1/installation`` (``features``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from plantcraft_sdk.events import EventSpec, parse_specs
from plantcraft_sdk.scopes import declared

# The version of the [contributes] tables PlantCraft reads; a new field never changes it.
CONTRIBUTES_VERSION = 1

# What a PlantCraft names in ``features`` of ``GET /api/v1/installation`` (SDK 0.31.0): the
# tables of [contributes] it draws today. An app hides what its platform lacks.
FEATURES = (
    "contributions",
    "llm",
    "widgets",
    "search",
    "calendar",
    "todo",
    "refs",
    "settings",
    "setup",
    "queue",
    "series",
    "assistant",
    "objects",
    "notebooks",
    "assistant_tools",
    "start",
)

SLUG = r"^[a-z][a-z0-9-]{0,40}$"
# A reference kind of the suite (plantcraft.refs): letters and "_", no digits.
REF_KIND = r"^[a-z][a-z_]{1,31}$"
# Kinds PlantCraft owns; an app names its own objects.
PLATFORM_REF_KINDS = (
    "action",
    "app",
    "asset",
    "conversation",
    "event",
    "execution",
    "group",
    "job",
    "loop",
    "note",
    "run",
    "signal",
    "todo",
    "user",
)
SETTING_KEY = r"^[a-z][a-z0-9_]{0,39}$"
# The kinds of value a Historian point holds (apps/historian kinds.py) and the series per run.
SERIES_TYPES = ("number", "integer", "boolean", "text", "instant", "structured", "run_series")
SERIES_NAME = re.compile(r"^[a-z{][a-z0-9_.{}-]{0,79}$")

Slug = Annotated[str, StringConstraints(pattern=SLUG)]
Title = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]
Description = Annotated[str, StringConstraints(max_length=600, strip_whitespace=True)]
# A path on the suite's host: "/" first, no scheme, host or "..".
Path = Annotated[str, StringConstraints(pattern=r"^/[A-Za-z0-9._~/{}-]{0,199}$")]


class _Table(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _once(items: list[Any], field: str, what: str) -> None:
    names = [getattr(item, field) for item in items]
    twice = sorted({name for name in names if names.count(name) > 1})
    if twice:
        raise ValueError(f"{what} declared more than once: {', '.join(twice)}")


class LlmUse(_Table):
    """A use of a language model: PlantCraft lists it in Setup > Language models, where an
    administrator picks its model (or the default, or off); the app calls it through the
    platform (``POST /api/v1/llm/<app id>:<id>``) and never holds a key."""

    id: Slug
    title: Title
    description: Description = ""
    # What the use sends to the model, in words, for the administrator who decides.
    reads: Description = ""
    default: Literal["default", "off"] = "default"


class WidgetSize(_Table):
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=3)


class Widget(_Table):
    """A widget of the app's Overview and PlantCraft's boards; its data stays at
    ``<prefix>api/widgets/<id>`` (``docs/widgets.md``)."""

    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")]
    title: Title
    description: Description = ""
    size: Literal["s", "m", "l"] = "m"
    sizes: list[WidgetSize] = Field(default_factory=list, max_length=3)
    default: bool = False
    # The shape its data takes (plantcraft_sdk.widgets): number, list, split, series, facts.
    kind: Literal["number", "list", "split", "series", "facts", "bars", "columns", "tiles"] = "list"
    # A widget about one thing the person picks ("Schedule", "Point"): its choices are served at
    # <prefix>api/widgets/<id>/options and its data at <prefix>api/widgets/<id>?item=<value>.
    pick: Annotated[str, StringConstraints(max_length=40, strip_whitespace=True)] = ""
    # May be placed more than once on one board (always, with ``pick``).
    multiple: bool = False


class Search(_Table):
    """The app answers ``<prefix>api/search``; ``types`` are the kinds of object it finds."""

    types: list[Title] = Field(default_factory=list, max_length=20)


class CalendarFeed(_Table):
    """A feed of dated items the app keeps in Desk's calendar (``PUT /api/v1/calendar/<id>``)."""

    id: Slug
    title: Title
    description: Description = ""
    # Shown to a person until they hide it; false: a chip they switch on.
    visible: bool = True


class TodoKind(_Table):
    """A kind of to-do the app may give a person or a group (``POST /api/v1/todos``)."""

    id: Slug
    title: Title
    description: Description = ""


class RefKind(_Table):
    """A kind of reference the app owns (``#<kind>:<id>``): PlantCraft asks
    ``<prefix>api/refs/<kind>/<id>`` for its name and state, and links ``url``."""

    kind: Annotated[str, StringConstraints(pattern=REF_KIND)]
    title: Title
    # The object's page; "{id}" is replaced by the reference's id.
    url: Path

    @model_validator(mode="after")
    def _own(self) -> RefKind:
        if self.kind in PLATFORM_REF_KINDS:
            raise ValueError(f"reference kind {self.kind!r} belongs to PlantCraft")
        if "{id}" not in self.url:
            raise ValueError('url holds "{id}", where the reference\'s id goes')
        return self


class Setting(_Table):
    """An installation setting of the app, drawn by PlantCraft in Setup > Apps and read by the
    app at ``GET /api/v1/contributions/settings``. Work settings (a rule's limits) stay in the
    app's own pages."""

    key: Annotated[str, StringConstraints(pattern=SETTING_KEY)]
    title: Title
    help: Description = ""
    type: Literal["text", "number", "integer", "boolean", "choice"] = "text"
    default: str | int | float | bool | None = None
    options: list[Title] = Field(default_factory=list, max_length=30)
    min: float | None = None
    max: float | None = None
    unit: Annotated[str, StringConstraints(max_length=20)] = ""
    # Only an administrator reads it back (a token, a password); never shown again.
    secret: bool = False

    @model_validator(mode="after")
    def _typed(self) -> Setting:
        if self.type == "choice":
            if not self.options:
                raise ValueError(f"setting {self.key!r} of type choice lists its options")
            if self.default is not None and self.default not in self.options:
                raise ValueError(f"default of {self.key!r} is one of its options")
        elif self.options:
            raise ValueError(f"only a setting of type choice has options ({self.key!r})")
        if self.default is not None:
            expected = {
                "text": (str,),
                "number": (int, float),
                "integer": (int,),
                "boolean": (bool,),
                "choice": (str,),
            }[self.type]
            if not isinstance(self.default, expected) or (
                self.type in ("number", "integer") and isinstance(self.default, bool)
            ):
                raise ValueError(f"default of {self.key!r} is a {self.type}")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min of {self.key!r} is not above its max")
        if (self.min is not None or self.max is not None) and self.type not in (
            "number",
            "integer",
        ):
            raise ValueError(f"only a number has min and max ({self.key!r})")
        return self


def setting_value(spec: Setting | Mapping[str, Any], value: Any) -> Any:
    """``value`` checked against the setting it is for (its type, options, min and max); None
    clears it (the app reads its default again). Raises ValueError with a sentence to show."""

    setting = spec if isinstance(spec, Setting) else Setting.model_validate(dict(spec))
    if value is None:
        return None
    kind = setting.type
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{setting.title} is on or off.")
        return value
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{setting.title} is a number.")
        if kind == "integer":
            if float(value) != int(value):
                raise ValueError(f"{setting.title} is a whole number.")
            value = int(value)
        if setting.min is not None and value < setting.min:
            raise ValueError(f"{setting.title} is {setting.min:g} at least.")
        if setting.max is not None and value > setting.max:
            raise ValueError(f"{setting.title} is {setting.max:g} at most.")
        return value
    if not isinstance(value, str):
        raise ValueError(f"{setting.title} is a text.")
    if kind == "choice" and value not in setting.options:
        raise ValueError(f"{setting.title} is one of: {', '.join(setting.options)}.")
    if len(value) > 2000:
        raise ValueError(f"{setting.title} has 2,000 characters at most.")
    return value


class SetupPage(_Table):
    """A page of the app PlantCraft's Setup lists (the app's sources, its alarm philosophy)."""

    title: Title
    path: Path
    description: Description = ""


class SeriesSpec(_Table):
    """Series the app writes to the Historian, in the Historian's format (``docs/api-v1.md``,
    "Data layer"). ``name`` is the pattern of the point names (``{schedule}.{output}``)."""

    name: Annotated[str, StringConstraints(pattern=SERIES_NAME.pattern)]
    title: Title
    description: Description = ""
    type: Literal[SERIES_TYPES] = "number"  # type: ignore[valid-type]
    unit: Annotated[str, StringConstraints(max_length=20)] = ""
    # What one point is about: an asset (a result asset under it), a signal, or the app.
    per: Literal["asset", "signal", "app"] = "asset"
    # Who sets how long it is kept: the app (per point, managed_by), else the Historian's
    # default; a number of days (0: forever) fixes it.
    retention: Literal["app", "historian"] | Annotated[int, Field(ge=0, le=36500)] = "historian"


WORK_FIELD_TYPES = (
    "text",
    "long_text",
    "number",
    "integer",
    "boolean",
    "choice",
    "date",
    "datetime",
    "list",
)
# Access levels of the suite (plantcraft.auth.access), lowest first.
LEVELS = ("viewer", "editor", "admin")


class WorkField(_Table):
    """A field of the object a "create" work proposes. The assistant asks for it, the platform
    checks the proposal with these rules (``check_fields``) and the person sees it on the card;
    the app's own route still checks the object when the person clicks Create."""

    key: Annotated[str, StringConstraints(pattern=SETTING_KEY)]
    title: Title
    help: Description = ""
    type: Literal[WORK_FIELD_TYPES] = "text"  # type: ignore[valid-type]
    required: bool = False
    options: list[Annotated[str, StringConstraints(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=60
    )
    max_length: int = Field(default=2000, ge=1, le=20000)
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _typed(self) -> WorkField:
        if (self.type == "choice") != bool(self.options):
            raise ValueError(f"field {self.key!r}: a choice lists its options, other types none")
        if (self.min is not None or self.max is not None) and self.type not in (
            "number",
            "integer",
        ):
            raise ValueError(f"only a number has min and max ({self.key!r})")
        return self


class AssistantWork(_Table):
    """Something the assistant does on some of the app's pages: it reads and
    explains (``ask``) or collects fields and proposes an object the person creates with one click
    (``create``; the model itself never writes). ``docs/assistant.md``, "Works"."""

    id: Slug
    pages: list[Slug] = Field(min_length=1, max_length=20)
    kind: Literal["ask", "create"] = "ask"
    title: Title
    hint: Description = ""
    # What the model is asked to do (the person can read it: "See the context").
    instructions: Annotated[
        str, StringConstraints(min_length=1, max_length=2000, strip_whitespace=True)
    ]
    # The person completes the question first ("Which signal?").
    ask: Annotated[str, StringConstraints(max_length=120, strip_whitespace=True)] = ""
    # The lowest access level offered the work. A "create" work says the level its route takes
    # (an editor for shared objects, a viewer for their own, like a calendar event); the route
    # checks it again when the person clicks Create.
    level: Literal[LEVELS] = "viewer"  # type: ignore[valid-type]
    object: Annotated[str, StringConstraints(max_length=60, strip_whitespace=True)] = ""
    fields: list[WorkField] = Field(default_factory=list, max_length=40)
    create: Path | None = None
    open: Path | None = None
    # Or, for an object a person finishes in its own form (a block's code, an algorithm's
    # diagram): the page the card's button opens with the fields as a draft; the person saves there.
    # create, open and form may hold "{subject}", the id of the page's object (a work that
    # changes the block on screen opens /link/blocks/{subject}/edit).
    form: Path | None = None
    # What of the page the work sends ("a specific context for each
    # question"): the keys of the page's facts and view it keeps. Empty sends them all; the
    # place, the subject's name and the person always go.
    context: list[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,40}$")]] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def _kind(self) -> AssistantWork:
        _once(self.fields, "key", f"field of work {self.id!r}")
        if self.kind == "create":
            if not (self.object and self.fields and (self.create or self.form)):
                raise ValueError(
                    f"create work {self.id!r} names its object, fields and create route or form"
                )
            if self.create and self.form:
                raise ValueError(f"create work {self.id!r} has a create route or a form, not both")
            if self.form and self.open:
                raise ValueError(f"the form of {self.id!r} opens the object itself (no open)")
            if self.open is not None and "{id}" not in self.open:
                raise ValueError(f'open of {self.id!r} holds "{{id}}"')
        elif self.fields or self.create or self.open or self.form:
            raise ValueError(f"only a create work has fields, create, open and form ({self.id!r})")
        return self


class AssistantOffer(_Table):
    """One of PlantCraft's works the app offers on some of its pages, such as creating an action
    from an alarm: the work and its create route stay PlantCraft's, the page is the app's."""

    work: Slug
    pages: list[Slug] = Field(min_length=1, max_length=20)


TOOL_ID = r"^[a-z][a-z0-9_]{1,40}$"


class ToolArg(_Table):
    """One argument of an app's assistant tool: the model fills it, PlantCraft checks its type."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,30}$")]
    type: Literal["text", "integer", "boolean", "ref"] = "text"
    title: Title
    required: bool = False


class AssistantTool(_Table):
    """A read-only tool an app offers the assistant (plan "Documents", D7):
    PlantCraft lists it to the model as ``<app id>_<id>`` and calls
    ``POST <prefix>api/assistant/tools/<id>`` with the arguments, as the person who asks, so the
    app's own access decides the answer. ``docs/assistant.md``, "Tools the apps add"."""

    id: Annotated[str, StringConstraints(pattern=TOOL_ID)]
    title: Title
    # What the model reads to decide when to call it: say what it holds and when to use it.
    description: Annotated[
        str, StringConstraints(min_length=20, max_length=600, strip_whitespace=True)
    ]
    # What it reads, shown to administrators beside the app's permissions.
    reads: Description = ""
    args: list[ToolArg] = Field(default_factory=list, max_length=8)
    # The key of a text argument (SDK 0.73.0): PlantCraft calls the tool with the person's
    # question in it before the model answers, and hands the model what it returns, so a small
    # model that would not pick the tool still reads it (pre-retrieval). For a search that is
    # cheap and answers most questions about the app's objects; the model may still call it.
    prefetch: str = ""

    @model_validator(mode="after")
    def _args(self) -> AssistantTool:
        _once(self.args, "key", f"argument of tool {self.id!r}")
        if self.prefetch and not any(
            arg.key == self.prefetch and arg.type == "text" for arg in self.args
        ):
            raise ValueError(
                f"tool {self.id!r}: prefetch names {self.prefetch!r}, which is not one of its "
                "text arguments"
            )
        return self


class AssistantTable(_Table):
    works: list[AssistantWork] = Field(default_factory=list, max_length=60)
    offers: list[AssistantOffer] = Field(default_factory=list, max_length=20)
    tools: list[AssistantTool] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _unique(self) -> AssistantTable:
        _once(self.works, "id", "assistant work")
        _once(self.offers, "work", "offered work")
        _once(self.tools, "id", "assistant tool")
        return self


def fields_schema(fields: list[WorkField] | list[Mapping[str, Any]]) -> dict[str, Any]:
    """The JSON Schema of a create work's fields, for the model's ``propose`` tool."""

    properties: dict[str, Any] = {}
    required: list[str] = []
    for raw in fields:
        field = raw if isinstance(raw, WorkField) else WorkField.model_validate(dict(raw))
        kind = {
            "number": {"type": "number"},
            "integer": {"type": "integer"},
            "boolean": {"type": "boolean"},
            "list": {"type": "array", "items": {"type": "string"}},
            "date": {"type": "string", "format": "date"},
            "datetime": {"type": "string", "format": "date-time"},
            "choice": {"type": "string", "enum": list(field.options)},
        }.get(field.type, {"type": "string", "maxLength": field.max_length})
        description = field.title + (f": {field.help}" if field.help else "")
        properties[field.key] = {**kind, "description": description}
        if field.required:
            required.append(field.key)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def check_fields(
    fields: list[WorkField] | list[Mapping[str, Any]], values: Any
) -> tuple[dict[str, Any], list[str]]:
    """A proposal's values checked against the work's fields: the clean values and the problems,
    one sentence each (missing, unknown, wrong type, not an option, out of range)."""

    specs = [
        raw if isinstance(raw, WorkField) else WorkField.model_validate(dict(raw)) for raw in fields
    ]
    if not isinstance(values, Mapping):
        return {}, ["The proposal is an object of fields."]
    known = {field.key: field for field in specs}
    problems = [f"Unknown field {key!r}." for key in values if key not in known]
    clean: dict[str, Any] = {}
    for field in specs:
        value = values.get(field.key)
        if value is None or value == "" or value == []:
            if field.required:
                problems.append(f"{field.title} ({field.key}) is required.")
            continue
        problem = _field_problem(field, value)
        if problem:
            problems.append(problem)
        else:
            clean[field.key] = value
    return clean, problems


def _field_problem(field: WorkField, value: Any) -> str:
    kind = field.type
    wrong = f"{field.title} ({field.key}) is a {kind.replace('_', ' ')}."
    if kind == "boolean":
        return "" if isinstance(value, bool) else wrong
    if kind in ("number", "integer"):
        if not isinstance(value, int | float) or isinstance(value, bool):
            return wrong
        if kind == "integer" and float(value) != int(value):
            return wrong
        if field.min is not None and value < field.min:
            return f"{field.title} is {field.min:g} at least."
        if field.max is not None and value > field.max:
            return f"{field.title} is {field.max:g} at most."
        return ""
    if kind == "list":
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        return "" if ok else wrong
    if not isinstance(value, str):
        return wrong
    if len(value) > field.max_length:
        return f"{field.title} has {field.max_length} characters at most."
    if kind == "choice" and value not in field.options:
        return f"{field.title} is one of: {', '.join(field.options)}."
    if kind == "date" and not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return f"{field.title} is a date (YYYY-MM-DD)."
    if kind == "datetime" and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
        return f"{field.title} is a date and time (ISO 8601)."
    return ""


class ObjectKind(_Table):
    """A kind of the app's objects that notebooks list, read and run through PlantCraft with the
    person's access (``GET /api/v1/apps/<app>/objects/<kind>``; ``docs/en/notebooks.md``, "The
    apps' objects"). The app serves ``<prefix>api/objects/<kind>`` and
    ``<prefix>api/objects/<kind>/<id>`` (``plantcraft_sdk.server.objects``)."""

    kind: Slug
    title: Title
    description: Description = ""
    # Where its objects run when a notebook runs one: "local" on the person's computer (or in
    # their browser) with the app's runtime ([contributes.notebooks] runtime); "app" in the app's
    # own queue, like its Run button; "none": they are only read.
    run: Literal["none", "local", "app"] = "none"


MODULE = r"^[a-z_][a-z0-9_]{0,40}(\.[a-z_][a-z0-9_]{0,40}){0,4}$"


class NotebooksTable(_Table):
    """What the app gives notebooks: its examples (``Examples/<app>`` in Notebooks, in the browser
    and on the person's computer) and the Python packages that run its objects there."""

    examples: bool = False
    # Top-level packages copied, as they are installed in the app, to the person's computer when
    # a notebook first runs one of its objects; nothing runs on the server.
    runtime: list[Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]{0,40}$")]] = Field(
        default_factory=list, max_length=8
    )
    # The module of the runtime whose ``run(kind, item, plant, app, **options)`` runs an object.
    entry: Annotated[str, StringConstraints(pattern=MODULE)] | None = None

    @model_validator(mode="after")
    def _entry(self) -> NotebooksTable:
        if bool(self.runtime) != bool(self.entry):
            raise ValueError("[contributes.notebooks] names its runtime and its entry together")
        if self.entry and self.entry.split(".")[0] not in self.runtime:
            raise ValueError(f"entry {self.entry!r} is a module of its runtime packages")
        return self


class StartStep(_Table):
    """A first step the app takes once a plant's assets exist (review D5, F4):
    collect their signals, monitor their loops, draft their alarms, draw their overviews.
    PlantCraft offers the steps of every app on Assets › Import once an import is applied; an
    administrator ticks them, and PlantCraft calls ``POST <prefix>api/start/<id>`` as that person
    with what the import wrote (``StartIn``). The app does the step with its own access checks and
    answers ``StartOut``. A step is taken again after a later import, so it skips what it did
    already; it never deletes."""

    id: Slug
    title: Title
    description: Description = ""
    # Offered ticked: what most plants want as soon as their assets exist.
    default: bool = True
    # The app's page where the person sees what the step did.
    open: Path | None = None


class StartAsset(BaseModel):
    """An asset the import wrote, as ``StartIn`` lists it."""

    model_config = ConfigDict(extra="ignore")

    id: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    kind: Annotated[str, StringConstraints(max_length=80)] = ""
    name: Annotated[str, StringConstraints(max_length=300)] = ""
    parent_id: Annotated[str, StringConstraints(max_length=300)] | None = None


class StartSignal(BaseModel):
    """A signal the import bound to one of its assets."""

    model_config = ConfigDict(extra="ignore")

    asset_id: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    tag: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    role: Annotated[str, StringConstraints(max_length=40)] = ""
    source_id: Annotated[str, StringConstraints(max_length=120)] = ""


MAX_START_ASSETS = 50_000


class StartIn(BaseModel):
    """The body of ``POST <prefix>api/start/<id>``: what the newest import wrote. ``units`` are
    the ids of its assets of kind ``unit`` (or, in a tree without units, its top assets): the
    groups a step works by."""

    model_config = ConfigDict(extra="ignore")

    import_id: Annotated[str, StringConstraints(max_length=80)] = ""
    assets: list[StartAsset] = Field(default_factory=list, max_length=MAX_START_ASSETS)
    signals: list[StartSignal] = Field(default_factory=list, max_length=4 * MAX_START_ASSETS)
    units: list[Annotated[str, StringConstraints(max_length=300)]] = Field(
        default_factory=list, max_length=2000
    )


class StartOut(BaseModel):
    """What a start step answers: one sentence of what it did, its counts, where to see it."""

    summary: Annotated[str, StringConstraints(max_length=600)]
    counts: dict[str, int] = Field(default_factory=dict)
    open: str | None = None


class ContributesTable(_Table):
    llm: list[LlmUse] = Field(default_factory=list, max_length=20)
    widgets: list[Widget] = Field(default_factory=list, max_length=20)
    search: Search | None = None
    calendar: list[CalendarFeed] = Field(default_factory=list, max_length=10)
    todo: list[TodoKind] = Field(default_factory=list, max_length=20)
    refs: list[RefKind] = Field(default_factory=list, max_length=20)
    settings: list[Setting] = Field(default_factory=list, max_length=50)
    setup: list[SetupPage] = Field(default_factory=list, max_length=10)
    queue: bool = False
    assistant: AssistantTable | None = None
    objects: list[ObjectKind] = Field(default_factory=list, max_length=20)
    notebooks: NotebooksTable | None = None
    start: list[StartStep] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _unique(self) -> ContributesTable:
        _once(self.llm, "id", "llm use")
        _once(self.widgets, "id", "widget")
        _once(self.calendar, "id", "calendar feed")
        _once(self.todo, "id", "to-do kind")
        _once(self.refs, "kind", "reference kind")
        _once(self.settings, "key", "setting")
        _once(self.setup, "path", "setup page")
        _once(self.objects, "kind", "object kind")
        _once(self.start, "id", "start step")
        runs = [item.kind for item in self.objects if item.run == "local"]
        if runs and not (self.notebooks and self.notebooks.entry):
            raise ValueError(
                f"object kinds {', '.join(runs)} run locally: [contributes.notebooks] names the runtime"
            )
        return self


class ContributionsIn(BaseModel):
    """The body of ``PUT /api/v1/contributions``: what one app adds, replaced whole."""

    model_config = ConfigDict(extra="ignore")

    app: Annotated[str, StringConstraints(min_length=1, max_length=40)] | None = None
    version: Annotated[str, StringConstraints(max_length=60)] = ""
    format: int = CONTRIBUTES_VERSION
    contributes: ContributesTable = ContributesTable()
    series: list[SeriesSpec] = Field(default_factory=list, max_length=50)
    events: list[EventSpec] = Field(default_factory=list, max_length=100)
    # The app's [permissions] as ids (``read.signals``, ``write.audit``; plantcraft_sdk.scopes):
    # what PlantCraft holds a suite app's token to. None from an app before SDK 0.42.
    permissions: list[Annotated[str, StringConstraints(max_length=40)]] | None = Field(
        default=None, max_length=40
    )

    @model_validator(mode="before")
    @classmethod
    def _known_tables(cls, data: Any) -> Any:
        # A newer app may send tables this SDK does not know: keep the known ones, list the rest.
        if isinstance(data, Mapping) and isinstance(data.get("contributes"), Mapping):
            known = set(ContributesTable.model_fields)
            given = dict(data["contributes"])
            data = {
                **data,
                "contributes": {key: value for key, value in given.items() if key in known},
                "unknown": sorted(set(given) - known),
            }
        return data

    unknown: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _once(self) -> ContributionsIn:
        _once(self.series, "name", "series")
        _once(self.events, "name", "event")
        return self


def contributions(manifest: Any) -> dict[str, Any]:
    """The body of ``PUT /api/v1/contributions`` from a parsed ``AppManifest`` or ``app.toml``
    read as a dict."""

    if isinstance(manifest, Mapping):
        app = dict(manifest.get("app") or {})
        publishes = dict(manifest.get("publishes") or {})
        granted = dict(manifest.get("permissions") or {})
        body = ContributionsIn.model_validate(
            {
                "app": app.get("id"),
                "version": app.get("version") or "",
                "contributes": manifest.get("contributes") or {},
                "series": publishes.get("series") or [],
                "events": [
                    spec.model_dump(mode="json")
                    for spec in parse_specs(publishes.get("events") or [])
                ],
                "permissions": sorted(
                    declared(list(granted.get("read") or []), list(granted.get("write") or []))
                ),
            }
        )
    else:
        body = ContributionsIn(
            app=manifest.app.id,
            version=manifest.app.version,
            contributes=manifest.contributes,
            series=list(manifest.publishes.series),
            events=list(manifest.publishes.events),
            permissions=sorted(declared(manifest.permissions.read, manifest.permissions.write)),
        )
    return body.model_dump(mode="json", exclude_none=True, exclude={"unknown"})


__all__ = [
    "AssistantTable",
    "AssistantWork",
    "CONTRIBUTES_VERSION",
    "CalendarFeed",
    "ContributesTable",
    "ContributionsIn",
    "FEATURES",
    "LlmUse",
    "NotebooksTable",
    "ObjectKind",
    "PLATFORM_REF_KINDS",
    "RefKind",
    "SERIES_TYPES",
    "Search",
    "SeriesSpec",
    "Setting",
    "SetupPage",
    "StartAsset",
    "StartIn",
    "StartOut",
    "StartSignal",
    "StartStep",
    "TodoKind",
    "WORK_FIELD_TYPES",
    "Widget",
    "WorkField",
    "check_fields",
    "contributions",
    "fields_schema",
    "setting_value",
]
