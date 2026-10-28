"""Running the Python code of a block written on the site, away from the server.

A block file carries code people wrote (or an assistant wrote for them). It never runs in the
server's process. ``CodePool`` keeps worker processes (started with ``spawn``) that:

- cannot write files (``RLIMIT_FSIZE`` 0) or open network connections (``socket`` disabled);
- get a memory budget (``LINKCRAFT_BLOCK_MEMORY_MB``, default 1024 above what they start with);
- are stopped when a call takes longer than ``LINKCRAFT_BLOCK_TIMEOUT_SECONDS`` (default 30).

Before it runs, the code is checked (``check_code``): it may import only ``ALLOWED_MODULES``,
may not touch attributes that start with ``_`` nor names that start with ``__`` (the ways out of
a restricted namespace), may not call ``eval``, ``exec``, ``open`` and the like, and may not
use the file and process functions of numpy and pandas (``DENIED_ATTRIBUTES``, and every
``read_*``). Its builtins are a short list (``SAFE_BUILTINS``). The modules it imports reach it
through ``_Module``, which hands out only allowed modules: ``typing.sys`` or ``re.enum.sys`` (the
modules an allowed module imports itself) are refused while the code runs.

This is defence in depth on top of the suite's isolation (internal network, read-only image),
not a jail against a determined attacker: only administrators write block code, and every
version is recorded with its author (AGENTS.md).

``LINKCRAFT_BLOCK_SANDBOX=inline`` runs the checked code in the calling process, for tests.
"""

from __future__ import annotations

import ast
import builtins
import logging
import multiprocessing
import os
import threading
import types
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Any

from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)
TASKS_PER_WORKER = 500
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MEMORY_MB = 1024

ALLOWED_MODULES = frozenset(
    {
        "math",
        "cmath",
        "statistics",
        "decimal",
        "fractions",
        "datetime",
        "collections",
        "itertools",
        "functools",
        "re",
        "json",
        "typing",
        "dataclasses",
        "enum",
        "numpy",
        "pandas",
        "plantcraft_sdk.blocks",
        "linkcraft.blocks.base",
    }
)
# Submodules that read or write files, or reach the system, even inside an allowed package.
DENIED_MODULES = frozenset(
    {
        "numpy.ctypeslib",
        "numpy.f2py",
        "numpy.distutils",
        "numpy.testing",
        "pandas.io",
        "pandas.testing",
    }
)
DENIED_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
        "help",
        "exit",
        "quit",
    }
)
DENIED_ATTRIBUTES = frozenset(
    {
        # string formatting reaches attributes by name
        "format",
        "format_map",
        # files
        "load",
        "save",
        "savez",
        "savez_compressed",
        "savetxt",
        "loadtxt",
        "genfromtxt",
        "fromfile",
        "tofile",
        "fromregex",
        "memmap",
        "DataSource",
        "lib",
        "io",
        "HDFStore",
        "ExcelWriter",
        "ExcelFile",
        "to_csv",
        "to_pickle",
        "to_parquet",
        "to_excel",
        "to_hdf",
        "to_sql",
        "to_feather",
        "to_stata",
        "to_clipboard",
        "dump",
        "to_orc",
        "to_xml",
        "to_html",
        "to_latex",
        "to_markdown",
        # expressions evaluated from text, and frames
        "eval",
        "query",
        "get_type_hints",
        "f_globals",
        "f_locals",
        "f_back",
        "f_builtins",
        "gi_frame",
        "gi_code",
        "cr_frame",
        "ag_frame",
        "tb_frame",
        "tb_next",
        # code run from text, and temporary files (numpy.testing)
        "runstring",
        "rundocs",
        "extbuild",
        "tempdir",
        "temppath",
        # the system
        "system",
        "popen",
        "ctypes",
        "ctypeslib",
    }
)
SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(builtins, name)
    for name in (
        "abs",
        "all",
        "any",
        "bool",
        "callable",
        "dict",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "frozenset",
        "hasattr",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "object",
        "pow",
        "print",
        "property",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "staticmethod",
        "classmethod",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "zip",
        "ArithmeticError",
        "AssertionError",
        "Exception",
        "FloatingPointError",
        "IndexError",
        "KeyError",
        "LookupError",
        "NotImplementedError",
        "OverflowError",
        "RuntimeError",
        "StopIteration",
        "TypeError",
        "ValueError",
        "ZeroDivisionError",
        "True",
        "False",
        "None",
        "NotImplemented",
        "Ellipsis",
    )
}


