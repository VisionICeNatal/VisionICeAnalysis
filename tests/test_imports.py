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


def test_provenance_helper_shape() -> None:
    """The bridge's ``_provenance`` helper produces the documented dict shape.

    See ``CROSS_CHECKS.md`` → *Bridge-side contracts* for the field
    list. Downstream code is allowed to extend this dict, but the
    bridge's own keys form a stable schema — rename them and a paper's
    provenance audit trail breaks silently.
    """
    from vision_ice_analysis.pipelines import _provenance

    p = _provenance(seed=12345)

    assert set(p.keys()) >= {
        "loaded_at",
        "seed",
        "bit_generator",
        "input_sha256",
        "git_commit",
        "platform",
        "threading",
        "software_versions",
    }
    assert p["seed"] == 12345
    # bit_generator pairs with seed: a paper citing the seed must also
    # cite the BitGenerator class (Generator has no cross-version
    # algorithm-stability guarantee). See CROSS_CHECKS.md → RNG policy.
    assert p["bit_generator"] == "PCG64DXSM"
    assert isinstance(p["software_versions"], dict)
    # Python version is always resolvable from sys.version; the package
    # versions may be None when running uninstalled from a source checkout,
    # but the keys themselves must be present.
    sw = p["software_versions"]
    for key in (
        "vision-ice-analysis",
        "neural-cca",
        "visioniceio",
        "numpy",
        "scipy",
        "scikit-learn",
        "xarray",
        "zarr",
        "numcodecs",
        "python",
    ):
        assert key in sw, f"software_versions missing '{key}'"
    assert sw["python"], "python version should always resolve"
    # ISO-8601 timestamp contains a 'T' between date and time.
    assert "T" in p["loaded_at"]

    # input_sha256 / git_commit are best-effort: hex string or None.
    # When called without a data_source (as here), input_sha256 must
    # be None; git_commit depends on whether the install is editable.
    assert p["input_sha256"] is None
    assert p["git_commit"] is None or isinstance(p["git_commit"], str)

    # platform sub-dict: every key present, values are strings (even
    # the empty-string case is a str — never None).
    plat = p["platform"]
    assert isinstance(plat, dict)
    for key in ("system", "release", "machine", "python_compiler"):
        assert key in plat, f"platform missing '{key}'"
        assert isinstance(plat[key], str), f"platform['{key}'] is not str"

    # threading sub-dict: every BLAS-env key present, default "unset"
    # is a str so the value is always a str.
    thr = p["threading"]
    assert isinstance(thr, dict)
    for key in ("omp_num_threads", "mkl_num_threads", "openblas_num_threads"):
        assert key in thr, f"threading missing '{key}'"
        assert isinstance(thr[key], str), f"threading['{key}'] is not str"
