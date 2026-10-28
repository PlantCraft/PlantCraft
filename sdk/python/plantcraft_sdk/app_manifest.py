"""``app.toml``, the manifest of an app of the suite (``docs/app-standard.md``, sections 4 and 7).

::

    from plantcraft_sdk.app_manifest import load_manifest

    manifest = load_manifest("app.toml")      # raises ManifestError listing every problem
    manifest.app.id, manifest.runtime.prefix

Every rule of the standard that can be read from the file is checked here:
the id, name and version forms, the suite table (each app's id, name,
prefix, port and uid are assigned once, in section 7), the permissions
(``plant_write`` false, no outbound hosts) and the kinds an app publishes and
consumes. Unknown tables and keys are errors, so a typo never passes silently.
``plantcraft-app check`` (``plantcraft_sdk.app_cli``) runs it in each
app's CI together with the repository layout of section 5.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from plantcraft_sdk.contributes import ContributesTable, SeriesSpec
from plantcraft_sdk.events import EventSpec, parse_specs
from plantcraft_sdk.scopes import READ_SCOPES, WRITE_SCOPES


@dataclass(frozen=True)
class SuiteRow:
    """One row of the suite table (section 7). ``prefix`` None: the app has no web prefix."""

    name: str
    prefix: str | None
    port: int
    uid: int


# The suite table of docs/app-standard.md, section 7: assigned there, nowhere else.
SUITE: dict[str, SuiteRow] = {
    "processcraft": SuiteRow("PlantCraft", "/", 8060, 10001),
    "cpmcraft": SuiteRow("CPMCraft", "/cpm/", 8070, 10002),
    "simcraft": SuiteRow("PlantCraft Simulator", None, 4840, 10004),
    "dashcraft": SuiteRow("PlantCraft View", "/dash/", 8080, 10006),
    "datacraft": SuiteRow("DataCraft", "/quality/", 8090, 10007),
    "histcraft": SuiteRow("PlantCraft Historian", "/hist/", 8100, 10008),
    "alarmcraft": SuiteRow("PlantCraft Alarms", "/alarm/", 8110, 10009),
    "twincraft": SuiteRow("PlantCraft Twin", "/twin/", 8120, 10010),
    "modelcraft": SuiteRow("PlantCraft Models", "/model/", 8130, 10011),
    "linkcraft": SuiteRow("PlantCraft Analytics", "/link/", 8140, 10012),
    "doccraft": SuiteRow("PlantCraft Documents", "/doc/", 8150, 10015),
}
# Rows of the table that are not apps: (port or None, uid).
SERVICES: dict[str, tuple[int | None, int]] = {
    "proxy": (8443, 10003),
    "installer": (None, 10005),
    # The one way out to a language model in the cloud (PlantCraft's image, processcraft/egress).
    "llm-egress": (3128, 10014),
    # The local compute worker's gateway and the apps' executors (docs/compute.md).
    "compute": (None, 10020),
}
# The uids PlantCraft hands to apps (processcraft/apps/package.py keeps the same range).
FIRST_UID, LAST_UID = 10002, 65533
# An app outside the table names no port and no uid (scale review E5, 2026-10-25): each app runs
# in its own container, so every one listens on the same port inside it, and its container user
# comes from its id, the same on every installation.
DEFAULT_PORT = 8000
FIRST_OWN_UID, OWN_UIDS = 20000, 40000


def default_uid(app_id: str) -> int:
    """The container user of an app that names none: from its id, in 20000-59999."""

    import hashlib

    return FIRST_OWN_UID + int(hashlib.sha256(app_id.encode()).hexdigest()[:8], 16) % OWN_UIDS


APP_ID = r"^[a-z][a-z0-9]{2,30}$"
NAME = r"^((PlantCraft|PlantCraft)( [A-Z][A-Za-z]{1,30})?|[A-Z][A-Za-z]*Craft)$"
SEMVER = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$"
)
# ">=1.0", ">=1.0,<2", "==1.2.0"
VERSION_RANGE = r"^\s*(==|>=|<=|>|<|~=|!=)\s*\d+(\.\d+){0,2}(\s*,\s*(==|>=|<=|>|<|~=|!=)\s*\d+(\.\d+){0,2})*\s*$"
# What [permissions] may name: one list for the suite (plantcraft_sdk.scopes, held to every
# API v1 route).
READS = tuple(READ_SCOPES)
WRITES = tuple(WRITE_SCOPES)
KIND = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
QUALIFIED_KIND = re.compile(r"^[a-z][a-z0-9]{2,30}\.[a-z][a-z0-9_]{0,59}$")
EVENT = re.compile(r"^[a-z][a-z0-9_]{0,39}(\.[a-z][a-z0-9_]{0,39}){1,3}$")
SUBJECT = re.compile(r"^(asset(:[a-z][a-z0-9_]{0,59})?|signal)$")
TYPE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
ROLE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

Text = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]


class ManifestError(ValueError):
    """``app.toml`` breaks the standard; ``problems`` lists every rule it breaks."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