class BlockCodeError(RuntimeError):
    """The code of a block could not run, with a sentence a person can act on."""


# Functions that read files by name (pandas.read_csv, read_pickle, ...), whatever their package.
DENIED_PREFIXES = ("read_",)


def _module_allowed(name: str) -> bool:
    if any(name == denied or name.startswith(denied + ".") for denied in DENIED_MODULES):
        return False
    return any(name == allowed or name.startswith(allowed + ".") for allowed in ALLOWED_MODULES)


def _attribute_denied(name: str) -> bool:
    return name in DENIED_ATTRIBUTES or name.startswith(DENIED_PREFIXES)


def _leads_to_allowed(name: str) -> bool:
    # A package on the way to an allowed module ("linkcraft" for "linkcraft.blocks.base").
    return any(allowed.startswith(name + ".") for allowed in ALLOWED_MODULES)


class _Module:
    """An allowed module as block code sees it: every attribute is looked up through ``_guard``.

    Allowed modules import others (``typing`` imports ``sys``, ``re`` imports ``enum``, a
    package's ``__init__`` imports ``os``): without this, ``typing.sys.modules["os"]`` would
    reach the system from code that imported only ``typing``. A package that only leads to an
    allowed module (``linkcraft`` for ``linkcraft.blocks.base``) opens nothing else.
    """

    __slots__ = ("_module", "_path_only")

    def __init__(self, module: types.ModuleType, path_only: bool = False):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_path_only", path_only)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        module = object.__getattribute__(self, "_module")
        full = f"{module.__name__}.{name}"
        if name.startswith("_") or _attribute_denied(name):
            raise AttributeError(t("{name} is not allowed in a block.", name=full))
        if object.__getattribute__(self, "_path_only") and not (
            _module_allowed(full) or _leads_to_allowed(full)
        ):
            raise AttributeError(t("{name} is not allowed in a block.", name=full))
        return _guard(getattr(module, name), full)

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401
        raise AttributeError(t("Modules are read-only in a block."))

    def __delattr__(self, name: str) -> None:
        raise AttributeError(t("Modules are read-only in a block."))

    def __dir__(self) -> list[str]:
        module = object.__getattribute__(self, "_module")
        return [name for name in dir(module) if not name.startswith("_")]

    def __repr__(self) -> str:
        return f"<module {object.__getattribute__(self, '_module').__name__!r}>"


def _guard(value: Any, name: str) -> Any:  # noqa: ANN401
    """What block code gets for ``value`` (found as ``name``): modules only through ``_Module``."""

    if isinstance(value, types.ModuleType):
        if _module_allowed(value.__name__):
            return _Module(value)
        if _leads_to_allowed(value.__name__):
            return _Module(value, path_only=True)
        raise AttributeError(t("{name} is not allowed in a block.", name=name))
    return value


def check_code(code: str) -> list[str]:
    """What keeps ``code`` from running as a block, one sentence each (empty: it may run)."""

    try:
        tree = ast.parse(code, filename="block.py")
    except SyntaxError as exc:
        return [t("Line {line}: {error}.", line=exc.lineno or "?", error=exc.msg)]
    problems: list[str] = []

    def problem(node: ast.AST, text: str) -> None:
        if len(problems) < 20:
            problems.append(
                t("Line {line}: {problem}", line=getattr(node, "lineno", "?"), problem=text)
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name):
                    problem(node, t("importing {module} is not allowed.", module=alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or not _module_allowed(module):
                problem(node, t("importing {module} is not allowed.", module=module or "."))
            for alias in node.names:
                if alias.name == "*" or alias.name.startswith("_"):
                    problem(node, t("import the names you use, one by one."))
                elif f"{module}.{alias.name}" in DENIED_MODULES:
                    problem(
                        node,
                        t("importing {module} is not allowed.", module=f"{module}.{alias.name}"),
                    )
                elif _attribute_denied(alias.name):
                    problem(node, t("{name} is not allowed in a block.", name=alias.name))
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                problem(
                    node,
                    t("attributes that start with _ are not allowed ({name}).", name=node.attr),
                )
            elif _attribute_denied(node.attr):
                problem(node, t("{name} is not allowed in a block.", name=node.attr))
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                problem(node, t("names that start with __ are not allowed ({name}).", name=node.id))
            elif node.id in DENIED_NAMES:
                problem(node, t("{name} is not allowed in a block.", name=node.id))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("__"):
                problem(
                    node, t("names that start with __ are not allowed ({name}).", name=node.name)
                )
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problem(node, t("global and nonlocal are not allowed in a block."))
    run = next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "run"),
        None,
    )
    if run is None:
        problems.append(t("The code defines no run(inputs, params, ctx) function."))
    elif len(run.args.args) != 3 or run.args.vararg or run.args.kwarg:
        problems.append(t("run takes exactly three arguments: inputs, params and ctx."))
    return problems


