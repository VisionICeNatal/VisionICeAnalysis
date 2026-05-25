"""Smoke tests for the public import surface.

These tests are intentionally trivial — their job is to catch the class
of breakage where a rename in an upstream package (visioniceio /
neural_cca) silently invalidates every import in this bridge package.
Without them, pytest exits 5 ("no tests collected") on an empty test
suite and CI is green on a fully broken package.
"""

from __future__ import annotations


def test_top_level_imports() -> None:
    """Every name in ``__all__`` must be importable from the top level."""
    import vision_ice_analysis as via

    for name in via.__all__:
        assert hasattr(via, name), f"vision_ice_analysis.{name} missing"


def test_bridge_callables() -> None:
    """Bridge entry points are callable (not e.g. None or stale modules)."""
    from vision_ice_analysis import (
        batch_sort_experiment,
        export_ssort,
        load_from_visioniceio,
        run_sorting_pipeline,
    )

    for fn in (
        load_from_visioniceio,
        batch_sort_experiment,
        export_ssort,
        run_sorting_pipeline,
    ):
        assert callable(fn), f"{fn!r} is not callable"


def test_sorting_data_signature() -> None:
    """The re-exported SortingData accepts the new (stim_window) API.

    Guards against the regression where the bridge was passing the old
    ``trial_duration`` / ``stimulus_onset`` kwargs to a dataclass that
    no longer accepts them.
    """
    import numpy as np

    from vision_ice_analysis import SortingData

    # Minimal valid construction with the new keyword names.
    sd = SortingData(
        waveforms=np.zeros((3, 8), dtype=np.float64),
        spike_times=np.array([0.1, 0.2, 0.3], dtype=np.float64),
        trials=np.array([0, 0, 1], dtype=np.int64),
        angles=np.array([0.0, 30.0], dtype=np.float64),
        stim_window=(0.5, 2.5),
        stim_frequency=2.0,
    )
    assert sd.n_spikes == 3
    assert sd.stim_window == (0.5, 2.5)
    assert sd.stimulus_duration == 2.0


def test_sorting_result_uses_cluster_labels() -> None:
    """SortingResult exposes ``cluster_labels`` (not ``labels``).

    Guards against the regression where ``export_ssort`` accessed
    ``result.labels`` instead of ``result.cluster_labels``.
    """
    import dataclasses

    from vision_ice_analysis import SortingResult

    field_names = {f.name for f in dataclasses.fields(SortingResult)}
    assert "cluster_labels" in field_names
    assert "labels" not in field_names