class _Table(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AppTable(_Table):
    id: Annotated[str, StringConstraints(pattern=APP_ID)]
    name: Annotated[str, StringConstraints(pattern=NAME)]
    version: Annotated[str, StringConstraints(pattern=SEMVER)]
    category: Text
    summary: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    publisher: Text
    license: Text
    homepage: str = ""
    mark: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,40}$")]

    @field_validator("summary")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if "\n" in value.strip():
            raise ValueError("summary is one line")
        return value

    @field_validator("homepage")
    @classmethod
    def _homepage(cls, value: str) -> str:
        if value and not (urlsplit(value).scheme == "https" and urlsplit(value).netloc):
            raise ValueError("homepage is empty or an https:// address")
        return value


class RuntimeTable(_Table):
    # "" only for an app with no web prefix (the Simulator, an OPC UA server).
    prefix: str
    port: Annotated[int, Field(ge=1024, le=65535)] = DEFAULT_PORT
    # None: the app's own, from its id (default_uid), filled in when the manifest is read.
    uid: Annotated[int, Field(ge=10000, le=65535)] | None = None
    health: Annotated[str, StringConstraints(pattern=r"^/[A-Za-z0-9/_-]*$")] = "/healthz"
    image: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,63}$")]

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        if value and not re.match(r"^/([a-z][a-z0-9-]*/)?$", value):
            raise ValueError('prefix is a path like "/cpm/": lower case, with both slashes')
        return value


class RequiresTable(_Table):
    processcraft_api: Annotated[str, StringConstraints(pattern=VERSION_RANGE)]
    sdk: Annotated[str, StringConstraints(pattern=SEMVER)]
    asset_types: list[Annotated[str, StringConstraints(pattern=TYPE.pattern)]] = []
    roles: dict[str, list[Annotated[str, StringConstraints(pattern=ROLE.pattern)]]] = {}

    @model_validator(mode="after")
    def _roles_of_known_types(self) -> RequiresTable:
        unknown = sorted(set(self.roles) - set(self.asset_types))
        if unknown:
            raise ValueError(f"roles name types not in asset_types: {', '.join(unknown)}")
        return self


