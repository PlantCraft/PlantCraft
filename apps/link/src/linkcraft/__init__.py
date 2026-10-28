"""PlantCraft Analytics: control loop performance monitoring for the PlantCraft suite."""

from importlib.metadata import PackageNotFoundError, version

# The installed package's version (pyproject.toml, which tests/test_app_standard.py ties to
# app.toml): /healthz, /api/me and the image label say the same, never a copy kept here.
try:
    __version__ = version("linkcraft")
except PackageNotFoundError:  # run from a checkout without `pip install -e .`
    __version__ = "0+unknown"
APP_ID = "linkcraft"
