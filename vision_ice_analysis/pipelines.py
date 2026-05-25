"""Spike-sorting data extraction from VisionICeIO experiments.

Converts the xarray-based ``Experiment`` structure into the flat numpy
arrays expected by the spike-sorting pipeline in :mod:`neural_cca`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from neural_cca import SortingData, steps2degree
from visioniceio import Experiment


def load_from_visioniceio(
    data_dir: str | Path,
    name: str,
    electrode: int,
    tlabel2angle: dict[int, float] | None = None,
    *,
    waveform_fs: float | None = None,
    stim_window: tuple[float, float] = (0.5, 2.5),
    stim_frequency: float | None = 2.0,
) -> SortingData:
    """Load an experiment and return a ``SortingData`` container.

    Args:
        data_dir: Path to the experiment directory.
        name: Experiment name (file prefix, e.g. ``'c5607a07'``).
        electrode: Electrode index to select.
        tlabel2angle: Mapping from 1-based stimulus label to angle in
            degrees.  Defaults to ``neural_cca.steps2degree(12)`` (12
            equidistant steps, Natal convention).
        waveform_fs: Waveform sampling rate in Hz.  When ``None``
            (default) the value is read from ``exp.sample_rate_spike``.
        stim_window: ``(onset, end)`` of the stimulus period within each
            trial (seconds). Spikes that fall in ``(onset, end]`` are
            part of the stimulated portion; ``end`` is also the assumed
            full trial length.  Matches ``SortingData.stim_window``.
        stim_frequency: Temporal frequency of the visual stimulus (Hz).
            ``None`` when not applicable.

    Returns:
        ``SortingData`` container ready for the sorting pipeline.

    Raises:
        KeyError: If ``tlabel2angle`` does not cover every stimulus
            label present in the experiment.
    """
    if tlabel2angle is None:
        tlabel2angle = steps2degree(12)

    # --- Load experiment (skip zarr export) ---
    exp = Experiment()
    exp.load_from_dir(path=str(data_dir), name=name, save_as=None)

    if waveform_fs is None:
        waveform_fs = float(exp.sample_rate_spike)

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

    return SortingData(
        waveforms=waveforms,
        spike_times=spike_times,
        trials=trials,
        angles=angles,
        waveform_fs=waveform_fs,
        n_trials=int(len(exp.stim_label)),
        stim_window=stim_window,
        stim_frequency=stim_frequency,
        metadata={
            "electrode": electrode,
            "name": name,
            "data_dir": str(data_dir),
            "experiment_metadata": exp.metadata,
        },
    )


def batch_sort_experiment(
    data_source: str | Path,
    name: str | None = None,
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
        **kwargs: Forwarded to the upstream
            ``neural_cca.sorting.batch.batch_sort_experiment``.

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

    return _batch(data_source, name, **kwargs)
