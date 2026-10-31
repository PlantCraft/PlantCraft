"""Ways out of the block sandbox found in the security test of 2026-10-31 (D8): each one ran a
shell command from a block before ``check_code`` refused it."""

from __future__ import annotations

import pytest

from linkcraft.blocks.sandbox import check_code

MATCH_ESCAPE = """
def run(inputs, params, ctx):
    match ():
        case object(__class__=t):
            pass
    return {"out": t}
"""

MATCH_ARGS = """
def run(inputs, params, ctx):
    match inputs:
        case K(c):
            return {"out": c}
    return {}
"""

PICKLE_ESCAPE = """
import pandas
def run(inputs, params, ctx):
    return {"out": pandas.compat.pickle_compat.loads(b"")}
"""

EXPR_ESCAPE = """
import pandas
def run(inputs, params, ctx):
    env = pandas.core.computation.scope.Scope(0, local_dict={"x": ()})
    return {"out": pandas.core.computation.expr.Expr("x.__class__", env=env)()}
"""

IMPORT_ESCAPE = """
import pandas
def run(inputs, params, ctx):
    return {"out": pandas.core.apply.import_optional_dependency("subprocess")}
"""


@pytest.mark.parametrize(
    ("code", "problem"),
    [
        (MATCH_ESCAPE, "class patterns"),
        (MATCH_ARGS, "class patterns"),
        (PICKLE_ESCAPE, "pickle_compat"),
        ("from pandas.compat import pickle_compat\ndef run(i, p, c):\n    return {}\n", "pandas"),
        (EXPR_ESCAPE, "computation"),
        (IMPORT_ESCAPE, "import_optional_dependency"),
    ],
)
def test_known_escapes_are_refused(code, problem):
    assert any(problem in item for item in check_code(code))


def test_plain_match_still_works():
    code = (
        "def run(inputs, params, ctx):\n"
        "    match params.get('mode'):\n"
        "        case 'mean' | 'avg':\n"
        "            return {'out': 1}\n"
        "        case {'k': v}:\n"
        "            return {'out': v}\n"
        "        case _:\n"
        "            return {'out': 0}\n"
    )
    assert check_code(code) == []
