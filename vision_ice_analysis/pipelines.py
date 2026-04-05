"""Spike-sorting data extraction from VisionICeIO experiments.

Converts the xarray-based Experiment structure into the flat numpy
arrays expected by the spike-sorting pipeline.

Note:
    This module imports ``SortingData`` from ``mini_analysis_cidbn``, which must
    be installed (i.e. pip install mini-analysis-cidbn).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from visioniceio import Experiment, read_spike_new, write_ssort

try:
    from mini_analysis_cidbn.mini_sorting.io_util import SortingData
except ImportError as e:
    raise ImportError(
        "mini_analysis_cidbn must be installed. Run: pip install mini-analysis-cidbn"
    ) from e


def load_from_visioniceio(
    data_dir: str | Path,
    name: str,
    electrode: int,
    tlabel2angle: dict[int, float] | None = None,
    *,
    waveform_fs: float | None = None,
    trial_duration: float = 2.5,
    stimulus_onset: float = 0.5,
    stimulus_frequency: float | None = 2.0,
):
    """Load an experiment and return a ``SortingData`` container.

    Args:
        data_dir: Path to the experiment directory.
        name: Experiment name (file prefix, e.g. ``'c5607a07'``).
        electrode: Electrode index to select.
        tlabel2angle: Mapping from 1-based stimulus label to angle in
            degrees.  Defaults to the Natal convention (12 labels,
            30° steps starting at 0°).
        waveform_fs: Waveform sampling rate in Hz.  When ``None``
            (default) the value is read from the experiment metadata
            (``SpikeSamplingFrequency``).
        trial_duration: Duration of one trial in seconds.
        stimulus_onset: Stimulus onset within a trial in seconds.
        stimulus_frequency: Temporal frequency of the stimulus (Hz).

    Returns:
        ``SortingData`` container ready for the sorting pipeline.

    Raises:
        ImportError: If ``mini_analysis_cidbn`` cannot be imported.
    """
    if tlabel2angle is None:
        # Default: 12 equidistant steps (Natal convention)
        tlabel2angle = {i: (i - 1) * 30.0 for i in range(1, 13)}

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
        trial_duration=trial_duration,
        stimulus_onset=stimulus_onset,
        stimulus_frequency=stimulus_frequency,
        metadata={
            "electrode": electrode,
            "name": name,
            "data_dir": str(data_dir),
            "experiment_metadata": exp.metadata,
        },
    )


def export_ssort(
    data_dir: str | Path,
    name: str,
    sorting_results: dict[int, object],
    filepath: str | Path | None = None,
    n_fields: int = 10,
) -> str:
    """Export spike-sorting results to a ``.ssort`` file.

    Converts per-electrode ``SortingResult`` objects into the
    trial-major, channel-minor binary format expected by LabView.

    Args:
        data_dir: Experiment directory (for reading spike indices).
        name: Experiment file prefix (e.g. ``'c5607a07'``).
        sorting_results: Dict mapping electrode index to a
            ``SortingResult`` (must have ``.labels`` attribute).
        filepath: Output ``.ssort`` path. Defaults to
            ``<data_dir>/<name>.ssort``.
        n_fields: Number of float32 columns per row (default 10).

    Returns:
        Filepath the ``.ssort`` file was written to, as a string.
    """
    data_dir = Path(data_dir)

    # --- Load spike indices to reconstruct per-record structure ---
    # NOTE: Ideally this I/O should be handled by visioniceio (see below).
    spike_path = data_dir / (name + ".spike")
    spi_path = data_dir / (name + ".spi")
    if spike_path.exists():
        spike_data = read_spike_new(str(spike_path))
    elif spi_path.exists():
        from visioniceio import read_data

        spike_data = read_data(str(spi_path), "int32", 1)
    else:
        raise FileNotFoundError(
            f"No spike file found for '{name}'. Looked for:\n  {spike_path}\n  {spi_path}"
        )

    # Load experiment via public API to get metadata dimensions
    exp = Experiment()
    exp.load_from_dir(path=str(data_dir), name=name, save_as=None)
    n_trials = exp.metadata["NofTrials"]
    n_electrodes = exp.metadata["NofSpikeChannels"]

    # --- Build per-record (trial-major, channel-minor) label/index lists ---
    labels_per_record: list[np.ndarray] = []
    indices_per_record: list[np.ndarray] = []

    # Pre-compute cumulative spike counts per electrode so we can slice
    # result.labels without recomputing inside the inner loop.
    cumsum_per_ch: dict[int, np.ndarray] = {}
    for ch in sorting_results:
        counts = [len(spike_data[t * n_electrodes + ch]) for t in range(n_trials)]
        cumsum_per_ch[ch] = np.cumsum([0] + counts)

    for trial in range(n_trials):
        for ch in range(n_electrodes):
            rec_idx = trial * n_electrodes + ch
            spike_indices = spike_data[rec_idx].astype(np.float32)
            n_spikes = len(spike_indices)

            if ch in sorting_results and n_spikes > 0:
                result = sorting_results[ch]
                start = int(cumsum_per_ch[ch][trial])
                end = int(cumsum_per_ch[ch][trial + 1])
                if end - start != n_spikes:
                    raise ValueError(
                        f"Spike count mismatch for electrode {ch}, trial {trial}: "
                        f"spike file has {n_spikes} spikes, "
                        f"sorting result has {end - start}"
                    )
                rec_labels = np.asarray(result.labels[start:end], dtype=np.int32)
            else:
                rec_labels = np.zeros(n_spikes, dtype=np.int32)

            labels_per_record.append(rec_labels)
            indices_per_record.append(spike_indices)

    if filepath is None:
        filepath = data_dir / (name + ".ssort")

    write_ssort(str(filepath), labels_per_record, indices_per_record, n_fields=n_fields)
    return str(filepath)


def batch_sort_experiment(
    data_source: str | Path,
    name: str,
    **kwargs,
) -> dict:
    """Batch spike sorting across all electrodes.

    Convenience re-export of
    ``mini_analysis_cidbn.mini_sorting.batch.batch_sort_experiment``.
    See that function for full documentation.

    Args:
        data_source: Path to the experiment directory.
        name: Experiment file prefix (e.g. ``'c5607a07'``).
        **kwargs: Additional keyword arguments forwarded to the upstream
            ``batch_sort_experiment`` function.

    Returns:
        Dict mapping electrode indices to ``SortingResult`` objects.

    Raises:
        ImportError: If ``mini_analysis_cidbn`` is not installed.
    """
    try:
        from mini_analysis_cidbn.mini_sorting.batch import batch_sort_experiment as _batch
    except ImportError as e:
        raise ImportError(
            "mini_analysis_cidbn must be installed. Run: pip install mini-analysis-cidbn"
        ) from e
    return _batch(data_source, name, **kwargs)
