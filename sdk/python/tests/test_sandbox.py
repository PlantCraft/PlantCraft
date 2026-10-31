"""The sandbox for code written on the site (``plantcraft_sdk.sandbox``): checked before it
runs, modules only through their guard, and workers that stop slow code and refuse files and
network."""

from __future__ import annotations

from typing import Any

import pytest

from plantcraft_sdk import sandbox
from plantcraft_sdk.sandbox import CodeError, Policy, check_code, compile_code

RULE = Policy(entry="check", arguments=("inputs",), what="a rule")


def evaluate(payload: dict[str, Any]) -> Any:  # noqa: ANN401 - runs in the worker
    check = compile_code(payload["code"], RULE, key=payload["code"])
    return check(payload.get("inputs") or {})


@pytest.mark.parametrize(
    ("code", "problem"),
    [
        ("import os\ndef check(i):\n    return 1\n", "importing os"),
        ("from pandas.io import sql\ndef check(i):\n    return 1\n", "importing pandas.io"),
        ("def check(i):\n    return ().__class__\n", "start with _"),
        ("def check(i):\n    return eval('1')\n", "eval is not allowed in a rule"),
        ("def check(i):\n    return open('/etc/passwd')\n", "open is not allowed"),
        ("import numpy as np\ndef check(i):\n    np.save('x', 1)\n", "save is not allowed"),
        ("def check(i):\n    return '{0.x}'.format(i)\n", "format is not allowed"),
        ("def go(i):\n    return 1\n", "no check(inputs) function"),
        ("def check(i, j):\n    return 1\n", "exactly 1 arguments: inputs"),
        ("def check(i)\n    return 1\n", "Line 1"),
        ("import pandas as pd\ndef check(i):\n    pd.read_csv('/etc/x')\n", "read_csv"),
        ("from numpy.testing import runstring\ndef check(i):\n    return 1\n", "numpy"),
        # class patterns read attributes by name (security test 2026-10-31, D8)
        (
            "def check(i):\n    match ():\n        case object(__class__=c):\n            return c\n",
            "class patterns",
        ),
        (
            "def check(i):\n    match i:\n        case K(c):\n            return c\n",
            "class patterns",
        ),
        # pickle_compat.loads unpickles, and unpickling runs os.system
        (
            "import pandas\ndef check(i):\n    return pandas.compat.pickle_compat.loads(b'')\n",
            "pickle_compat",
        ),
        ("from pandas.compat import pickle_compat\ndef check(i):\n    return 1\n", "pandas.compat"),
        # Expr reads any attribute by name; import_optional_dependency imports any module
        (
            "import pandas\ndef check(i):\n    return pandas.core.computation.expr.Expr('x')\n",
            "computation",
        ),
        (
            "import pandas\ndef check(i):\n"
            "    return pandas.core.apply.import_optional_dependency('os')\n",
            "import_optional_dependency",
        ),
    ],
)
def test_code_is_checked_before_it_runs(code, problem):
    assert any(problem in item for item in check_code(code, RULE))


@pytest.mark.parametrize(
    "reach",
    [
        "from typing import sys\nos = sys.modules['os']",
        "import typing\nos = typing.sys.modules['os']",
        "import re\nos = re.enum.sys.modules['os']",
        "import dataclasses\nos = dataclasses.sys.modules['os']",
        "import numpy as np\nos = np.testing",
        "import plantcraft_sdk.blocks\nos = plantcraft_sdk.client",
        "import pandas\nos = pandas.compat",
    ],
)
def test_allowed_modules_never_lead_to_the_system(reach):
    code = f"{reach}\ndef check(i):\n    return 1\n"
    assert check_code(code, RULE) == []
    with pytest.raises((AttributeError, ImportError), match="not allowed|cannot import"):
        compile_code(code, RULE, key=reach)


def test_allowed_modules_and_the_apps_own_still_work():
    policy = Policy(entry="check", arguments=("inputs",), modules=sandbox.BASE_MODULES)
    code = (
        "import numpy as np\nimport pandas as pd\nfrom numpy import linalg\n"
        "def check(i):\n"
        "    s = pd.Series([1.0, 2.0, 3.0]).rolling(2).mean()\n"
        "    return float(np.nanmean(s)) + float(linalg.norm(np.array([3.0, 4.0]))) + i['x']\n"
    )
    assert compile_code(code, policy, key="guarded")({"x": 1.0}) == 8.0
    # Names the app hands in, without an import.
    given = compile_code("def check(i):\n    return LIMIT\n", RULE, key="n", names={"LIMIT": 3})
    assert given({}) == 3


def test_params_are_read_only():
    params = sandbox.Params({"window": 5})
    assert params.window == params["window"] == 5 and "window" in params
    with pytest.raises(AttributeError, match="read-only"):
        params.window = 6


def test_workers_stop_slow_code_and_refuse_files_and_network():
    pool = sandbox.CodePool(workers=1, timeout=4)
    try:
        assert pool.run(evaluate, {"code": "def check(i):\n    return i['a'] * 2\n",
                                   "inputs": {"a": 2}}) == 4  # fmt: skip
        writes = (
            "import pandas as pd\n"
            "def check(i):\n"
            "    pd.Series([1.0]).to_json('/tmp/processcraft-sandbox-test.json')\n"
            "    return 1\n"
        )
        assert check_code(writes, RULE) == []
        with pytest.raises((OSError, CodeError)):
            pool.run(evaluate, {"code": writes})
        with pytest.raises(CodeError, match="did not finish"):
            pool.run(evaluate, {"code": "def check(i):\n    while True:\n        pass\n"})
        with pytest.raises(CodeError, match="not allowed"):
            pool.run(evaluate, {"code": "import urllib.request\ndef check(i):\n    return 1\n"})
    finally:
        pool.shutdown()


def test_a_pool_per_kind_of_code_from_the_environment(monkeypatch):
    monkeypatch.setenv("TESTCRAFT_CODE_SANDBOX", "inline")
    try:
        found = sandbox.pool("TESTCRAFT_CODE")
        assert isinstance(found, sandbox.InlinePool)
        assert found.run(evaluate, {"code": "def check(i):\n    return 7\n"}) == 7
        monkeypatch.setenv("OTHERCRAFT_CODE_TIMEOUT_SECONDS", "3")
        other = sandbox.pool("OTHERCRAFT_CODE")
        assert isinstance(other, sandbox.CodePool) and other.timeout == 3
    finally:
        sandbox.shutdown()
