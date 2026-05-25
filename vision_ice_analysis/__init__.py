"""VisionICeAnalysis — End-to-end workflows for Vision Lab recordings.

Combines ``visioniceio`` (LabView binary I/O) and :mod:`neural_cca`
(spike sorting, STA, tuning analysis) into convenient experiment-level
pipelines.

Re-exports the most common analysis primitives from :mod:`neural_cca`
so callers don't have to import from both upstream packages directly::

    from vision_ice_analysis import (
        load_from_visioniceio,
        run_sorting_pipeline,
        SortingData,
        SortingResult,
    )
"""

from importlib.metadata import PackageNotFoundError, version


def _read_version_from_pyproject() -> str:
    """Fallback for source-checkout imports (no ``pip install``).

    ``importlib.metadata.version()`` reads the installed package's
    ``METADATA`` file, which is generated from ``pyproject.toml`` at
    install time. When the package isn't installed at all, we parse
    ``pyproject.toml`` directly so the version stays in sync with the
    canonical source of truth instead of a hardcoded fallback that
    would silently rot between releases.

    Uses a regex rather than ``tomllib`` because ``tomllib`` is 3.11+
    and the project targets Python ``>=3.10``. Anchored at line start
    so unrelated ``*version`` keys (e.g. ``target-version``) are not
    matched.
    """
    import re
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "0.0.0"


try:
    __version__ = version("vision-ice-analysis")
except PackageNotFoundError:
    __version__ = _read_version_from_pyproject()

# Re-exports from neural_cca so the bridge is a single import surface
# for typical end-to-end workflows. ``steps2degree`` is re-exported
# because callers commonly override the default ``tlabel2angle`` mapping
# in ``load_from_visioniceio`` (e.g. for 8-direction or non-Natal
# experiments) and the bridge shouldn't force a `from neural_cca import`
# for that case. See ``CROSS_CHECKS.md`` → *steps2degree / tlabel2angle*.
from neural_cca import SortingData, SortingResult, run_sorting_pipeline, steps2degree

from .pipelines import batch_sort_experiment, load_from_visioniceio

__all__ = [
    "load_from_visioniceio",
    "batch_sort_experiment",
    # Re-exports from neural_cca
    "SortingData",
    "SortingResult",
    "run_sorting_pipeline",
    "steps2degree",
]
