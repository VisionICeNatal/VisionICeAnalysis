"""Spike-sorting workflows over VisionICeIO experiments.

This is the only layer that knows how a Natal recording is stored on
disk (a LabView experiment directory or a ``visioniceio`` zarr store)
*and* how to drive the :mod:`neural_cca` sorter.  By design neither
upstream leaf knows about the other — the composition lives here (see
``../CLAUDE.md`` → dependency direction).

Two entry points:

* :func:`load_from_visioniceio` — load one electrode into a
  ``SortingData`` container for a single :func:`run_sorting_pipeline`
  call.
* :func:`batch_sort_experiment` — loop every electrode, sort each, and
  write a consolidated zarr summary.

Both share one electrode-extraction helper
(:func:`_extract_electrode_arrays`) so the NaN-filtering contract can
never drift between the single-shot and batch paths.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import warnings
from collections.abc import Sequence
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import numpy as np
import xarray as xr
from neural_cca import (
    SortingData,
    minimal_spike_train_analysis,
    run_sorting_pipeline,
    steps2degree,
)
from numpy.random import SeedSequence
from visioniceio import Experiment

# RNG contract pinned by the bridge. Downstream consumers should
# reconstruct the random state as
#
#     from numpy.random import Generator, PCG64DXSM, SeedSequence
#     rng = Generator(PCG64DXSM(SeedSequence(metadata["provenance"]["seed"])))
#
# `np.random.default_rng()` returns a PCG64-backed generator with the
# known parallel-stream self-correlation bug (numpy/numpy#16313).
# Always go through SeedSequence — it mixes entropy from small
# integer seeds and supports `spawn()` for independent sub-streams.
# See CROSS_CHECKS.md → "RNG policy" for the full contract and
# spawning recipe.
_DEFAULT_BIT_GENERATOR = "PCG64DXSM"


def _safe_version(name: str) -> str | None:
    """Return ``importlib.metadata.version(name)`` or ``None`` if not installed."""
    try:
        return _pkg_version(name)
    except PackageNotFoundError:
        return None


def _compute_input_sha256(data_source: str | Path) -> str | None:
    """SHA-256 of the input ``data_source``.

    For a directory: hash the concatenation of sorted
    ``(relative_path, file_sha256)`` pairs for each file in the tree.
    Files >100 MB (e.g. zarr chunks) are not stream-hashed; instead we
    fold in their ``(path, size, mtime_ns)`` tuple so renames or
    re-writes of large chunks still perturb the digest without forcing
    a several-GB read on every load.

    For a single file: hash the file directly.

    Returns ``None`` if ``data_source`` does not exist on disk (e.g. a
    synthetic ``xarray.Dataset`` was loaded in-memory and no path is
    meaningful).
    """
    path = Path(data_source)
    if not path.exists():
        return None
    hasher = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    # Directory: hash of sorted (relpath, contenthash) pairs.
    for p in sorted(path.rglob("*")):
        if p.is_file():
            relpath = p.relative_to(path).as_posix()
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > 100 * 1024 * 1024:
                # Large file (likely zarr chunk): metadata only.
                hasher.update(f"{relpath}|{size}|{p.stat().st_mtime_ns}\n".encode())
            else:
                sub = hashlib.sha256()
                with p.open("rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sub.update(chunk)
                hasher.update(f"{relpath}|{sub.hexdigest()}\n".encode())
    return hasher.hexdigest()


def _detect_installed_git_sha() -> str | None:
    """Best-effort detect the git SHA of the installed bridge code.

    Walks up from this module's ``__file__`` looking for a ``.git``
    directory. Resolves the HEAD ref (loose ref first, then
    ``packed-refs`` fallback) or returns the detached-HEAD SHA
    directly. Returns ``None`` if no ``.git`` is reachable
    (e.g. installed from a wheel / PyPI rather than editable from a
    git checkout).
    """
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        gitdir = parent / ".git"
        if gitdir.exists():
            head_file = gitdir / "HEAD"
            if not head_file.exists():
                continue
            head = head_file.read_text().strip()
            if head.startswith("ref: "):
                ref_path = gitdir / head[5:]
                if ref_path.exists():
                    return ref_path.read_text().strip()
                # Packed refs fallback.
                packed = gitdir / "packed-refs"
                if packed.exists():
                    for line in packed.read_text().splitlines():
                        if line.endswith(" " + head[5:]):
                            return line.split(" ")[0]
            else:
                return head  # detached HEAD
    return None


def _provenance(seed: int, data_source: str | Path | None = None) -> dict:
    """Build the ``provenance`` sub-dict for ``SortingData.metadata``.

    Captures software versions, the load timestamp, the RNG master
    seed, the BitGenerator class the bridge contract is pinned to,
    and an audit trail of where and how the run executed: SHA-256 of
    the input data source, git SHA of the installed bridge code,
    OS/platform identifiers, and the BLAS / OpenMP thread-count
    environment (which silently perturbs numerical output on some
    LAPACK paths). The ``seed`` + ``bit_generator`` pair is the
    canonical reproducibility key — log both, since ``Generator``
    does not guarantee cross-version algorithm stability across
    numpy releases.

    Software versions cover every library whose release notes
    plausibly perturb numerical output: ``numpy`` (random, linalg),
    ``scipy`` (statistical tests and fits), ``scikit-learn`` (KMeans
    / PCA determinism contracts), ``xarray`` / ``zarr`` / ``numcodecs``
    (the I/O stack the bridge composes).

    See ``CROSS_CHECKS.md`` → *Bridge-side contracts* and
    *RNG policy* for the field list and reconstruction recipe;
    ``tests/test_imports.py`` covers the documented keys so
    regressions surface in CI.
    """
    return {
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "seed": int(seed),
        "bit_generator": _DEFAULT_BIT_GENERATOR,
        "input_sha256": (_compute_input_sha256(data_source) if data_source is not None else None),
        "git_commit": _detect_installed_git_sha(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_compiler": platform.python_compiler(),
        },
        "threading": {
            "omp_num_threads": os.environ.get("OMP_NUM_THREADS", "unset"),
            "mkl_num_threads": os.environ.get("MKL_NUM_THREADS", "unset"),
            "openblas_num_threads": os.environ.get("OPENBLAS_NUM_THREADS", "unset"),
        },
        "software_versions": {
            "vision-ice-analysis": _safe_version("vision-ice-analysis"),
            "neural-cca": _safe_version("neural-cca"),
            "visioniceio": _safe_version("visioniceio"),
            "numpy": _safe_version("numpy"),
            "scipy": _safe_version("scipy"),
            "scikit-learn": _safe_version("scikit-learn"),
            "xarray": _safe_version("xarray"),
            "zarr": _safe_version("zarr"),
            "numcodecs": _safe_version("numcodecs"),
            "python": sys.version.split()[0],
        },
    }


# ----------------------------------------------------------------------
# Shared loading / reshaping helpers
#
# These three helpers are the *only* place that bridges the LabView /
# zarr layout to the flat arrays the sorter wants.  Keeping them shared
# between ``load_from_visioniceio`` and ``batch_sort_experiment`` means
# the NaN-filtering and angle-mapping contracts cannot drift between the
# single-electrode and batch code paths.
# ----------------------------------------------------------------------


def _load_experiment_dataset(
    data_source: str | Path,
    name: str | None,
) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray, float, dict]:
    """Resolve a data source to the arrays the sorter needs.

    Accepts either a VisionICeIO experiment **directory** (raw LabView
    ``.swa/.spi/.stm/.ana`` or headerless ``.swave/.spike/...`` files)
    or a previously saved ``visioniceio`` **zarr** store.

    Returns ``(waveforms, spike_times, stim_label, sample_rate_hz,
    experiment_metadata)`` where the first three are
    ``xarray.DataArray`` s spanning all electrodes.

    Raises:
        FileNotFoundError: If *data_source* does not exist.
        ValueError: If a raw directory is given without *name*.
    """
    data_source = Path(data_source)
    if not data_source.exists():
        raise FileNotFoundError(f"Data source not found: {data_source}")

    if str(data_source).endswith(".zarr"):
        ds = xr.open_zarr(str(data_source))
        sample_rate = float(ds.attrs.get("SpikeSamplingFrequency", 32_000.0))
        return ds.waveforms, ds.spike_times, ds.stim_label, sample_rate, dict(ds.attrs)

    if name is None:
        raise ValueError(
            "name (the experiment file prefix, e.g. 'c5607a07') is required "
            "for a raw experiment directory; it is only optional for a "
            ".zarr store."
        )
    exp = Experiment()
    exp.load_from_dir(path=str(data_source), name=name, save_as=None)
    exp_metadata = dict(exp.metadata) if exp.metadata else {}
    return (
        exp.waveforms,
        exp.spike_times,
        exp.stim_label,
        float(exp.sample_rate_spike),
        exp_metadata,
    )


def _extract_electrode_arrays(
    waveforms: xr.DataArray,
    spike_times: xr.DataArray,
    electrode: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flatten one electrode to ``(waveforms, spike_times, trials)``.

    Selects the electrode, stacks ``(trials, spikes_idx)`` into one
    spike axis, and applies a **coupled** valid-spike mask: a spike
    survives only when its waveform has at least one non-NaN sample
    *and* its spike time is non-NaN.  Both arrays — and the per-spike
    trial index — are indexed with the *same* mask, so they can never
    fall out of alignment.  (Filtering waveforms and spike times
    independently, as the old upstream batch did, risks a length or
    ordering mismatch whenever the two NaN patterns diverge.)

    Returns:
        ``(waveforms (n_spikes, snippet_len) float64,
        spike_times (n_spikes,) float64,
        trials (n_spikes,) int64)`` — trial-major within the electrode.
    """
    wv = waveforms.sel(electrodes=electrode).stack(sidx_rec=("trials", "spikes_idx"))
    st = spike_times.sel(electrodes=electrode).stack(sidx_rec=("trials", "spikes_idx"))

    valid = (wv.notnull().any(dim="snippet_time") & st.notnull()).values
    valid_idx = np.nonzero(valid)[0]
    wv = wv.isel(sidx_rec=valid_idx)
    st = st.isel(sidx_rec=valid_idx)

    waveforms_out = wv.T.values.astype(np.float64)  # (n_spikes, snippet_length)
    spike_times_out = st.values.astype(np.float64)
    trials_out = wv.trials.values.astype(np.int64)
    return waveforms_out, spike_times_out, trials_out