def _restricted_import(
    name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0
) -> Any:  # noqa: ANN401
    if level or not _module_allowed(name):
        raise ImportError(t("importing {module} is not allowed.", module=name))
    for item in fromlist or ():
        if f"{name}.{item}" in DENIED_MODULES:
            raise ImportError(t("importing {module} is not allowed.", module=f"{name}.{item}"))
    found = builtins.__import__(name, globals_, locals_, fromlist, level)
    # ``import a.b.c`` binds the package ``a``: the code walks from it to ``c`` and nowhere else.
    return _guard(found, found.__name__)


class Params:
    """A block's parameters as the code reads them: ``params.window`` or ``params["window"]``."""

    def __init__(self, values: Mapping[str, Any]):
        object.__setattr__(self, "_values", dict(values))

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, name: str) -> Any:  # noqa: ANN401
        return self._values[name]

    def get(self, name: str, default: Any = None) -> Any:  # noqa: ANN401
        return self._values.get(name, default)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(t("Parameters are read-only."))

    def __repr__(self) -> str:
        return f"Params({self._values!r})"


@dataclass
class Call:
    """One call of a block's ``run``: plain data, so it crosses to a worker process."""

    key: str
    code: str
    inputs: dict[str, Any]
    params: dict[str, Any]
    start: Any = None
    end: Any = None
    sample_seconds: float | None = None
    asset: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    node_id: str = ""


_COMPILED: dict[str, Any] = {}


def _compiled(call: Call) -> Any:  # noqa: ANN401
    found = _COMPILED.get(call.key)
    if found is not None:
        return found
    problems = check_code(call.code)
    if problems:
        raise BlockCodeError(" ".join(problems))
    from plantcraft_sdk.blocks import NoData, Result

    namespace: dict[str, Any] = {
        "__builtins__": {
            **SAFE_BUILTINS,
            "__import__": _restricted_import,
            "__build_class__": builtins.__build_class__,
        },
        "__name__": "block",
        "Result": Result,
        "NoData": NoData,
    }
    exec(compile(call.code, "block.py", "exec"), namespace)  # noqa: S102 - checked code, restricted builtins
    run = namespace.get("run")
    if not callable(run):
        raise BlockCodeError(t("The code defines no run(inputs, params, ctx) function."))
    if len(_COMPILED) > 200:
        _COMPILED.clear()
    _COMPILED[call.key] = run
    return run


def execute(call: Call) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run ``call`` here (in a worker process, or inline): the outputs and the block's new state."""

    from plantcraft_sdk.blocks import Context

    run = _compiled(call)
    context = Context(
        start=call.start,
        end=call.end,
        sample_seconds=call.sample_seconds,
        asset=dict(call.asset),
        states={call.node_id: dict(call.state)},
        node_id=call.node_id,
    )
    given = run(dict(call.inputs), Params(call.params), context)
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise BlockCodeError(
            t(
                "run returned {kind}; it returns a dict with a value per output port.",
                kind=type(given).__name__,
            )
        )
    return given, context.state


