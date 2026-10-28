"""The block file: one block, its contract and its Python code, in one JSON document.

The same document is what people import and export, what each saved version is, and what the
assistant is asked to write (``prompts.new_block_prompt``)::

    {
      "format": "plantcraft-block/1",
      "block_id": "equipment.ua_drift",          # library.name; given by Link when absent
      "name": "UA drift",
      "library": "equipment",
      "group": "Heat exchanger",
      "tags": ["fouling"],
      "origin": "user",                          # user | assistant | import | plantcraft | modelcraft-fmu
      "version": {"number": 3, "name": "Adaptive window", "description": "..."},
      "author": "jonathan", "owner": "jonathan",
      "docs": {"summary": "...", "description": "...", "reading": "...", "formula": "...",
               "assumptions": [], "limitations": [], "references": []},
      "inputs": [{"port": "duty", "type": "series", "label": "Duty", "unit": "kW",
                  "description": "..."}],
      "outputs": [{"port": "ua", "type": "series", "label": "UA", "unit": "kW/K",
                   "description": "...", "record": true}],
      "parameters": [{"name": "window_hours", "type": "number", "title": "Window",
                      "default": 24, "unit": "h", "minimum": 1, "description": "..."}],
      "image": "data:image/png;base64,...",       # optional: drawn in the node and palette
      "code": "def run(inputs, params, ctx):\\n    ...\\n    return {\\"ua\\": ua}"
    }

``image`` is optional: a PNG, JPEG or WebP of at most 256 KB, or an SVG, which is rebuilt
without scripts, event handlers or outside references (``plantcraft_sdk.images``).

``code`` defines ``run(inputs, params, ctx)``: ``inputs`` maps each input port to its value
(``None`` when an optional input is not wired, a list for a ``multiple`` one), ``params`` holds
the parameters (``params.window_hours``) and ``ctx`` the window (``ctx.start``, ``ctx.end``),
the asset and ``ctx.state`` (the block's memory between runs). It returns a dict with a value
per output port. It runs in a separate, restricted process (``blocks.sandbox``).

A saved version is immutable. Algorithms name a version (``equipment.ua_drift.v3``), so a new
version never changes in silence what an algorithm computes (owner decision, 2026-10-23).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from plantcraft_sdk.blocks import (
    BlockDocs,
    BlockSpec,
    NoParameters,
    Port,
)
from plantcraft_sdk.images import MAX_IMAGE_BYTES, ImageError, block_image
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    create_model,
    field_validator,
    model_validator,
)

from linkcraft.blocks.base import LIBRARIES
from linkcraft.i18n import t

FORMAT = "plantcraft-block/1"
ORIGINS = ("user", "assistant", "import", "plantcraft", "modelcraft-fmu")
# Libraries a block written on the site may join (the others are the app's own structure).
CLOSED_LIBRARIES = frozenset({"input", "output", "model", "draft"})
OPEN_LIBRARIES = tuple(key for key in LIBRARIES if key not in CLOSED_LIBRARIES)
# A library made on this site (round 10): its id, as a block's id starts with it.
LIBRARY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def open_library(library: str) -> bool:
    """Whether a site block may sit in ``library``: one Link ships that is open to them, or one
    made on this site (``BlockStore.create_library``)."""

    return library in OPEN_LIBRARIES or (
        library not in LIBRARIES
        and library not in CLOSED_LIBRARIES
        and bool(LIBRARY.match(library))
    )


DEFAULT_LIBRARY = "custom"
NAME = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
FAMILY = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]{0,59}$")
PINNED = re.compile(r"^(?P<family>[a-z][a-z0-9_]*\.[a-z][a-z0-9_]{0,59})\.v(?P<number>[0-9]{1,6})$")
MAX_CODE = 100_000
# A data URL of an image of at most MAX_IMAGE_BYTES (base64 is 4/3 of it).
MAX_IMAGE_URL = MAX_IMAGE_BYTES * 4 // 3 + 200
MAX_PORTS = 24
MAX_PARAMETERS = 40
PortTypeName = Literal["series", "state", "number", "result", "intervals"]


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    if not value or not value[0].isalpha():
        value = f"block_{value}".strip("_")
    return value[:60]


def pinned_id(family: str, number: int) -> str:
    """The id an algorithm names one version by: ``equipment.ua_drift`` 3 -> ``…ua_drift.v3``."""

    return f"{family}.v{int(number)}"


def split_pinned(block_id: str) -> tuple[str, int] | None:
    found = PINNED.match(block_id or "")
    return (found["family"], int(found["number"])) if found else None


class PortFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    port: str = Field(pattern=NAME.pattern)
    type: PortTypeName
    # An input may accept more than one type (a quality check reads a series or a state).
    types: list[PortTypeName] = Field(default_factory=list)
    label: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=2000)
    unit: str = Field(default="", max_length=40)
    required: bool = True
    multiple: bool = False
    record: bool = False
    low: float | None = None
    high: float | None = None
    better: Literal["higher", "lower"] | None = None

    def all_types(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([self.type, *self.types]))


class ParameterFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(pattern=NAME.pattern)
    type: Literal["number", "integer", "boolean", "text", "choice"] = "number"
    title: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=2000)
    default: Any = None
    unit: str = Field(default="", max_length=40)
    minimum: float | None = None
    maximum: float | None = None
    choices: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _default_fits(self) -> ParameterFile:
        if self.type == "choice" and not self.choices:
            raise ValueError("a choice parameter lists its choices")
        if self.default is None:
            self.default = {
                "number": self.minimum if self.minimum is not None else 0.0,
                "integer": int(self.minimum) if self.minimum is not None else 0,
                "boolean": False,
                "text": "",
                "choice": self.choices[0] if self.choices else "",
            }[self.type]
        value = self.default
        if self.type in ("number", "integer"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"the default of {self.name} must be a number")
            if self.type == "integer" and float(value) != int(value):
                raise ValueError(f"the default of {self.name} must be a whole number")
            if self.minimum is not None and value < self.minimum:
                raise ValueError(f"the default of {self.name} is below its minimum")
            if self.maximum is not None and value > self.maximum:
                raise ValueError(f"the default of {self.name} is above its maximum")
        elif self.type == "boolean" and not isinstance(value, bool):
            raise ValueError(f"the default of {self.name} must be true or false")
        elif self.type == "text" and not isinstance(value, str):
            raise ValueError(f"the default of {self.name} must be text")
        elif self.type == "choice" and value not in self.choices:
            raise ValueError(f"the default of {self.name} must be one of its choices")
        return self


class DocsFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1, max_length=400)
    description: str = Field(default="", max_length=6000)
    reading: str = Field(default="", max_length=3000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    formula: str = Field(default="", max_length=2000)
    references: list[str] = Field(default_factory=list, max_length=20)


class VersionFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: int = Field(default=0, ge=0)
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)


class BlockFile(BaseModel):
    """A block file (``plantcraft-block/1``), checked: what a version holds."""

    model_config = ConfigDict(extra="ignore")

    format: Literal["plantcraft-block/1"] = FORMAT
    block_id: str = ""
    name: str = Field(min_length=1, max_length=120)
    library: str = DEFAULT_LIBRARY
    group: str = Field(default="", max_length=60)
    tags: list[str] = Field(default_factory=list, max_length=20)
    origin: Literal["user", "assistant", "import", "plantcraft", "modelcraft-fmu"] = "user"
    version: VersionFile = Field(default_factory=VersionFile)
    author: str = Field(default="", max_length=120)
    owner: str = Field(default="", max_length=120)
    docs: DocsFile
    inputs: list[PortFile] = Field(default_factory=list, max_length=MAX_PORTS)
    outputs: list[PortFile] = Field(min_length=1, max_length=MAX_PORTS)
    parameters: list[ParameterFile] = Field(default_factory=list, max_length=MAX_PARAMETERS)
    runs_on_missing: bool = False
    # Its picture (round 9 M2): a data URL, checked (an SVG rebuilt) by plantcraft_sdk.images.
    image: str = Field(default="", max_length=MAX_IMAGE_URL)
    code: str = Field(min_length=1, max_length=MAX_CODE)

    @field_validator("image")
    @classmethod
    def _image(cls, value: str) -> str:
        try:
            return block_image(value)
        except ImageError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def _consistent(self) -> BlockFile:
        if not open_library(self.library):
            raise ValueError(
                f"library must be one of {', '.join(OPEN_LIBRARIES)} or one made on this site "
                f"(got {self.library!r})"
            )
        self.tags = list(
            dict.fromkeys(tag.strip().lower()[:40] for tag in self.tags if tag.strip())
        )
        if self.block_id:
            if not FAMILY.match(self.block_id):
                raise ValueError(
                    "block_id is library.name in lower case, for example custom.ua_drift"
                )
            if self.block_id.split(".")[0] != self.library:
                raise ValueError("block_id starts with the block's library")
        for kind, ports in (("input", self.inputs), ("output", self.outputs)):
            names = [port.port for port in ports]
            if len(set(names)) != len(names):
                raise ValueError(f"two {kind}s share a port name")
        for port in self.outputs:
            if port.types and port.all_types() != (port.type,):
                raise ValueError(f"output {port.port} carries one type")
        names = [item.name for item in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("two parameters share a name")
        return self

    def family(self) -> str:
        return self.block_id or f"{self.library}.{slug(self.name)}"

    def contract(self) -> str:
        """A fingerprint of the ports: a new version that changes it changes the wiring."""

        ports = [
            [kind, port.port, list(port.all_types()), port.required, port.multiple]
            for kind, items in (("in", self.inputs), ("out", self.outputs))
            for port in items
        ]
        return hashlib.sha256(json.dumps(ports, sort_keys=True).encode()).hexdigest()[:16]

    def code_key(self) -> str:
        return hashlib.sha256(self.code.encode()).hexdigest()


def problems_of(error: ValidationError) -> list[str]:
    """A validation error as sentences: where, then what."""

    found = []
    for item in error.errors()[:12]:
        where = ".".join(str(part) for part in item.get("loc", ()) if part != "__root__")
        message = str(item.get("msg") or "").removeprefix("Value error, ")
        found.append(f"{where}: {message}" if where else message)
    return found


def read_file(payload: Any) -> BlockFile:
    """A block file from JSON text or a dict; ``ValueError`` with the problems, one per line."""

    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(t("Not JSON: {error}", error=str(exc))) from exc
    if not isinstance(payload, dict):
        raise ValueError(t("A block file is a JSON object."))
    if payload.get("format") not in (None, FORMAT):
        raise ValueError(t("Unknown block format {format}.", format=payload.get("format")))
    try:
        return BlockFile.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("\n".join(problems_of(exc))) from exc


_PYTHON_TYPES: dict[str, type] = {"number": float, "integer": int, "boolean": bool, "text": str}


def parameters_model(file: BlockFile) -> type[BaseModel]:
    """The block's parameters as a pydantic model, so the diagram check validates them."""

    if not file.parameters:
        return NoParameters
    fields: dict[str, Any] = {}
    for item in file.parameters:
        extra = {"unit": item.unit} if item.unit else None
        kind: Any = (
            Literal[tuple(item.choices)]  # type: ignore[valid-type]
            if item.type == "choice"
            else _PYTHON_TYPES[item.type]
        )
        fields[item.name] = (
            kind,
            Field(
                default=item.default,
                title=item.title or item.name.replace("_", " ").capitalize(),
                description=item.description or None,
                ge=item.minimum if item.type in ("number", "integer") else None,
                le=item.maximum if item.type in ("number", "integer") else None,
                json_schema_extra=extra,
            ),
        )
    return create_model(f"Parameters_{slug(file.family())}", **fields)


