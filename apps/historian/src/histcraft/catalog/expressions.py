"""Calculated points: a formula over other points, checked here and evaluated by the collector.

A formula names other points as ``[source:tag]`` and combines them with numbers, ``+ - * / **
%``, comparisons (``< <= > >= == !=``, true is 1), ``and``, ``or``, ``not`` and the functions
below. ``total(<formula>, per="h", reset="day")`` as the whole formula is a totalizer: the
time integral of the formula (a flow in m³/h totalled per hour gives m³), restarted at each
``reset`` (``none``, ``hour``, ``day`` or ``month``, in UTC).

Only these pieces are accepted: the formula is parsed with Python's ``ast`` and every node
checked against an allow list, never ``eval``-ed as code.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any

from histcraft.i18n import t

# ``[source:tag]``: a tag may hold anything but a closing bracket.
_REF = re.compile(r"\[([a-z0-9][a-z0-9_-]{0,39}):([^\]\n]+)\]")
MAX_LENGTH = 500
MAX_REFS = 20
_IF = re.compile(r"\bif\s*\(")
PERS = {"s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}
RESETS = ("none", "hour", "day", "month")


def _if(condition: float, yes: float, no: float) -> float:
    return yes if condition else no


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


FUNCTIONS: dict[str, tuple[Any, int, int]] = {
    # name: (function, fewest arguments, most arguments)
    "abs": (abs, 1, 1),
    "min": (min, 2, MAX_REFS),
    "max": (max, 2, MAX_REFS),
    "sqrt": (math.sqrt, 1, 1),
    "exp": (math.exp, 1, 1),
    "log": (math.log, 1, 1),
    "log10": (math.log10, 1, 1),
    "round": (round, 1, 2),
    "clip": (_clip, 3, 3),
    "if": (_if, 3, 3),
}
_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
    ast.Mod: lambda a, b: a % b,
}
_COMPARE = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}


class FormulaError(ValueError):
    """A formula Historian cannot take; the message says where and why."""


@dataclass
class Formula:
    text: str
    # The signals it reads, in the order of the variables ``_0``, ``_1``...
    signals: list[str]
    tree: ast.expr
    # A totalizer: seconds of its ``per`` unit and when it restarts; None for a plain formula.
    per_seconds: float | None = None
    reset: str = "none"

    @property
    def total(self) -> bool:
        return self.per_seconds is not None

    def evaluate(self, values: list[float]) -> float:
        """The formula on these input values (in ``signals`` order); NaN when it has none."""

        try:
            result = float(_evaluate(self.tree, values))
        except (ArithmeticError, ValueError, TypeError):
            return math.nan
        return result if math.isfinite(result) else math.nan


def parse(text: str) -> Formula:
    """Check a formula and prepare it; ``FormulaError`` says what is wrong."""

    text = (text or "").strip()
    if text.startswith("="):
        text = text[1:].strip()
    if not text:
        raise FormulaError(t("Write a formula, e.g. [plant:FI-100.PV] * 3.6."))
    if len(text) > MAX_LENGTH:
        raise FormulaError(t("A formula has at most {count} characters.", count=MAX_LENGTH))
    signals: list[str] = []

    def variable(match: re.Match[str]) -> str:
        signal = f"{match.group(1)}:{match.group(2).strip()}"
        if signal not in signals:
            signals.append(signal)
        return f"_{signals.index(signal)}"

    source = _REF.sub(variable, text)
    if "[" in source or "]" in source:
        raise FormulaError(t("A signal is written [source:tag], e.g. [plant:TI-100.PV]."))
    if not signals:
        raise FormulaError(t("A formula reads at least one signal, written [source:tag]."))
    if len(signals) > MAX_REFS:
        raise FormulaError(t("A formula reads at most {count} signals.", count=MAX_REFS))
    # ``if`` is a Python keyword: the function is parsed under another name.
    source = _IF.sub("if_(", source)
    try:
        tree = ast.parse(source, mode="eval").body
    except SyntaxError as exc:
        raise FormulaError(t("The formula is not valid: {detail}", detail=exc.msg)) from None
    per, reset = None, "none"
    if isinstance(tree, ast.Call) and isinstance(tree.func, ast.Name) and tree.func.id == "total":
        tree, per, reset = _totalizer(tree)
    _check(tree, len(signals))
    return Formula(text=text, signals=signals, tree=tree, per_seconds=per, reset=reset)


def _totalizer(call: ast.Call) -> tuple[ast.expr, float, str]:
    if len(call.args) != 1:
        raise FormulaError(t('total takes one formula: total([plant:FI-100.PV], per="h").'))
    per, reset = "h", "none"
    for keyword in call.keywords:
        if not isinstance(keyword.value, ast.Constant) or not isinstance(keyword.value.value, str):
            raise FormulaError(t("per and reset of total are words in quotes."))
        if keyword.arg == "per":
            per = keyword.value.value
        elif keyword.arg == "reset":
            reset = keyword.value.value
        else:
            raise FormulaError(t("total takes per and reset only."))
    if per not in PERS:
        raise FormulaError(t("per is one of {names}.", names=", ".join(PERS)))
    if reset not in RESETS:
        raise FormulaError(t("reset is one of {names}.", names=", ".join(RESETS)))
    return call.args[0], PERS[per], reset


def _check(node: ast.AST, count: int) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise FormulaError(t("Only numbers and signals go in a formula."))
        return
    if isinstance(node, ast.Name):
        if not re.fullmatch(r"_\d+", node.id) or int(node.id[1:]) >= count:
            raise FormulaError(
                t("Unknown name {name}: signals are written [source:tag].", name=node.id)
            )
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        _check(node.left, count)
        _check(node.right, count)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd | ast.Not):
        _check(node.operand, count)
        return
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            _check(value, count)
        return
    if isinstance(node, ast.Compare) and all(type(op) in _COMPARE for op in node.ops):
        _check(node.left, count)
        for value in node.comparators:
            _check(value, count)
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        name = _function(node.func.id)
        if name == "total":
            raise FormulaError(t("total is the whole formula, not a part of one."))
        if name not in FUNCTIONS:
            raise FormulaError(
                t("Unknown function {name}; known: {names}.", name=name, names=", ".join(FUNCTIONS))
            )
        _, low, high = FUNCTIONS[name]
        if not low <= len(node.args) <= high:
            raise FormulaError(
                t("{name} takes {low} to {high} values.", name=name, low=low, high=high)
            )
        for argument in node.args:
            _check(argument, count)
        return
    raise FormulaError(t("This is not allowed in a formula: {part}", part=ast.unparse(node)))


def _function(name: str) -> str:
    return "if" if name == "if_" else name


def _evaluate(node: ast.AST, values: list[float]) -> float:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return values[int(node.id[1:])]
    if isinstance(node, ast.BinOp):
        return _BINARY[type(node.op)](_evaluate(node.left, values), _evaluate(node.right, values))
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, values)
        if isinstance(node.op, ast.Not):
            return float(not operand)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BoolOp):
        results = [_evaluate(value, values) for value in node.values]
        return float(all(results) if isinstance(node.op, ast.And) else any(results))
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, values)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(comparator, values)
            if not _COMPARE[type(op)](left, right):
                return 0.0
            left = right
        return 1.0
    assert isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    function = FUNCTIONS[_function(node.func.id)][0]
    return float(function(*[_evaluate(argument, values) for argument in node.args]))
