"""End-to-end tests for the bridge-owned ``batch_sort_experiment``.

``batch_sort_experiment`` used to be a thin pass-through to
``neural_cca.sorting.batch`` (which itself imported ``visioniceio`` —
the cross-leaf coupling this bridge exists to prevent).  It now lives
entirely in the bridge.  These tests drive it over a synthetic
``visioniceio``-shaped zarr store so the full loop — load → coupled-mask
extraction → per-electrode sort → consolidated zarr — is exercised
without committing a real recording.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr
from neural_cca import make_rng

from vision_ice_analysis import (
    batch_sort_experiment,
    load_from_visioniceio,
    run_sorting_pipeline,
)


def _make_synthetic_zarr(
    path,
    *,
    n_elec: int = 2,
    n_trials: int = 8,
    max_spikes: int = 5,
    snippet: int = 12,
    fs: float = 30_000.0,
):
    """Write a minimal visioniceio-shaped experiment to *path* (zarr).

    Two waveform templates (so KMeans has structure to find), four
    valid spikes per (electrode, trial), and a trailing all-NaN spike
    slot per cell so the coupled NaN mask has padding to drop.
    """
    rs = make_rng(0)  # PCG64DXSM Generator (RNG policy)
    wv = np.full((n_elec, n_trials, max_spikes, snippet), np.nan, dtype=np.float64)
    st = np.full((n_elec, n_trials, max_spikes), np.nan, dtype=np.float64)
    t = np.linspace(0.0, 1.0, snippet)
    tmpl = (np.sin(2 * np.pi * t), -np.sin(2 * np.pi * t))
    n_valid = 4  # spike slot index `n_valid` (== 4) stays all-NaN padding
    for e in range(n_elec):
        for tr in range(n_trials):
            for s in range(n_valid):
                wv[e, tr, s, :] = tmpl[s % 2] + 0.1 * rs.standard_normal(snippet)
                st[e, tr, s] = rs.uniform(0.6, 2.4)

    coords_full = {
        "electrodes": np.arange(n_elec),
        "trials": np.arange(n_trials),
        "spikes_idx": np.arange(max_spikes),
    }
    ds = xr.Dataset(
        {
            "waveforms": xr.DataArray(
                wv,
                dims=("electrodes", "trials", "spikes_idx", "snippet_time"),
                coords={**coords_full, "snippet_time": np.arange(snippet) / fs},
            ),
            "spike_times": xr.DataArray(
                st,
                dims=("electrodes", "trials", "spikes_idx"),
                coords=coords_full,
            ),
            "stim_label": xr.DataArray(
                np.array([1, 2, 3, 4] * (n_trials // 4 + 1), dtype=np.int32)[:n_trials],
                dims=("trials",),
                coords={"trials": np.arange(n_trials)},
            ),
        },
        attrs={"SpikeSamplingFrequency": fs},
    )
    ds.to_zarr(str(path), mode="w")
    return path


def test_batch_end_to_end_writes_summary_and_store(tmp_path):
    src = _make_synthetic_zarr(tmp_path / "exp.zarr")
    out = tmp_path / "out.zarr"

    summary = batch_sort_experiment(
        src,
        output_path=out,
        stim_window=(0.5, 2.5),
        n_angle_steps=4,
        seed=0,
        compute_tuning=False,  # keep the assertion fast + deterministic
        compute_sta=True,
    )

    # Documented summary schema (CROSS_CHECKS.md → batch_sort_experiment).
    assert set(summary) >= {
        "result_path",
        "n_electrodes_processed",
        "n_clusters_total",
        "summary",
    }
    assert summary["n_electrodes_processed"] == 2
    assert summary["n_clusters_total"] >= 2

    # Coupled-mask extraction keeps exactly the 4 valid spikes/trial.
    for elec_summary in summary["summary"].values():
        assert {"n_clusters", "quality", "n_spikes"} <= set(elec_summary)
        assert elec_summary["n_spikes"] == 8 * 4

    # Output store is readable and carries the documented variables.
    res = xr.open_zarr(str(out))
    for var in (
        "spike_times_by_cluster",
        "firing_rate_by_trial",
        "trial_angles",
        "n_clusters",
    ):
        assert var in res
    assert res.sizes["trials"] == 8
    assert res.attrs["seed"] == 0


def test_batch_requires_stim_window(tmp_path):
    src = _make_synthetic_zarr(tmp_path / "exp.zarr")
    with pytest.raises(ValueError, match="stim_window is required"):
        batch_sort_experiment(src, n_angle_steps=4)


def test_batch_requires_angle_mapping(tmp_path):
    src = _make_synthetic_zarr(tmp_path / "exp.zarr")
    with pytest.raises(ValueError, match="tlabel2angle or n_angle_steps"):
        batch_sort_experiment(src, stim_window=(0.5, 2.5))


def test_batch_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Data source not found"):
        batch_sort_experiment(
            tmp_path / "nope.zarr",
            stim_window=(0.5, 2.5),
            n_angle_steps=4,
        )


def test_recorded_seed_replays_through_pipeline(tmp_path):
    """C2 regression: the ~128-bit master seed ``load_from_visioniceio``
    records in ``provenance`` must replay through ``run_sorting_pipeline``
    reproducibly. Before neural_cca 0.3.0's ``_as_seed`` fix, forwarding
    that seed raised ``InvalidParameterError`` in sklearn — so the
    recorded seed could not actually reproduce the run.
    """
    src = _make_synthetic_zarr(tmp_path / "exp.zarr")
    data = load_from_visioniceio(src, name="exp", electrode=0, stim_window=(0.5, 2.5))

    seed = data.metadata["provenance"]["seed"]
    assert seed.bit_length() > 32  # a full-entropy master, not a uint32

    r1 = run_sorting_pipeline(data, rng=seed, plot=False, compute_os=False)
    r2 = run_sorting_pipeline(data, rng=seed, plot=False, compute_os=False)
    assert len(r1.cluster_labels) == data.n_spikes
    assert np.array_equal(r1.cluster_labels, r2.cluster_labels)
