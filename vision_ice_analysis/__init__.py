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
    __version__ = "0.0.0"

# Re-exports from neural_cca so the bridge is a single import surface
# for typical end-to-end workflows.
from neural_cca import SortingData, SortingResult, run_sorting_pipeline

from .pipelines import batch_sort_experiment, load_from_visioniceio

__all__ = [
    "load_from_visioniceio",
    "batch_sort_experiment",
    # Re-exports from neural_cca
    "SortingData",
    "SortingResult",
    "run_sorting_pipeline",
]