def _port(item: PortFile, *, output: bool) -> Port:
    return Port(
        item.port,
        (item.type,) if output else item.all_types(),
        item.label or item.port.replace("_", " ").capitalize(),
        item.description,
        unit=item.unit,
        required=False if output else item.required,
        multiple=False if output else item.multiple,
        record=item.record if output else False,
        low=item.low,
        high=item.high,
        better=item.better,
    )


def spec_of(file: BlockFile, block_id: str) -> BlockSpec:
    docs = file.docs
    return BlockSpec(
        block_id,
        str(file.version.number or 0),
        file.library,
        file.name,
        BlockDocs(
            summary=docs.summary,
            description=docs.description or docs.summary,
            reading=docs.reading or t("See the block's description."),
            assumptions=tuple(docs.assumptions),
            limitations=tuple(docs.limitations),
            formula=docs.formula,
            references=tuple(docs.references),
        ),
        inputs=tuple(_port(item, output=False) for item in file.inputs),
        outputs=tuple(_port(item, output=True) for item in file.outputs),
        parameters=parameters_model(file),
        runs_on_missing=file.runs_on_missing,
        group=file.group,
        image=file.image,
    )


def _port_file(port: Port, *, output: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "port": port.port_id,
        "type": port.type,
        "label": port.label,
        "description": port.description,
    }
    if len(port.types) > 1:
        item["types"] = list(port.types)
    if port.unit:
        item["unit"] = port.unit
    if output:
        if port.record:
            item["record"] = True
        for key in ("low", "high", "better"):
            if getattr(port, key) is not None:
                item[key] = getattr(port, key)
    else:
        if not port.required:
            item["required"] = False
        if port.multiple:
            item["multiple"] = True
    return item


