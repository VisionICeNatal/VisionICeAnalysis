# Cross-checks against upstream packages

This bridge has no runtime logic of its own beyond reshaping data — every
symbol it touches in [`neural_cca`](https://github.com/goecidbn/neural_cca)
or [`visioniceio`](https://github.com/VisionICeNatal/VisionICeIO) is an
implicit contract. Verify each item below before cutting a release, or
after bumping either upstream.

Items marked **✓** are exercised by `pytest` (`tests/test_imports.py`).
Everything else is runtime-only — drift surfaces as `AttributeError`,
`KeyError`, `TypeError`, or silently-wrong output.

---

## `neural_cca`

### Importable symbols

Failure to import any of these breaks `import vision_ice_analysis`.

- ✓ `from neural_cca import SortingData`
- ✓ `from neural_cca import SortingResult`
- ✓ `from neural_cca import run_sorting_pipeline`
- ✓ `from neural_cca import steps2degree`
- `from neural_cca.sorting.batch import batch_sort_experiment` *(lazy
  import inside `pipelines.batch_sort_experiment`; not loaded until
  first call)*

### `SortingData` constructor

Used in [`pipelines.load_from_visioniceio`](vision_ice_analysis/pipelines.py).
The bridge passes the full keyword set below; all of them are exercised
by `test_sorting_data_signature` (**✓**), so an upstream rename or
required-arg change breaks tests immediately.

| kwarg            | type                                          |
| ---------------- | --------------------------------------------- |
| `waveforms`      | `np.ndarray (n_spikes, snippet_len)` float64  |
| `spike_times`    | `np.ndarray (n_spikes,)` float64              |
| `trials`         | `np.ndarray (n_spikes,)` int64                |
| `angles`         | `np.ndarray (n_trials,)` float64              |
| `waveform_fs`    | float (Hz)                                    |
| `n_trials`       | int                                           |
| `stim_window`    | `(onset, end)` tuple of float seconds         |
| `stim_frequency` | float \| None                                 |
| `metadata`       | dict                                          |

Attributes used downstream:

- ✓ `SortingData.n_spikes`
- ✓ `SortingData.stim_window`
- ✓ `SortingData.stimulus_duration` (must equal `stim_window[1] - stim_window[0]`)

### `SortingResult`

The bridge re-exports it but does not access fields itself. Consumers
of `run_sorting_pipeline(...)` (and any future `.ssort` re-export) rely
on:

- Field `cluster_labels` — order **must match** the trial-major,
  NaN-filtered order produced by `load_from_visioniceio` (see
  *File-format invariants* under ``visioniceio`` below). This was
  previously named `labels`; a silent rename back will not raise.

### `steps2degree`

- Signature: `steps2degree(n: int) -> dict[int, float]`
- `steps2degree(12)` must equal `{i: (i - 1) * 30.0 for i in range(1, 13)}`
  (1-based keys, 30° spacing, starts at 0°). This is the default
  `tlabel2angle` in `load_from_visioniceio`. Any change to indexing
  (0-based vs 1-based), starting angle, or step size silently re-maps
  every Natal-convention recording.

### `run_sorting_pipeline`

- Signature: `(data: SortingData, plot: bool = ...) -> SortingResult`
- Returns a `SortingResult` whose `cluster_labels` length equals
  `data.n_spikes`.

### `batch_sort_experiment` (submodule)

- Import path: `neural_cca.sorting.batch.batch_sort_experiment`
- Signature: `(data_source, name=None, **kwargs) -> dict`
- Returned dict must contain keys `result_path`,
  `n_electrodes_processed`, `n_clusters_total`, `summary` (per
  `pipelines.batch_sort_experiment` docstring and `README.md`).

---

## `visioniceio`

### Importable symbols

- `from visioniceio import Experiment` *(eager import in
  `pipelines.py`; failure breaks `import vision_ice_analysis`)*

### `Experiment` API

Used in [`pipelines.load_from_visioniceio`](vision_ice_analysis/pipelines.py):

- `Experiment()` — zero-arg constructor
- `exp.load_from_dir(path: str, name: str, save_as=None)` — loads in
  place; `save_as=None` must suppress the zarr-export side effect
- `exp.sample_rate_spike` — float-like (Hz); backed by metadata key
  `SpikeSamplingFrequency`
- `exp.metadata` — dict (passed through verbatim into
  `SortingData.metadata["experiment_metadata"]`)
- `exp.stim_label` — array-like with `.data` of integer (1-based)
  stimulus labels; `len(exp.stim_label) == n_trials`
- `exp.waveforms` — `xarray.DataArray` with dims
  `(electrodes, trials, spikes_idx, snippet_time)`
- `exp.spike_times` — `xarray.DataArray` with dims
  `(electrodes, trials, spikes_idx)`
- Both old (DLTG) and new (headerless) on-disk formats resolved
  transparently inside `load_from_dir`

### File-format invariants

- **NaN padding.** `waveforms` and `spike_times` use NaN for missing /
  short spike records. The bridge filters with
  `wv.notnull().any(dim="snippet_time") & st.notnull()`. If upstream
  ever changes the sentinel (e.g. `-1`, masked array, separate mask
  variable), this filter becomes a no-op and padded "spikes" leak into
  the sorting pipeline.
- **Trial-major spike order.** After
  `wv.stack(sidx_rec=("trials", "spikes_idx"))`, iteration is
  trial-major within each electrode. Any downstream consumer that
  reconstructs per-trial spike trains from `cluster_labels` depends on
  this order being preserved.

### Pending upstream additions

- **`.ssort` writer.** `export_ssort` was removed from this bridge in
  favour of an upstream `visioniceio.save_ssort` / `write_ssort`. Once
  it lands:
  1. Re-export it from [`vision_ice_analysis/__init__.py`](vision_ice_analysis/__init__.py).
  2. Add to `__all__` and to `test_bridge_callables` in
     [`tests/test_imports.py`](tests/test_imports.py).
  3. Replace the "lives in `visioniceio`" notes in
     [`README.md`](README.md) and
     [`docs/workflows.rst`](docs/workflows.rst) with a usage example.

---

## Distribution names

Mismatches between import name and PyPI name are easy to break in
`pyproject.toml`:

| import (Python)        | distribution (`pip install ...`) |
| ---------------------- | -------------------------------- |
| `neural_cca`           | `neural-cca`                     |
| `visioniceio`          | `visioniceio`                    |
| `vision_ice_analysis`  | `vision-ice-analysis`            |

`__init__.py` reads its own version with
`version("vision-ice-analysis")`; the distribution names are also what
`.github/workflows/{tests,docs}.yml` install from git
(`lint.yml` only installs ruff).

---

## How to run the cross-check

After bumping either upstream — neither package is on PyPI yet, so
mirror the git-install dance from `README.md` and the CI workflows:

```bash
pip install --force-reinstall \
  "visioniceio @ git+https://github.com/VisionICeNatal/VisionICeIO.git@main" \
  "neural-cca @ git+https://github.com/goecidbn/neural_cca.git@main"
pip install -e ".[test]"
pytest
```

(Once both are on PyPI this collapses to
``pip install -U neural-cca visioniceio && pip install -e ".[test]" && pytest``.)

That covers every **✓** above. For the unmarked items, the cheapest
verification is to load one real experiment end-to-end:

```python
from vision_ice_analysis import load_from_visioniceio, run_sorting_pipeline
data = load_from_visioniceio("<some experiment dir>", "<name>", electrode=0)
result = run_sorting_pipeline(data, plot=False)
assert len(result.cluster_labels) == data.n_spikes
```

If that runs clean, every runtime-only contract above held for at least
one input.
