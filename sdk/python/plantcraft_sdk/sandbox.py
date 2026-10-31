"""Running Python that people wrote on the site, away from the app's server process.

Link's blocks, Alarms' Python rules and any app that lets a person write a little code use this
one sandbox (written once: AGENTS.md, section 2). The code never runs in the server's process.
``CodePool`` keeps worker processes (started with ``spawn``) that:

- cannot write files (``RLIMIT_FSIZE`` 0) or open network connections (``socket`` disabled);
- get a memory budget (``memory_mb``, default 1024 above what they start with);
- are stopped when a call takes longer than ``timeout`` seconds (default 30).

Before it runs, the code is checked (``check_code``): it may import only the modules its
``Policy`` allows (``BASE_MODULES``: math, statistics, datetime, collections, re, json, numpy,
pandas and the like, plus what the app adds), may not touch attributes that start with ``_`` nor
names that start with ``__`` (the ways out of a restricted namespace), may not call ``eval``,
``exec``, ``open`` and the like, and may not use the file and process functions of numpy and
pandas (``DENIED_ATTRIBUTES``, and every ``read_*``). Its builtins are a short list
(``SAFE_BUILTINS``). The modules it imports reach it through ``_Module``, which hands out only
allowed modules: ``typing.sys`` or ``re.enum.sys`` (the modules an allowed module imports itself)
are refused while the code runs.

This is defence in depth on top of the suite's isolation (internal network, read-only image),
not a jail against a determined attacker: only administrators write code, and every version is
recorded with its author (AGENTS.md).

An app runs code in two steps: ``compile_code`` gives the code's entry function in the worker
(the app's own function, run by ``CodePool.run(fn, payload)``, builds the arguments it passes),
and ``pool(prefix)`` is the process's pool, configured by ``<PREFIX>_WORKERS``,
``<PREFIX>_TIMEOUT_SECONDS`` and ``<PREFIX>_MEMORY_MB``; ``<PREFIX>_SANDBOX=inline`` runs the
checked code in the calling process, for tests::

    POLICY = Policy(entry="check", arguments=("inputs",), what="a rule")

    def evaluate(payload):          # top level: it crosses to the worker
        check = compile_code(payload["code"], POLICY, key=payload["key"])
        return check(payload["inputs"])

    answer = pool("ALARMCRAFT_CODE").run(evaluate, {"key": "...", "code": code, "inputs": {...}})
"""

from __future__ import annotations

import ast
import builtins
import logging
import multiprocessing
import os
import threading
import types
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Any

from plantcraft_sdk.i18n import t

LOGGER = logging.getLogger(__name__)
TASKS_PER_WORKER = 500
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MEMORY_MB = 1024

BASE_MODULES = frozenset(
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
        # pickle_compat.loads unpickles, and unpickling calls any function (os.system)
        "pandas.compat",
        # Expr("x.__class__") reads any attribute by name (pandas.eval's own machinery)
        "pandas.core.computation",
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
        # unpickling calls any function
        "Unpickler",
        "pickle",
        "pickle_compat",
        "computation",
        "Expr",
        "Scope",
        # imports any module by name and hands it back unguarded
        "import_optional_dependency",
        # the system
        "system",
        "popen",
        "ctypes",
        "ctypeslib",
    }
)
# Functions that read files by name (pandas.read_csv, read_pickle, ...), whatever their package.
DENIED_PREFIXES = ("read_",)
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


class CodeError(RuntimeError):
    """The code could not run, with a sentence a person can act on."""


@dataclass(frozen=True)
class Policy:
    """What one kind of code may do: the function it defines (``entry``) with its arguments,
    the modules it may import (``modules``, ``BASE_MODULES`` and the app's own), and how the
    messages name it (``what``: "a block", "a rule")."""

    entry: str = "run"
    arguments: tuple[str, ...] = ("inputs", "params", "ctx")
    modules: frozenset[str] = BASE_MODULES
    what: str = "this code"

    def allows(self, name: str) -> bool:
        if any(name == denied or name.startswith(denied + ".") for denied in DENIED_MODULES):
            return False
        return any(name == allowed or name.startswith(allowed + ".") for allowed in self.modules)

    def leads_to_allowed(self, name: str) -> bool:
        # A package on the way to an allowed module ("linkcraft" for "linkcraft.blocks.base").
        return any(allowed.startswith(name + ".") for allowed in self.modules)

    @property
    def signature(self) -> str:
        return f"{self.entry}({', '.join(self.arguments)})"


def _attribute_denied(name: str) -> bool:
    return name in DENIED_ATTRIBUTES or name.startswith(DENIED_PREFIXES)


