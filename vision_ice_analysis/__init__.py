"""VisionICeAnalysis — End-to-end workflows for Vision Lab recordings.

Combines :mod:`visioniceio` (LabView binary I/O) and :mod:`neural_cca`
(spike sorting, STA, tuning analysis) into convenient experiment-level
pipelines.

This package is the single import surface for end-to-end use; it
re-exports the most common analysis primitives so callers don't have
to import from both upstream packages directly::

    from vision_ice_analysis import (
        load_from_visioniceio,
        run_sorting_pipeline,
        export_ssort,
        SortingData,
        SortingResult,
    )
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("vision-ice-analysis")
except PackageNotFoundError:
    __version__ = "0.0.0"

# Re-exports from neural_cca so the bridge is a self-contained import
# surface for typical end-to-end workflows.
from neural_cca import SortingData, SortingResult, run_sorting_pipeline

from .pipelines import batch_sort_experiment, export_ssort, load_from_visioniceio

__all__ = [
    "load_from_visioniceio",
    "batch_sort_experiment",
    "export_ssort",
    # Re-exports from neural_cca
    "SortingData",
    "SortingResult",
    "run_sorting_pipeline",
]