def _map_angles(
    stim_labels: np.ndarray,
    tlabel2angle: dict[int, float],
    *,
    allow_missing_fill: bool,
) -> np.ndarray:
    """Map per-trial 1-based stimulus labels to angles in degrees.

    When ``allow_missing_fill`` is ``False`` (the tuning path), every
    observed label must be present in *tlabel2angle* or a ``KeyError``
    is raised — otherwise the comprehension would alias unrelated
    conditions or blow up deep in the call stack.  When ``True`` (tuning
    disabled), unmapped labels are filled with ``0.0``: the angles are
    still carried in ``SortingData`` but are never consumed downstream,
    so the placeholder is harmless (e.g. a mixed dot/grating-contrast
    design where labels are not one-orientation-per-stimulus).
    """
    observed = sorted({int(lbl) for lbl in stim_labels})
    missing = [lbl for lbl in observed if lbl not in tlabel2angle]
    if missing:
        if not allow_missing_fill:
            raise KeyError(
                f"Stimulus labels {missing} not found in tlabel2angle mapping. "
                f"Labels in experiment: {observed}. "
                f"Mapped labels: {sorted(tlabel2angle.keys())}. "
                f"Pass a tlabel2angle dict that covers all labels (or disable "
                f"tuning with compute_tuning=False if angles are not meaningful "
                f"for this protocol)."
            )
        tlabel2angle = {**tlabel2angle, **{lbl: 0.0 for lbl in missing}}
    return np.asarray([tlabel2angle[int(lbl)] for lbl in stim_labels], dtype=np.float64)


