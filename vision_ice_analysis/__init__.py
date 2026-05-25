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

try:
    __version__ = version("vision-ice-analysis")
except PackageNotFoundError:
    # Reported when the package is on sys.path but not pip-installed
    # (e.g. a source checkout without `pip install -e .`). Keep this
    # string in sync with pyproject.toml — bump on every release; see
    # docs/developer.rst → Release Checklist.
    __version__ = "0.1.1"

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
