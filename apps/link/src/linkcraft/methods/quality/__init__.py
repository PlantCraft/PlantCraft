"""Data quality methods, in the order they appear in the catalog."""

from linkcraft.methods.quality import (
    availability,
    statistics,
    value_integrity,
)

METHOD_MODULES = [availability, value_integrity, statistics]

__all__ = ["METHOD_MODULES"]