class PermissionsTable(_Table):
    read: list[str] = []
    write: list[str] = []
    plant_write: bool = False
    outbound: list[str] = []

    @field_validator("read")
    @classmethod
    def _read(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(READS))
        if unknown:
            raise ValueError(f"unknown read permissions {unknown}; use {', '.join(READS)}")
        return value

    @field_validator("write")
    @classmethod
    def _write(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(WRITES))
        if unknown:
            raise ValueError(f"unknown write permissions {unknown}; use {', '.join(WRITES)}")
        return value

    @field_validator("plant_write")
    @classmethod
    def _no_plant_write(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "plant_write is always false (a write path to a plant is an owner decision)"
            )
        return value

    @field_validator("outbound")
    @classmethod
    def _no_outbound(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("outbound is [] for every app (no outbound network by default)")
        return value


class ResultPort(_Table):
    kind: str
    subject: Annotated[str, StringConstraints(pattern=SUBJECT.pattern)]


class PublishesTable(_Table):
    results: list[ResultPort] = []
    # ``[[publishes.events]]`` tables (``plantcraft_sdk.events``); a bare name still declares one.
    events: list[EventSpec] = []
    # ``[[publishes.series]]``: what the app writes to the Historian (``contributes``).
    series: list[SeriesSpec] = []

    @field_validator("results")
    @classmethod
    def _bare_kinds(cls, value: list[ResultPort]) -> list[ResultPort]:
        for port in value:
            if not KIND.match(port.kind):
                raise ValueError(
                    f"published result kind {port.kind!r} is a bare name like loop_health "
                    "(the app id is added when others read it)"
                )
        return value

    @field_validator("events", mode="before")
    @classmethod
    def _events(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        for item in value:
            name = item if isinstance(item, str) else (item or {}).get("name", "")
            if isinstance(name, str) and not EVENT.match(name):
                raise ValueError(
                    f"published event {name!r} is <noun>.<verb> like finding.opened "
                    "(sent as <app id>.<noun>.<verb>)"
                )
        try:
            return parse_specs(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from None


class ConsumesTable(_Table):
    results: list[ResultPort] = []

    @field_validator("results")
    @classmethod
    def _qualified(cls, value: list[ResultPort]) -> list[ResultPort]:
        for port in value:
            if not QUALIFIED_KIND.match(port.kind):
                raise ValueError(
                    f"consumed result kind {port.kind!r} is <app id>.<kind> "
                    "like linkcraft.signal_quality"
                )
        return value


class SuggestsTable(_Table):
    asset_types: list[Annotated[str, StringConstraints(pattern=TYPE.pattern)]] = []


# A path inside the app's data folder: relative, no "..", "/" at the end for a folder.
DATA_PATH = r"^[A-Za-z0-9._-][A-Za-z0-9._/-]{0,199}$"
DataPath = Annotated[str, StringConstraints(pattern=DATA_PATH)]


class BackupTable(_Table):
    """What the suite's backup saves of the app's data folder (``docs/operations.md``).

    ``sqlite`` files are copied with SQLite's online backup and checked; ``files`` (a name, or a
    folder ending in ``/``) are copied as they are; ``skip`` is left out (caches, logs, scratch).
    Anything in the data folder that none of the three names is copied as a file too: a backup
    never misses data because a new file was not declared.
    """

    sqlite: list[DataPath] = []
    files: list[DataPath] = []
    skip: list[DataPath] = []

    @field_validator("sqlite", "files", "skip")
    @classmethod
    def _inside(cls, value: list[str]) -> list[str]:
        for name in value:
            if ".." in name.split("/"):
                raise ValueError(f"a path inside the data folder, without '..': {name!r}")
        return value

    @field_validator("sqlite")
    @classmethod
    def _databases(cls, value: list[str]) -> list[str]:
        for name in value:
            if name.endswith("/"):
                raise ValueError(f"sqlite names a database file, not a folder: {name!r}")
        return value

    @model_validator(mode="after")
    def _once(self) -> BackupTable:
        named = [*self.sqlite, *self.files, *self.skip]
        twice = sorted({name for name in named if named.count(name) > 1})
        if twice:
            raise ValueError(f"named more than once: {', '.join(twice)}")
        return self


class AppManifest(_Table):
    app: AppTable
    runtime: RuntimeTable
    requires: RequiresTable
    permissions: PermissionsTable = PermissionsTable()
    publishes: PublishesTable = PublishesTable()
    consumes: ConsumesTable = ConsumesTable()
    suggests: SuggestsTable = SuggestsTable()
    backup: BackupTable = BackupTable()
    # What PlantCraft draws for the app (``plantcraft_sdk.contributes``, section 4b).
    contributes: ContributesTable = ContributesTable()

    @model_validator(mode="after")
    def _suite_table(self) -> AppManifest:
        if self.runtime.uid is None:
            row = SUITE.get(self.app.id)
            uid = row.uid if row is not None else default_uid(self.app.id)
            # The tables are frozen once read: this one is made again with its user.
            object.__setattr__(self, "runtime", self.runtime.model_copy(update={"uid": uid}))
        problems = suite_problems(self)
        for spec in self.publishes.events:
            if spec.name.startswith(f"{self.app.id}."):
                problems.append(
                    f"published event {spec.name!r} is named without the app id "
                    f"({spec.name[len(self.app.id) + 1 :]!r}): it is sent as {self.app.id}.<name>"
                )
        names = [spec.name for spec in self.publishes.series]
        twice = sorted({name for name in names if names.count(name) > 1})
        if twice:
            problems.append(f"series declared more than once: {', '.join(twice)}")
        for page in self.contributes.setup:
            if self.runtime.prefix and not page.path.startswith(self.runtime.prefix):
                problems.append(
                    f"setup page {page.path!r} is a page of the app, under {self.runtime.prefix}"
                )
        for ref in self.contributes.refs:
            if self.runtime.prefix and not ref.url.startswith(self.runtime.prefix):
                problems.append(
                    f"reference kind {ref.kind!r} opens a page of the app, under {self.runtime.prefix}"
                )
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def to_json(self) -> dict[str, Any]:
        """The manifest as JSON (what an app's ``/api/meta`` serves, plus its revision)."""

        return self.model_dump(mode="json")


def suite_problems(manifest: AppManifest) -> list[str]:
    """Where the manifest disagrees with the suite table of section 7.

    An app of the suite must match its row. An app outside the table (a company's own app,
    one made from the app template) may take any id, but none of the prefix, port or uid
    of a row, of a stack service, or outside the uids PlantCraft hands to apps, and it may
    not carry the PlantCraft name, which the suite's own apps keep.
    """

    app, runtime = manifest.app, manifest.runtime
    problems = []
    row = SUITE.get(app.id)
    if row is None:
        if app.name.startswith(("PlantCraft", "PlantCraft")):
            problems.append(
                f"name {app.name!r} is kept for the suite's own apps: name yours like StarterCraft"
            )
        # Its port is its own container's (any); its prefix and its user must be its own.
        for owner, other in SUITE.items():
            for value, taken, what in (
                (runtime.prefix, other.prefix, "prefix"),
                (runtime.uid, other.uid, "uid"),
            ):
                if value == taken:
                    problems.append(f"{what} {value} belongs to {owner} in the suite table")
        for service, (_port, uid) in SERVICES.items():
            if runtime.uid == uid:
                problems.append(f"the uid belongs to the stack of PlantCraft ({service})")
        if runtime.uid is None or not FIRST_UID <= runtime.uid <= LAST_UID:
            problems.append(f"uid is between {FIRST_UID} and {LAST_UID}, not {runtime.uid}")
    else:
        if app.name != row.name:
            problems.append(f"name of {app.id} is {row.name!r}, not {app.name!r}")
        if runtime.prefix != (row.prefix or ""):
            problems.append(f"prefix of {app.id} is {row.prefix or ''!r}, not {runtime.prefix!r}")
        if runtime.port != row.port:
            problems.append(f"port of {app.id} is {row.port}, not {runtime.port}")
        if runtime.uid != row.uid:
            problems.append(f"uid of {app.id} is {row.uid}, not {runtime.uid}")
    if runtime.image != app.id:
        problems.append(f"image is named after the app id: {app.id!r}, not {runtime.image!r}")
    return problems


def _problems(error: ValidationError) -> list[str]:
    found = []
    for item in error.errors(include_input=False, include_url=False):
        where = ".".join(str(part) for part in item.get("loc", ())) or "app.toml"
        message = str(item.get("msg", "invalid")).removeprefix("Value error, ")
        if item.get("type") == "extra_forbidden":
            message = "unknown key (not in the standard)"
        elif item.get("type") == "missing":
            message = "required"
        found.append(f"{where}: {message}")
    return found


def parse_manifest(data: dict[str, Any]) -> AppManifest:
    """A parsed ``app.toml`` as an ``AppManifest``; raises ``ManifestError``."""

    try:
        return AppManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestError(_problems(exc)) from None


def load_manifest(path: str | Path) -> AppManifest:
    """Read and check ``app.toml``; raises ``ManifestError`` listing every problem."""

    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError([f"{path}: missing"]) from None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError([f"{path}: not valid TOML ({exc})"]) from None
    return parse_manifest(data)


__all__ = [
    "AppManifest",
    "BackupTable",
    "ManifestError",
    "SERVICES",
    "SUITE",
    "SuiteRow",
    "load_manifest",
    "parse_manifest",
    "suite_problems",
]
