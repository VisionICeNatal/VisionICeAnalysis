"""VisionICeAnalysis — End-to-end workflows for Vision Lab recordings.

Combines VisionICeIO (data loading) and mini_analysis_cidbn (processing)
to provide convenient experiment-level pipelines.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("vision-ice-analysis")
except PackageNotFoundError:
    __version__ = "0.0.0"

from .pipelines import batch_sort_experiment, export_ssort, load_from_visioniceio

__all__ = [
    "load_from_visioniceio",
    "batch_sort_experiment",
    "export_ssort",
]