def _parameter_files(model: type[BaseModel]) -> list[dict[str, Any]]:
    """A pydantic parameters model as the file's parameter list (best effort: Literal ->
    choice, numbers keep their limits; anything richer is described as text)."""

    schema = model.model_json_schema()
    properties = schema.get("properties") or {}
    found = []
    for name, info in model.model_fields.items():
        prop = properties.get(name) or {}
        default = None if info.is_required() else info.get_default(call_default_factory=True)
        item: dict[str, Any] = {
            "name": name,
            "title": info.title or name.replace("_", " ").capitalize(),
            "description": info.description or "",
        }
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        if extra.get("unit"):
            item["unit"] = extra["unit"]
        kind = prop.get("type")
        if "enum" in prop:
            item.update(type="choice", choices=[str(value) for value in prop["enum"]])
        elif kind in ("number", "integer"):
            item["type"] = kind
            for source, target in (
                ("minimum", "minimum"),
                ("exclusiveMinimum", "minimum"),
                ("maximum", "maximum"),
                ("exclusiveMaximum", "maximum"),
            ):
                if source in prop:
                    item[target] = prop[source]
        elif kind == "boolean":
            item["type"] = "boolean"
        else:
            item["type"] = "text"
            default = default if isinstance(default, str) else json.dumps(default, default=str)
        item["default"] = default
        found.append(item)
    return found


