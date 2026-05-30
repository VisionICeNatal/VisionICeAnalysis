"""Spike-sorting data extraction from VisionICeIO experiments.

Converts the xarray-based ``Experiment`` structure into the flat numpy
arrays expected by the spike-sorting pipeline in :mod:`neural_cca`.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import warnings
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import numpy as np
from neural_cca import SortingData, steps2degree
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
        data_dir: Path to the experiment directory.
        name: Experiment name (file prefix, e.g. ``'c5607a07'``).
        electrode: Electrode index to select.
        tlabel2angle: Mapping from 1-based stimulus label to angle in
            degrees.  Defaults to ``neural_cca.steps2degree(12)`` (12
            equidistant steps, Natal convention). For stable OSI/DSI
            estimates, Mazurek et al. 2014
            (*Front. Neural Circuits*) recommend at least 4-5 trials
            per direction; a warning is emitted below that threshold.
        waveform_fs: Waveform sampling rate in Hz. When ``None``
            (default) the value is read from ``exp.sample_rate_spike``.
            A warning is emitted below 10 kHz, which is uncommon for
            extracellular spike sorting.
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
    exp = Experiment()
    exp.load_from_dir(path=str(data_dir), name=name, save_as=None)

    if waveform_fs is None:
        waveform_fs = float(exp.sample_rate_spike)
    if waveform_fs < 10_000:
        warnings.warn(
            f"waveform_fs={waveform_fs} Hz is below the 10 kHz floor "
            "typical for extracellular spike sorting (most rigs run "
            "20-30 kHz). Verify the upstream metadata key "
            "'SpikeSamplingFrequency'.",
            stacklevel=2,
        )

    # --- Waveforms: (electrodes, trials, spikes_idx, snippet_time)
    #     → select electrode → stack → shared NaN mask → (n_spikes, snippet_time) ---
    wv = exp.waveforms.sel(electrodes=electrode)
    wv = wv.stack(sidx_rec=("trials", "spikes_idx"))

    # --- Spike times ---
    st = exp.spike_times.sel(electrodes=electrode)
    st = st.stack(sidx_rec=("trials", "spikes_idx"))

    # --- Shared valid-spike mask: require both waveform and spike time ---
    valid = (wv.notnull().any(dim="snippet_time") & st.notnull()).values
    valid_idx = np.nonzero(valid)[0]
    wv = wv.isel(sidx_rec=valid_idx)
    st = st.isel(sidx_rec=valid_idx)

    waveforms = wv.T.values.astype(np.float64)  # (n_spikes, snippet_length)
    spike_times = st.values.astype(np.float64)

    # --- Trial indices (from the multi-index created by stack) ---
    trials = wv.trials.values.astype(np.int64)

    # --- Stimulus angles ---
    unique_labels = sorted(set(int(w) for w in exp.stim_label.data))
    missing = [lbl for lbl in unique_labels if lbl not in tlabel2angle]
    if missing:
        raise KeyError(
            f"Stimulus labels {missing} not found in tlabel2angle mapping. "
            f"Labels in experiment: {unique_labels}. "
            f"Mapped labels: {sorted(tlabel2angle.keys())}. "
            f"Pass a tlabel2angle dict that covers all labels."
        )
    angles = np.array(
        [tlabel2angle[int(w)] for w in exp.stim_label.data],
        dtype=np.float64,
    )

    # Sampling-adequacy check: Mazurek et al. 2014 (Front. Neural
    # Circ.) recommend >=4-5 trials per direction for stable OSI/DSI
    # estimates. Below that, the indices are noise-dominated.
    n_directions = len(unique_labels)
    if n_directions > 0:
        trials_per_direction = len(exp.stim_label) / n_directions
        if trials_per_direction < 5:
            warnings.warn(
                f"{trials_per_direction:.1f} trials per direction "
                f"({len(exp.stim_label)} trials / {n_directions} directions) "
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
        "experiment_metadata": exp.metadata,
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
        n_trials=int(len(exp.stim_label)),
        stim_window=stim_window,
        stim_frequency=stim_frequency,
        metadata=metadata,
    )


def batch_sort_experiment(
    data_source: str | Path,
    name: str | None = None,
    *,
    seed: int | None = None,
    **kwargs,
) -> dict:
    """Batch spike sorting across all electrodes (zarr summary).

    Thin re-export of :func:`neural_cca.sorting.batch.batch_sort_experiment`.
    See that function for full documentation and the list of keyword
    arguments.

    Args:
        data_source: Path to either a VisionICeIO experiment directory
            (with ``.swa/.spi/.stm/.ana`` files) or a previously saved
            zarr store.
        name: Experiment file prefix (e.g. ``'c5607a07'``). Required for
            raw directories; ignored for zarr stores.
        seed: RNG seed forwarded to the upstream sorter for
            reproducible stochastic clustering. Required for
            publishable runs. Translated to upstream ``rng=`` —
            ``neural_cca.sorting.batch.batch_sort_experiment`` accepts
            ``rng: Generator | int | None``, so passing an integer
            seed there yields a reproducible
            ``np.random.default_rng(seed)``-equivalent stream.  The
            translation is done bridge-side so the bridge can keep
            the friendlier ``seed=`` name (matching every other
            ``load_from_visioniceio`` callsite) without leaking the
            upstream-specific kwarg name onto callers.  Callers that
            need a fully-seeded ``PCG64DXSM`` Generator (RNG policy in
            ``CROSS_CHECKS.md``) should construct it explicitly and
            pass ``rng=`` through ``**kwargs`` instead.
        **kwargs: Forwarded verbatim to the upstream
            ``neural_cca.sorting.batch.batch_sort_experiment``.  Upstream
            additionally forwards any unrecognised keys to
            ``run_sorting_pipeline`` per electrode, so options like
            ``min_silhouette=`` or ``preprocess=`` can be set here.

    Returns:
        Summary ``dict`` with keys:
            ``result_path`` — path to output zarr store.
            ``n_electrodes_processed`` — count of successful electrodes.
            ``n_clusters_total`` — total clusters across all electrodes.
            ``summary`` — per-electrode dict with ``quality``, ``n_clusters``,
            optional STA / tuning metrics.

    Note:
        The returned summary does **not** include per-spike
        ``cluster_labels``. For per-spike labels, run
        :func:`load_from_visioniceio` + :func:`neural_cca.run_sorting_pipeline`
        per electrode.
    """
    from neural_cca.sorting.batch import batch_sort_experiment as _batch

    if seed is not None:
        # Translate the bridge-side ``seed=`` to the upstream's ``rng=``.
        # Upstream accepts ``int | Generator | None``, so an int suffices
        # and avoids materialising a Generator the bridge doesn't need.
        # ``setdefault`` lets an explicit ``rng=`` in kwargs win over a
        # default ``seed=`` (caller can mix the two when migrating code).
        kwargs.setdefault("rng", seed)
    return _batch(data_source, name, **kwargs)
