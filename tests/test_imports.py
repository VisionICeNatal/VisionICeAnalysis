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
        load_from_visioniceio,
        run_sorting_pipeline,
    )

    for fn in (
        load_from_visioniceio,
        batch_sort_experiment,
        run_sorting_pipeline,
    ):
        assert callable(fn), f"{fn!r} is not callable"


def test_sorting_data_signature() -> None:
    """``SortingData`` accepts every kwarg the bridge passes in production.

    Mirrors the exact call shape of
    :func:`vision_ice_analysis.pipelines.load_from_visioniceio` so that
    any upstream rename or required-arg change to ``SortingData``
    surfaces here (not at the first call against a real experiment).
    """
    import numpy as np

    from vision_ice_analysis import SortingData

    sd = SortingData(
        waveforms=np.zeros((3, 8), dtype=np.float64),
        spike_times=np.array([0.1, 0.2, 0.3], dtype=np.float64),
        trials=np.array([0, 0, 1], dtype=np.int64),
        angles=np.array([0.0, 30.0], dtype=np.float64),
        waveform_fs=20_000.0,
        n_trials=2,
        stim_window=(0.5, 2.5),
        stim_frequency=2.0,
        metadata={"source": "test_sorting_data_signature"},
    )
    assert sd.n_spikes == 3
    assert sd.stim_window == (0.5, 2.5)
    # stimulus_duration is the window length (end - onset), not the endpoint.
    assert sd.stimulus_duration == 2.0