class _Module:
    """An allowed module as the code sees it: every attribute is looked up through ``_guard``.

    Allowed modules import others (``typing`` imports ``sys``, ``re`` imports ``enum``, a
    package's ``__init__`` imports ``os``): without this, ``typing.sys.modules["os"]`` would
    reach the system from code that imported only ``typing``. A package that only leads to an
    allowed module (``linkcraft`` for ``linkcraft.blocks.base``) opens nothing else.
    """

    __slots__ = ("_module", "_path_only", "_policy")

    def __init__(self, module: types.ModuleType, policy: Policy, path_only: bool = False):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_policy", policy)
        object.__setattr__(self, "_path_only", path_only)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        module = object.__getattribute__(self, "_module")
        policy: Policy = object.__getattribute__(self, "_policy")
        full = f"{module.__name__}.{name}"
        refused = t("{name} is not allowed in {what}.", name=full, what=policy.what)
        if name.startswith("_") or _attribute_denied(name):
            raise AttributeError(refused)
        if object.__getattribute__(self, "_path_only") and not (
            policy.allows(full) or policy.leads_to_allowed(full)
        ):
            raise AttributeError(refused)
        return _guard(getattr(module, name), full, policy)

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401
        raise AttributeError(t("Modules are read-only here."))

    def __delattr__(self, name: str) -> None:
        raise AttributeError(t("Modules are read-only here."))

    def __dir__(self) -> list[str]:
        module = object.__getattribute__(self, "_module")
        return [name for name in dir(module) if not name.startswith("_")]

    def __repr__(self) -> str:
        return f"<module {object.__getattribute__(self, '_module').__name__!r}>"


def _guard(value: Any, name: str, policy: Policy) -> Any:  # noqa: ANN401
    """What the code gets for ``value`` (found as ``name``): modules only through ``_Module``."""

    if isinstance(value, types.ModuleType):
        if policy.allows(value.__name__):
            return _Module(value, policy)
        if policy.leads_to_allowed(value.__name__):
            return _Module(value, policy, path_only=True)
        raise AttributeError(t("{name} is not allowed in {what}.", name=name, what=policy.what))
    return value


def check_code(code: str, policy: Policy = Policy()) -> list[str]:  # noqa: B008
    """What keeps ``code`` from running, one sentence each (empty: it may run)."""

    try:
        tree = ast.parse(code, filename="code.py")
    except SyntaxError as exc:
        return [t("Line {line}: {error}.", line=exc.lineno or "?", error=exc.msg)]
    problems: list[str] = []
    what = policy.what

    def problem(node: ast.AST, text: str) -> None:
        if len(problems) < 20:
            problems.append(
                t("Line {line}: {problem}", line=getattr(node, "lineno", "?"), problem=text)
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not policy.allows(alias.name):
                    problem(node, t("importing {module} is not allowed.", module=alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or not policy.allows(module):
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
                    problem(node, t("{name} is not allowed in {what}.", name=alias.name, what=what))
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                problem(
                    node,
                    t("attributes that start with _ are not allowed ({name}).", name=node.attr),
                )
            elif _attribute_denied(node.attr):
                problem(node, t("{name} is not allowed in {what}.", name=node.attr, what=what))
        elif isinstance(node, ast.MatchClass):
            # A class pattern reads attributes by name, like getattr: ``case object(__class__=c)``,
            # or ``case K(c)`` with a ``__match_args__`` the code set through type().
            problem(node, t("class patterns in match are not allowed in {what}.", what=what))
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                problem(node, t("names that start with __ are not allowed ({name}).", name=node.id))
            elif node.id in DENIED_NAMES:
                problem(node, t("{name} is not allowed in {what}.", name=node.id, what=what))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("__"):
                problem(
                    node, t("names that start with __ are not allowed ({name}).", name=node.name)
                )
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problem(node, t("global and nonlocal are not allowed in {what}.", what=what))
    entry = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.FunctionDef) and item.name == policy.entry
        ),
        None,
    )
    if entry is None:
        problems.append(t("The code defines no {signature} function.", signature=policy.signature))
    elif len(entry.args.args) != len(policy.arguments) or entry.args.vararg or entry.args.kwarg:
        problems.append(
            t(
                "{entry} takes exactly {count} arguments: {names}.",
                entry=policy.entry,
                count=len(policy.arguments),
                names=", ".join(policy.arguments),
            )
        )
    return problems


def _importer(policy: Policy) -> Callable[..., Any]:
    def restricted_import(
        name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0
    ) -> Any:  # noqa: ANN401
        if level or not policy.allows(name):
            raise ImportError(t("importing {module} is not allowed.", module=name))
        for item in fromlist or ():
            if f"{name}.{item}" in DENIED_MODULES:
                raise ImportError(t("importing {module} is not allowed.", module=f"{name}.{item}"))
        found = builtins.__import__(name, globals_, locals_, fromlist, level)
        # ``import a.b.c`` binds the package ``a``: the code walks from it to ``c`` only.
        return _guard(found, found.__name__, policy)

    return restricted_import


class Params:
    """Read-only values the code reads as ``params.window`` or ``params["window"]``."""

    def __init__(self, values: Mapping[str, Any]):
        object.__setattr__(self, "_values", dict(values))

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, name: str) -> Any:  # noqa: ANN401
        return self._values[name]

    def __contains__(self, name: object) -> bool:
        return name in self._values

    def get(self, name: str, default: Any = None) -> Any:  # noqa: ANN401
        return self._values.get(name, default)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(t("These values are read-only."))

    def __repr__(self) -> str:
        return f"Params({self._values!r})"


