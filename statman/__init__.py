"""Statman — personlig plattform for norsk offentlig statistikk.

Alle imports i prosjektet er absolutte og går via pakkenavnet `statman`.
Det fungerer fordi prosjektet installeres editable (`uv sync`), og fordi
pytest får `pythonpath = ["."]` fra pyproject.toml.
"""

from __future__ import annotations

from statman.catalog import Metric, metric, metrics
from statman.io import load, model_path, project_root
from statman.registry import BuildResult, Context, build, model

__version__ = "0.1.0"

__all__ = [
    "BuildResult",
    "Context",
    "Metric",
    "__version__",
    "build",
    "load",
    "metric",
    "metrics",
    "model",
    "model_path",
    "project_root",
]