def _start_worker(memory_mb: int) -> None:
    """In each worker process, before any block runs: no files, no network, a memory budget."""

    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    import numpy  # noqa: F401 - loaded before the memory limit
    import pandas  # noqa: F401

    try:
        import resource

        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        if memory_mb > 0:
            used = 0
            try:
                with open("/proc/self/status", encoding="ascii") as status:
                    for line in status:
                        if line.startswith("VmSize:"):
                            used = int(line.split()[1]) * 1024
            except OSError:
                used = 0
            if used:
                limit = used + memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # not Linux: the timeout still applies
        LOGGER.info("Block workers run without resource limits on this system.")
    import socket

    def refused(*_args: Any, **_kwargs: Any) -> Any:  # noqa: ANN401
        raise OSError(t("Blocks have no network access."))

    socket.socket = refused  # type: ignore[assignment,misc]
    socket.create_connection = refused  # type: ignore[assignment]
    socket.socketpair = refused  # type: ignore[assignment]
    socket.getaddrinfo = refused  # type: ignore[assignment]


class CodePool:
    """Worker processes for block code; ``run`` blocks until the outputs or the timeout."""

    def __init__(
        self,
        workers: int = 2,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        memory_mb: int = DEFAULT_MEMORY_MB,
    ):
        self.workers = max(1, int(workers))
        self.timeout = float(timeout)
        self.memory_mb = int(memory_mb)
        self._lock = threading.Lock()
        self._pool: ProcessPoolExecutor | None = None
        self.crashes = 0

    def _executor(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=self.workers,
                    mp_context=multiprocessing.get_context("spawn"),
                    max_tasks_per_child=TASKS_PER_WORKER,
                    initializer=_start_worker,
                    initargs=(self.memory_mb,),
                )
            return self._pool

    def _reset(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is None:
            return
        for process in list((getattr(pool, "_processes", None) or {}).values()):
            if process.is_alive():
                process.kill()
        pool.shutdown(wait=False, cancel_futures=True)

    def run(self, call: Call) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            future = self._executor().submit(execute, call)
            return future.result(timeout=self.timeout)
        except FutureTimeout as exc:
            self._reset()
            raise BlockCodeError(
                t(
                    "The block's code did not finish in {seconds} s and was stopped.",
                    seconds=f"{self.timeout:g}",
                )
            ) from exc
        except BrokenProcessPool as exc:
            self.crashes += 1
            self._reset()
            raise BlockCodeError(
                t("The block's code stopped its worker (too much memory, or it crashed).")
            ) from exc
        except MemoryError as exc:
            raise BlockCodeError(t("The block's code used more memory than a block may.")) from exc

    def shutdown(self) -> None:
        self._reset()


class InlinePool:
    """Runs checked block code in this process: tests and the command line only."""

    timeout = 0.0
    crashes = 0

    def run(self, call: Call) -> tuple[dict[str, Any], dict[str, Any]]:
        return execute(call)

    def shutdown(self) -> None:
        return None


_POOL: CodePool | InlinePool | None = None
_POOL_LOCK = threading.Lock()


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def pool() -> CodePool | InlinePool:
    """This process's pool for block code, started on first use."""

    global _POOL  # noqa: PLW0603 - one pool per process
    with _POOL_LOCK:
        if _POOL is None:
            if os.environ.get("LINKCRAFT_BLOCK_SANDBOX", "").strip().lower() == "inline":
                _POOL = InlinePool()
            else:
                _POOL = CodePool(
                    workers=int(_number("LINKCRAFT_BLOCK_WORKERS", 2)),
                    timeout=_number("LINKCRAFT_BLOCK_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
                    memory_mb=int(_number("LINKCRAFT_BLOCK_MEMORY_MB", DEFAULT_MEMORY_MB)),
                )
        return _POOL


def use_pool(found: CodePool | InlinePool | None) -> None:
    """Set this process's pool (tests; ``None`` starts a new one on next use)."""

    global _POOL  # noqa: PLW0603
    with _POOL_LOCK:
        if _POOL is not None and _POOL is not found:
            _POOL.shutdown()
        _POOL = found


def shutdown() -> None:
    use_pool(None)


__all__ = [
    "ALLOWED_MODULES",
    "BlockCodeError",
    "Call",
    "CodePool",
    "InlinePool",
    "Params",
    "check_code",
    "execute",
    "pool",
    "shutdown",
    "use_pool",
]