def load_from_visioniceio(
    data_dir: str | Path,
    name: str,
    electrode: int,
    tlabel2angle: dict[int, float] | None = None,
    *,
    waveform_fs: float | None = None,
    stim_window: tuple[float, float] = (0.5, 2.5),
    stim_frequency: float | None = 2.0,
    seed: int | None = None,
    extra_metadata: dict | None = None,
) -> SortingData:
    """Load an experiment and return a ``SortingData`` container.

    Args:
        data_dir: Path to the experiment directory (or a ``.zarr``
            store previously saved by ``visioniceio``).
        name: Experiment name (file prefix, e.g. ``'c5607a07'``).
            Required for raw directories; ignored for zarr stores.
        electrode: Electrode index to select.
        tlabel2angle: Mapping from 1-based stimulus label to angle in
            degrees.  Defaults to ``neural_cca.steps2degree(12)`` (12
            equidistant steps, Natal convention). For stable OSI/DSI
            estimates, Mazurek et al. 2014
            (*Front. Neural Circuits*) recommend at least 4-5 trials
            per direction; a warning is emitted below that threshold.
        waveform_fs: Waveform sampling rate in Hz. When ``None``
            (default) the value is read from the experiment metadata
            (``SpikeSamplingFrequency``).  A warning is emitted below
            10 kHz, which is uncommon for extracellular spike sorting.
        stim_window: ``(onset, end)`` of the stimulus period within
            each trial, **in seconds**. Spike times outside this window
            are part of the pre/post-stimulus epochs (the implicit
            baseline is ``[0, onset)``; there is no separate
            post-stimulus epoch — ``end`` is also the assumed full
            trial length). The open/closed semantics of the interval
            (whether spikes exactly at ``onset`` / ``end`` are
            included) are determined upstream by
            ``neural_cca.run_sorting_pipeline``; see ``CROSS_CHECKS.md``
            → *stim_window interval semantics*. Matches
            ``SortingData.stim_window``.
        stim_frequency: Temporal frequency of the visual stimulus, in Hz.
            ``None`` when not applicable.
        seed: RNG master seed recorded into
            ``SortingData.metadata['provenance']['seed']`` for
            reproducibility. When ``None`` a fresh ~128-bit seed is
            drawn from OS entropy via ``SeedSequence()``. Callers
            should forward this same value to ``run_sorting_pipeline``
            via its ``rng=`` argument (upstream accepts
            ``int | Generator | None``); the bridge's
            :func:`batch_sort_experiment` does this translation
            automatically when its own ``seed=`` is passed.
            Downstream RNG must be constructed as
            ``Generator(PCG64DXSM(SeedSequence(seed)))`` per the
            bridge's RNG policy (``CROSS_CHECKS.md`` → *RNG policy*);
            ``np.random.default_rng()`` is **not** acceptable as it
            uses PCG64 with the known parallel-stream correlation bug
            (numpy/numpy#16313). The recorded ``provenance`` dict also
            includes ``bit_generator`` (``"PCG64DXSM"``) so the seed
            is unambiguously interpretable across numpy versions.
        extra_metadata: Optional dict merged into
            ``SortingData.metadata``. Use to record subject ID, brain
            area, probe geometry, input file checksums, or any
            site-specific fields needed for FAIR / NWB reporting.
            Bridge-managed keys (``electrode``, ``name``, ``data_dir``,
            ``experiment_metadata``, ``provenance``) take precedence on
            collision — callers cannot accidentally overwrite them.

    Returns:
        ``SortingData`` container ready for the sorting pipeline.

    Raises:
        KeyError: If ``tlabel2angle`` does not cover every stimulus
            label present in the experiment.
    """
    if tlabel2angle is None:
        tlabel2angle = steps2degree(12)
    if seed is None:
        # SeedSequence() draws ~128-bit OS entropy and mixes it
        # internally — the recommended path over small-int seeds,
        # PIDs, timestamps, or `np.random.default_rng()` (PCG64
        # parallel-stream bug, numpy/numpy#16313). The recorded seed
        # is the 128-bit `.entropy` integer; downstream reconstructs
        # via SeedSequence(seed). See CROSS_CHECKS.md → RNG policy.
        seed = int(SeedSequence().entropy)

    # --- Load experiment (skip zarr export) ---
    wv_da, st_da, stim_da, sample_rate, exp_metadata = _load_experiment_dataset(data_dir, name)

    if waveform_fs is None:
        waveform_fs = sample_rate
    if waveform_fs < 10_000:
        warnings.warn(
            f"waveform_fs={waveform_fs} Hz is below the 10 kHz floor "
            "typical for extracellular spike sorting (most rigs run "
            "20-30 kHz). Verify the upstream metadata key "
            "'SpikeSamplingFrequency'.",
            stacklevel=2,
        )

    # --- Waveforms + spike times for this electrode (coupled NaN mask) ---
    waveforms, spike_times, trials = _extract_electrode_arrays(wv_da, st_da, electrode)

    # --- Stimulus angles (strict: every label must be mapped) ---
    stim_labels = stim_da.values
    angles = _map_angles(stim_labels, tlabel2angle, allow_missing_fill=False)
    n_trials = int(len(stim_labels))

    # Sampling-adequacy check: Mazurek et al. 2014 (Front. Neural
    # Circ.) recommend >=4-5 trials per direction for stable OSI/DSI
    # estimates. Below that, the indices are noise-dominated.
    n_directions = len({int(lbl) for lbl in stim_labels})
    if n_directions > 0:
        trials_per_direction = n_trials / n_directions
        if trials_per_direction < 5:
            warnings.warn(
                f"{trials_per_direction:.1f} trials per direction "
                f"({n_trials} trials / {n_directions} directions) "
                "is below the Mazurek 2014 recommendation of >=5 for "
                "stable OSI/DSI estimates.",
                stacklevel=2,
            )

    # --- Metadata: bridge-managed fields + provenance + caller extras.
    # Bridge keys take precedence so callers can't accidentally overwrite
    # the contract (see CROSS_CHECKS.md → Bridge-side contracts).
    bridge_metadata = {
        "electrode": electrode,
        "name": name,
        "data_dir": str(data_dir),
        "experiment_metadata": exp_metadata,
        "provenance": _provenance(seed, data_dir),
    }
    if extra_metadata:
        metadata = {**extra_metadata, **bridge_metadata}
    else:
        metadata = bridge_metadata

    return SortingData(
        waveforms=waveforms,
        spike_times=spike_times,
        trials=trials,
        angles=angles,
        waveform_fs=waveform_fs,
        n_trials=n_trials,
        stim_window=stim_window,
        stim_frequency=stim_frequency,
        metadata=metadata,
    )


