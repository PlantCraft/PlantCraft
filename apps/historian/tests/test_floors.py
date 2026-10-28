"""Measured numbers never drop below the floors in tests/floors.toml."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import numpy as np

from histcraft.archive.codec import encode
from histcraft.archive.compression import Compressor
from histcraft.catalog.models import SOURCE_KINDS
from histcraft.meta import help_pages

ROOT = Path(__file__).resolve().parents[1]
FLOORS = tomllib.loads((ROOT / "tests" / "floors.toml").read_text(encoding="utf-8"))
METHODS = {"get", "post", "put", "patch", "delete"}


def test_api_floors(runtime):
    from histcraft.api.app import create_app

    paths = create_app(runtime).state.api.openapi()["paths"]
    operations = {
        (path, method) for path, ops in paths.items() for method in ops if method in METHODS
    }
    assert len(operations) >= FLOORS["api"]["operations"]
    data = [item for item in operations if item[0].startswith("/api/v1/data")]
    assert len(data) >= FLOORS["api"]["data_operations"]


def test_collection_floor():
    assert len(SOURCE_KINDS) >= FLOORS["collection"]["source_kinds"]


def test_compression_floors():
    rng = np.random.default_rng(7)
    times = np.arange(0, 7200) * 1000
    values = 50 + np.cumsum(rng.normal(0, 0.2, len(times))) + 5 * np.sin(times / 300_000)
    compressor = Compressor(deviation=0.5, max_seconds=100_000)
    archived = []
    for at, value in zip(times, values, strict=True):
        archived += compressor.feed(int(at), float(value))
    assert len(times) / len(archived) >= FLOORS["compression"]["ratio_walk"]
    chunk = encode(np.array([a[0] for a in archived]), np.array([a[1] for a in archived]), "number")
    assert len(times) / len(chunk) * 1024 >= FLOORS["compression"]["values_per_kb_walk"]


def test_test_count_floor():
    count = sum(
        1
        for path in (ROOT / "tests").glob("test_*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    )
    assert count >= FLOORS["tests"]["functions"]


def test_help_floor():
    assert len(help_pages()) >= FLOORS["help"]["pages"]
