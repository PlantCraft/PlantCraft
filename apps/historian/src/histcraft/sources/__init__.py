"""History read from plant sources: PI Web API, OPC UA Historical Access and CSV files.

Ported from PlantCraft's ``industrial_data`` (same authors, Apache-2.0) when HistCraft
took over every connection to plant systems (``docs/data-layer.md``). ``history.py`` is
the interface the rest of HistCraft calls; the adapters below it are read-only.
"""