def batch_sort_experiment(
    data_source: str | Path,
    name: str | None = None,
    *,
    output_path: str | Path | None = None,
    electrode_indices: Sequence[int] | None = None,
    n_clusters: int | None = None,
    k_range: Sequence[int] = range(2, 6),
    tlabel2angle: dict[int, float] | None = None,
    n_angle_steps: int | None = None,
    stim_window: tuple[float, float] | None = None,
    stim_frequency: float | None = None,
    waveform_fs: float | None = None,
    refractory_period: float = 0.001,
    compute_spike_train_stats: bool = True,
    compute_tuning: bool = True,
    seed: int | None = None,
    **pipeline_kwargs,
) -> dict:
    """Batch spike sorting across all electrodes (writes a zarr summary).

    Loads a VisionICeIO experiment (directory or zarr store) once,
    iterates over electrodes, runs :func:`run_sorting_pipeline` on each,
    computes optional spike-train statistics and per-cluster firing
    rates, and writes a consolidated zarr store.  All loading and
    reshaping reuses the same helpers as :func:`load_from_visioniceio`,
    so the single-electrode and batch paths share one extraction
    contract.

    ``stim_window`` and an angle mapping are **required** — there is no
    library default because both are recording-specific:

    * ``stim_window=(onset, end)`` in seconds (e.g. ``(0.5, 2.5)`` for a
      500 ms baseline + 2 s stimulus).
    * ``tlabel2angle={1: 0.0, 2: 30.0, ...}`` *or* ``n_angle_steps=12``
      (the LabView 30-degree convention; see :func:`steps2degree`).

    Args:
        data_source: VisionICeIO experiment directory (raw LabView
            files) or a ``.zarr`` store saved by ``visioniceio``.
        name: Experiment file prefix.  Required for raw directories;
            ignored for zarr stores.
        output_path: Where to write the results zarr.  Defaults to
            ``<data_source stem>_sorted.zarr`` next to the source.
        electrode_indices: Which electrodes to process.  ``None``
            processes all present in the data.
        n_clusters: Fixed cluster count per electrode.  ``None`` →
            auto-select via silhouette over *k_range*.
        k_range: Candidate k values for auto-selection.
        tlabel2angle: Mapping from 1-based stimulus label to angle.
            **Required** unless *n_angle_steps* is given.
        n_angle_steps: Number of equidistant angle steps (builds the
            mapping via :func:`steps2degree`).  **Required** unless
            *tlabel2angle* is given.
        stim_window: ``(onset, end)`` of the stimulus period within each
            trial (seconds).  **Required.**
        stim_frequency: Temporal frequency of the stimulus (Hz).
            ``None`` disables F1/F0 computation in the per-cluster
            tuning block.
        waveform_fs: Waveform sampling rate (Hz).  ``None`` reads it
            from the experiment metadata.
        refractory_period: Refractory period for RPV computation (s).
        compute_spike_train_stats: Compute per-cluster spike-train
            statistics (MFR / CV / LvR). Renamed from ``compute_sta``;
            ``sta`` now denotes spike-triggered average upstream.
        compute_tuning: Compute per-cluster orientation selectivity.
            When ``False``, unmapped stimulus labels are tolerated.
        seed: RNG seed for reproducible stochastic clustering.
            Forwarded to ``run_sorting_pipeline`` as ``rng=seed`` and
            recorded in the output store's attributes.  Required for
            publishable runs.  (An explicit ``rng=`` in
            ``pipeline_kwargs`` is honoured when ``seed`` is ``None``.)
        **pipeline_kwargs: Extra keyword arguments forwarded verbatim to
            :func:`run_sorting_pipeline` per electrode (e.g.
            ``min_silhouette=``, ``preprocess=``, ``pca_components=``,
            ``n_init=``, ``bin_size=``, ``invert_waveforms=``).

    Returns:
        Summary ``dict`` with keys:
            ``result_path`` — path to output zarr store.
            ``n_electrodes_processed`` — count of successful electrodes.
            ``n_clusters_total`` — total clusters across all electrodes.
            ``summary`` — per-electrode dict with ``quality``,
            ``n_clusters``, ``n_spikes``, and optional ``spike_train_metrics`` /
            ``os_metrics``.

    Raises:
        FileNotFoundError: If *data_source* does not exist.
        ValueError: If *stim_window* is ``None``, or if both
            *tlabel2angle* and *n_angle_steps* are ``None``.
        KeyError: If *compute_tuning* is ``True`` and *tlabel2angle*
            does not cover every observed stimulus label.

    Note:
        The returned summary does **not** include per-spike
        ``cluster_labels``. For per-spike labels, run
        :func:`load_from_visioniceio` + :func:`run_sorting_pipeline`
        per electrode.
    """
    if stim_window is None:
        raise ValueError(
            "stim_window is required. Pass e.g. stim_window=(0.5, 2.5) "
            "for a 500ms baseline + 2s stimulus protocol. There is no "
            "library default because stim windows are recording-specific."
        )
    if tlabel2angle is None and n_angle_steps is None:
        raise ValueError(
            "Either tlabel2angle or n_angle_steps is required. "
            "Pass tlabel2angle={1: 0.0, 2: 30.0, ...} or n_angle_steps=12 "
            "(LabView 30-degree convention). See "
            "vision_ice_analysis.steps2degree for the helper."
        )
    if tlabel2angle is None:
        tlabel2angle = steps2degree(n_angle_steps)

    # Bridge keeps the friendly ``seed=`` name; upstream takes ``rng``.
    # An explicit ``rng=`` in kwargs only wins when no ``seed`` is given.
    rng = seed if seed is not None else pipeline_kwargs.pop("rng", None)

    wv_da, st_da, stim_da, sample_rate, exp_metadata = _load_experiment_dataset(data_source, name)
    if waveform_fs is None:
        waveform_fs = sample_rate

    src_path = Path(data_source)
    if output_path is None:
        output_path = src_path.parent / (src_path.stem + "_sorted.zarr")
    output_path = Path(output_path)

    # --- Stimulus angles (relaxed when tuning is off) ---
    stim_labels = stim_da.values
    angles = _map_angles(stim_labels, tlabel2angle, allow_missing_fill=not compute_tuning)
    n_trials = int(len(stim_labels))

    # --- Determine electrodes ---
    all_electrodes = wv_da.electrodes.values
    if electrode_indices is not None:
        all_electrodes = np.array([e for e in electrode_indices if e in all_electrodes])

    # --- Process each electrode ---
    summary: dict[int, dict] = {}
    all_electrode_results: list[dict] = []
    s_on, s_end = stim_window
    stim_dur = s_end - s_on

    for elec_idx in all_electrodes:
        elec = int(elec_idx)
        try:
            waveforms, spike_times, trials_arr = _extract_electrode_arrays(wv_da, st_da, elec)

            if len(waveforms) < 10:
                warnings.warn(
                    f"Electrode {elec}: only {len(waveforms)} spikes, skipping.",
                    stacklevel=2,
                )
                continue

            data = SortingData(
                waveforms=waveforms,
                spike_times=spike_times,
                trials=trials_arr,
                angles=angles,
                waveform_fs=float(waveform_fs),
                n_trials=n_trials,
                stim_window=stim_window,
                stim_frequency=stim_frequency,
                metadata={"electrode": elec},
            )

            result = run_sorting_pipeline(
                data,
                n_clusters=n_clusters,
                k_range=k_range,
                rng=rng,
                refractory_period=refractory_period,
                compute_os=compute_tuning,
                plot=False,
                **pipeline_kwargs,
            )

            # --- Spike-train statistics per cluster ---
            spike_train_metrics: dict[int, dict] | None = None
            if compute_spike_train_stats:
                spike_train_metrics = {}
                for cl in np.unique(result.cluster_labels):
                    spike_train_metrics[int(cl)] = minimal_spike_train_analysis(
                        spike_times,
                        trials=trials_arr,  # within-trial ISIs only (no cross-trial pseudo-ISIs)
                        cluster_labels=result.cluster_labels,
                        cluster_id=int(cl),
                        refractory_period=refractory_period,
                        stim_window=stim_window,
                        n_trials=n_trials,
                    )

            # --- Firing rates per trial per cluster ---
            fr_by_trial: dict[int, np.ndarray] = {}
            for cl in np.unique(result.cluster_labels):
                rates = np.zeros(n_trials, dtype=np.float64)
                cl_mask = result.cluster_labels == cl
                cl_st = spike_times[cl_mask]
                cl_tr = trials_arr[cl_mask]
                for t in range(n_trials):
                    t_spikes = cl_st[cl_tr == t]
                    rates[t] = np.sum((t_spikes > s_on) & (t_spikes <= s_end)) / stim_dur
                fr_by_trial[int(cl)] = rates

            # --- Spike times per trial per cluster ---
            st_by_trial: dict[int, dict[int, np.ndarray]] = {}
            for cl in np.unique(result.cluster_labels):
                cl_mask = result.cluster_labels == cl
                cl_st = spike_times[cl_mask]
                cl_tr = trials_arr[cl_mask]
                st_by_trial[int(cl)] = {t: cl_st[cl_tr == t] for t in range(n_trials)}

            all_electrode_results.append(
                {
                    "electrode": elec,
                    "result": result,
                    "spike_train_metrics": spike_train_metrics,
                    "fr_by_trial": fr_by_trial,
                    "st_by_trial": st_by_trial,
                }
            )

            elec_summary = {
                "n_clusters": result.n_clusters,
                "quality": result.quality,
                "n_spikes": len(waveforms),
            }
            if spike_train_metrics:
                elec_summary["spike_train_metrics"] = spike_train_metrics
            if result.os_metrics:
                elec_summary["os_metrics"] = result.os_metrics
            summary[elec] = elec_summary

        except Exception as e:
            warnings.warn(
                f"Electrode {elec}: processing failed — {e}",
                stacklevel=2,
            )
            continue

    # --- Build and save output zarr ---
    n_proc = len(all_electrode_results)
    if n_proc == 0:
        warnings.warn("No electrodes were successfully processed.", stacklevel=2)
        return {
            "result_path": str(output_path),
            "n_electrodes_processed": 0,
            "n_clusters_total": 0,
            "summary": summary,
        }

    max_clusters = max(r["result"].n_clusters for r in all_electrode_results)
    total_clusters = sum(r["result"].n_clusters for r in all_electrode_results)

    # Max spikes per trial across all results (ragged → NaN-padded).
    max_spk_per_trial = 0
    for r in all_electrode_results:
        for cl_trials in r["st_by_trial"].values():
            for st_arr in cl_trials.values():
                max_spk_per_trial = max(max_spk_per_trial, len(st_arr))
    max_spk_per_trial = max(max_spk_per_trial, 1)

    processed_electrodes = np.array([r["electrode"] for r in all_electrode_results], dtype=np.int64)

    # float64 throughout: spike times are seconds with microsecond
    # precision; float32 (~7 digits) silently loses tens of microseconds
    # near 100 s and would not round-trip the io_util zarr writers.
    spike_times_arr = np.full(
        (n_proc, max_clusters, n_trials, max_spk_per_trial),
        np.nan,
        dtype=np.float64,
    )
    firing_rates_arr = np.full(
        (n_proc, max_clusters, n_trials),
        np.nan,
        dtype=np.float64,
    )
    n_clusters_arr = np.zeros(n_proc, dtype=np.int32)

    for i, r in enumerate(all_electrode_results):
        n_clusters_arr[i] = r["result"].n_clusters
        for cl_idx, cl in enumerate(sorted(r["fr_by_trial"].keys())):
            firing_rates_arr[i, cl_idx, :] = r["fr_by_trial"][cl]
            for t in range(n_trials):
                st = r["st_by_trial"][cl].get(t, np.array([]))
                spike_times_arr[i, cl_idx, t, : len(st)] = st

    out_ds = xr.Dataset(
        data_vars={
            "spike_times_by_cluster": xr.DataArray(
                spike_times_arr,
                dims=("electrodes", "clusters", "trials", "spike_idx"),
                attrs={"description": "Spike times per cluster per trial, NaN-padded"},
            ),
            "firing_rate_by_trial": xr.DataArray(
                firing_rates_arr,
                dims=("electrodes", "clusters", "trials"),
                attrs={"description": "Firing rate (Hz) per cluster per trial"},
            ),
            "trial_angles": xr.DataArray(
                angles,
                dims=("trials",),
                attrs={"description": "Stimulus angle (degrees) per trial"},
            ),
            "n_clusters": xr.DataArray(
                n_clusters_arr,
                dims=("electrodes",),
                attrs={"description": "Number of clusters per electrode"},
            ),
        },
        coords={
            "electrodes": processed_electrodes,
            "clusters": np.arange(max_clusters),
            "trials": np.arange(n_trials),
            "spike_idx": np.arange(max_spk_per_trial),
        },
        attrs={
            "description": "Batch spike sorting results",
            "seed": int(seed) if seed is not None else "unset",
            "bit_generator": _DEFAULT_BIT_GENERATOR,
            "refractory_period": refractory_period,
            "stim_window": [float(stim_window[0]), float(stim_window[1])],
            **{k: str(v) for k, v in exp_metadata.items()},
        },
    )

    out_ds.to_zarr(str(output_path), mode="w")

    return {
        "result_path": str(output_path),
        "n_electrodes_processed": n_proc,
        "n_clusters_total": total_clusters,
        "summary": summary,
    }