_COMPILED: dict[tuple[str, Policy], Any] = {}


def compile_code(
    code: str,
    policy: Policy = Policy(),  # noqa: B008
    *,
    key: str,
    names: Mapping[str, Any] | None = None,
) -> Any:  # noqa: ANN401
    """The entry function ``code`` defines, checked and compiled with restricted builtins
    (``names``: what the code finds without importing it). Cached by ``key``: give each
    version of the code its own."""

    found = _COMPILED.get((key, policy))
    if found is not None:
        return found
    problems = check_code(code, policy)
    if problems:
        raise CodeError(" ".join(problems))
    namespace: dict[str, Any] = {
        "__builtins__": {
            **SAFE_BUILTINS,
            "__import__": _importer(policy),
            "__build_class__": builtins.__build_class__,
        },
        "__name__": "code",
        **dict(names or {}),
    }
    exec(compile(code, "code.py", "exec"), namespace)  # noqa: S102 - checked, restricted builtins
    entry = namespace.get(policy.entry)
    if not callable(entry):
        raise CodeError(t("The code defines no {signature} function.", signature=policy.signature))
    if len(_COMPILED) > 200:
        _COMPILED.clear()
    _COMPILED[(key, policy)] = entry
    return entry


def _start_worker(memory_mb: int) -> None:
    """In each worker process, before any code runs: no files, no network, a memory budget."""

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
        LOGGER.info("Code workers run without resource limits on this system.")
    import socket

    def refused(*_args: Any, **_kwargs: Any) -> Any:  # noqa: ANN401
        raise OSError(t("Code written on the site has no network access."))

    socket.socket = refused  # type: ignore[assignment,misc]
    socket.create_connection = refused  # type: ignore[assignment]
    socket.socketpair = refused  # type: ignore[assignment]
    socket.getaddrinfo = refused  # type: ignore[assignment]


@dataclass
class CodePool:
    """Worker processes for code written on the site; ``run`` waits for the answer or the
    timeout. ``fn`` is a top-level function of the app (it crosses to the worker by name) and
    ``payload`` plain data."""

    workers: int = 2
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    memory_mb: int = DEFAULT_MEMORY_MB
    crashes: int = 0
    _pool: ProcessPoolExecutor | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _executor(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=max(1, int(self.workers)),
                    mp_context=multiprocessing.get_context("spawn"),
                    max_tasks_per_child=TASKS_PER_WORKER,
                    initializer=_start_worker,
                    initargs=(int(self.memory_mb),),
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

    def run(self, fn: Callable[[Any], Any], payload: Any) -> Any:  # noqa: ANN401
        try:
            future = self._executor().submit(fn, payload)
            return future.result(timeout=float(self.timeout))
        except FutureTimeout as exc:
            self._reset()
            raise CodeError(
                t(
                    "The code did not finish in {seconds} s and was stopped.",
                    seconds=f"{float(self.timeout):g}",
                )
            ) from exc
        except BrokenProcessPool as exc:
            self.crashes += 1
            self._reset()
            raise CodeError(
                t("The code stopped its worker (too much memory, or it crashed).")
            ) from exc
        except MemoryError as exc:
            raise CodeError(t("The code used more memory than it may.")) from exc

    def shutdown(self) -> None:
        self._reset()


class InlinePool:
    """Runs checked code in this process: tests and the command line only."""

    timeout = 0.0
    crashes = 0

    def run(self, fn: Callable[[Any], Any], payload: Any) -> Any:  # noqa: ANN401
        return fn(payload)

    def shutdown(self) -> None:
        return None


_POOLS: dict[str, CodePool | InlinePool] = {}
_POOLS_LOCK = threading.Lock()


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def pool(prefix: str) -> CodePool | InlinePool:
    """This process's pool for one kind of code (``prefix``: ``ALARMCRAFT_CODE``), started on
    first use and configured from the environment (module docstring)."""

    with _POOLS_LOCK:
        found = _POOLS.get(prefix)
        if found is None:
            if os.environ.get(f"{prefix}_SANDBOX", "").strip().lower() == "inline":
                found = InlinePool()
            else:
                found = CodePool(
                    workers=int(_number(f"{prefix}_WORKERS", 2)),
                    timeout=_number(f"{prefix}_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
                    memory_mb=int(_number(f"{prefix}_MEMORY_MB", DEFAULT_MEMORY_MB)),
                )
            _POOLS[prefix] = found
        return found


def use_pool(prefix: str, found: CodePool | InlinePool | None) -> None:
    """Set the pool for ``prefix`` (tests; ``None`` starts a new one on next use)."""

    with _POOLS_LOCK:
        before = _POOLS.pop(prefix, None)
        if before is not None and before is not found:
            before.shutdown()
        if found is not None:
            _POOLS[prefix] = found


def shutdown() -> None:
    """Stop every pool of this process (the app's shutdown)."""

    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for item in pools:
        item.shutdown()


__all__ = [
    "BASE_MODULES",
    "CodeError",
    "CodePool",
    "InlinePool",
    "Params",
    "Policy",
    "check_code",
    "compile_code",
    "pool",
    "shutdown",
    "use_pool",
]