def file_of_spec(spec: BlockSpec, code: str, **fields: Any) -> dict[str, Any]:
    """A block's contract as a block file (a shipped block exported, or the start of a copy)."""

    docs = spec.docs
    item: dict[str, Any] = {
        "format": FORMAT,
        "block_id": spec.block_id,
        "name": spec.name,
        "library": spec.library,
        "group": spec.group,
        "tags": [],
        "origin": "plantcraft",
        "docs": {
            "summary": docs.summary,
            "description": docs.description,
            "reading": docs.reading,
            "assumptions": list(docs.assumptions),
            "limitations": list(docs.limitations),
            "formula": docs.formula,
            "references": list(docs.references),
        },
        "inputs": [_port_file(port, output=False) for port in spec.inputs],
        "outputs": [_port_file(port, output=True) for port in spec.outputs],
        "parameters": _parameter_files(spec.parameters),
        "runs_on_missing": spec.runs_on_missing,
        "image": spec.image,
        "code": code,
    }
    item.update(fields)
    return item


__all__ = [
    "DEFAULT_LIBRARY",
    "FORMAT",
    "CLOSED_LIBRARIES",
    "LIBRARY",
    "OPEN_LIBRARIES",
    "ORIGINS",
    "BlockFile",
    "file_of_spec",
    "open_library",
    "parameters_model",
    "pinned_id",
    "problems_of",
    "read_file",
    "slug",
    "spec_of",
    "split_pinned",
]
