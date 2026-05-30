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
- ✓ `from neural_cca import minimal_spike_train_analysis` *(eager
  import in `pipelines.py`; any import failure breaks
  `import vision_ice_analysis`, so every test covers it; exercised
  functionally by `tests/test_batch.py`)*

### `SortingData` constructor

Used in [`pipelines.load_from_visioniceio`](vision_ice_analysis/pipelines.py).
The bridge passes the full keyword set below; all of them are exercised
by `test_sorting_data_signature` (**✓**), so an upstream rename or
required-arg change breaks tests immediately.

| kwarg            | type                                          |
| ---------------- | --------------------------------------------- |
| `waveforms`      | `np.ndarray (n_spikes, snippet_len)` float64  |
| `spike_times`    | `np.ndarray (n_spikes,)` float64 (**seconds**, see *Spike-time units* below) |
| `trials`         | `np.ndarray (n_spikes,)` int64 (origin TBD, see *Trial-index origin* below) |
| `angles`         | `np.ndarray (n_trials,)` float64 (degrees, 0-360)      |
| `waveform_fs`    | float (Hz)                                    |
| `n_trials`       | int                                           |
| `stim_window`    | `(onset, end)` tuple of float seconds         |
| `stim_frequency` | float \| None (Hz)                            |
| `metadata`       | dict (bridge populates a fixed schema, see *Bridge-side contracts* below) |

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

### `steps2degree` / `tlabel2angle`

- Signature: `steps2degree(n: int) -> dict[int, float]`
- `steps2degree(12)` must equal `{i: (i - 1) * 30.0 for i in range(1, 13)}`
  (1-based keys, 30° spacing, starts at 0°). This is the default
  ``tlabel2angle`` argument in
  [`pipelines.load_from_visioniceio`](vision_ice_analysis/pipelines.py).
  Any change to indexing (0-based vs 1-based), starting angle, or
  step size silently re-maps every Natal-convention recording.
- ``steps2degree`` is re-exported by the bridge
  ([`vision_ice_analysis/__init__.py`](vision_ice_analysis/__init__.py),
  covered by ``test_top_level_imports`` ✓) so callers can override the
  default mapping without importing ``neural_cca`` directly.
- **`tlabel2angle` deprecation watch.** The bridge accepts an explicit
  ``tlabel2angle: dict[int, float] | None`` kwarg; if upstream
  ``neural_cca`` removes or renames the ``tlabel2angle`` concept in a
  future release (e.g., switches to a single ``angles`` array or a
  callable), the bridge must adapt
  ([`pipelines.load_from_visioniceio`](vision_ice_analysis/pipelines.py)
  builds ``angles`` from the dict and passes the result through; the
  dict itself does not currently round-trip into ``SortingData``).
  Confirm on every upstream bump.

### `run_sorting_pipeline`

- Signature: `(data: SortingData, plot: bool = ...) -> SortingResult`
- Returns a `SortingResult` whose `cluster_labels` length equals
  `data.n_spikes`.

### `stim_window` interval semantics

`run_sorting_pipeline` (and any helper it calls) gates spikes into the
stimulated portion of each trial via `data.stim_window=(onset, end)`.
The bridge documents the filter as `(onset, end]` (half-open including
``end``) but this is the **inverse** of the more common
``[onset, end)`` convention (matches Python slicing, NWB
``TimeIntervals``, and ``np.searchsorted(side="left")``). Confirm the
actual upstream behaviour:

- A spike at exactly ``t == onset``: included or dropped?
- A spike at exactly ``t == end``: included or dropped?

A silent mismatch shifts PSTHs and tuning curves by integer-spike
amounts per condition — small but systematic. Once upstream pins the
convention, update the bridge docstring at
[`pipelines.load_from_visioniceio`](vision_ice_analysis/pipelines.py)
to match.

### OSI / DSI formula

`run_sorting_pipeline` returns per-cluster tuning metrics in
`SortingResult.os_metrics`, which the bridge's `batch_sort_experiment`
aggregates into its `summary` dict. Confirm:

- Which formula is used for OSI / DSI. The legacy peak-orthogonal
  formula ``(R_pref − R_orth) / (R_pref + R_orth)`` produces
  spuriously high values for weakly tuned cells (Mazurek et al. 2014,
  *Front. Neural Circuits*); the modern recommendation is
  **1 − Circular Variance** (``|Σ R(θ)·exp(2iθ)| / Σ R(θ)``).
- Whether the formula name and any related kwargs are stable and
  documented upstream — without that, the bridge cannot report
  "OSI/DSI per Mazurek 2014" in publication-ready text.

### Seed forwarding for reproducible sorting

The bridge generates a ~128-bit RNG seed in
[`pipelines.load_from_visioniceio`](vision_ice_analysis/pipelines.py)
and records it into ``SortingData.metadata['provenance']['seed']``.
For end-to-end reproducibility, upstream must accept that seed:

- Confirm the kwarg name used by ``run_sorting_pipeline`` (the bridge
  forwards its friendly ``seed=`` as ``rng=`` from both
  ``load_from_visioniceio`` callers and the in-bridge
  [`pipelines.batch_sort_experiment`](vision_ice_analysis/pipelines.py)
  loop; if upstream renames ``rng`` to ``random_state``, adjust the
  bridge).
- **Known gap:** a ~128-bit ``SeedSequence().entropy`` seed is
  rejected by scikit-learn (``random_state`` must fit in uint32) once
  it reaches ``KMeans`` / ``PCA`` through upstream ``_as_seed``. Until
  that is clamped, the *recorded* default seed cannot be replayed
  verbatim — tracked separately from this batch relocation.
- Confirm the seed is honoured by every stochastic step (k-means
  initialisation, silhouette sampling, train/test splits, any
  bootstrap CI).
- Confirm the seed is propagated into upstream's own result/summary
  dicts so the value can be cited in a paper without grepping caller
  code.

Downstream RNG construction should follow numpy's recommended
pattern, ``np.random.Generator(np.random.PCG64DXSM(np.random.SeedSequence(seed)))``,
which mixes entropy properly from small-integer seeds and avoids
PCG64's parallel-stream correlation (numpy/numpy#16313).

### `batch_sort_experiment` (bridge-owned, not an upstream symbol)

`batch_sort_experiment` now lives entirely in the bridge
([`pipelines.py`](vision_ice_analysis/pipelines.py)). It composes
`Experiment` / zarr loading with `run_sorting_pipeline` +
`minimal_spike_train_analysis` per electrode and writes the
consolidated zarr summary, reusing the same coupled-mask electrode
extraction (`_extract_electrode_arrays`) as `load_from_visioniceio`.
Its return-dict schema (`result_path`, `n_electrodes_processed`,
`n_clusters_total`, `summary`) is a **bridge-side** contract, covered
by `tests/test_batch.py`.

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
  short spike records — this is structural for rectangular xarray
  storage (the `spikes_idx` axis is the max spike count across all
  trials for one electrode; shorter trials must be padded). The
  bridge filters with
  `wv.notnull().any(dim="snippet_time") & st.notnull()`.
  Two open questions for upstream:
  1. Does `visioniceio` ever NaN-pad *partial* snippets (e.g., a
     spike truncated at the recording boundary), or is every snippet
     either fully present or fully NaN? If partial snippets exist,
     the bridge filter's `.any(dim="snippet_time")` lets them
     through; switching to `.all(dim="snippet_time")` would drop
     them.
  2. If upstream ever switches sentinel (e.g. `-1`, masked array,
     separate mask variable), this filter silently becomes a no-op
     and padded "spikes" leak into clustering. A defensive
     post-filter ``assert not np.isnan(...).any()`` would catch the
     drift on the first run.
- **Spike-time units.** ``exp.spike_times.values`` is consumed by the
  bridge and passed unchanged into ``SortingData.spike_times``;
  downstream ``neural_cca`` compares against ``stim_window`` which is
  documented in **seconds**. Confirm with each upstream release that
  the values are in seconds (relative to trial start, matching
  ``stim_window``'s frame of reference). The most common alternative
  is sample-frames (the SpikeInterface default); that convention
  would cause a silent ~``waveform_fs``-fold mismatch against
  ``stim_window`` and the gate would let every spike through. Once
  upstream pins the convention, the bridge will add a defensive
  sanity assertion (``assert spike_times.max() <= stim_window[1] * c``
  for some plausibility factor ``c``).
- **Trial-index origin.** The bridge extracts per-spike trial indices
  from ``wv.trials.values`` after
  ``wv.stack(sidx_rec=("trials", "spikes_idx"))`` (see
  [pipelines.py](vision_ice_analysis/pipelines.py) — search
  ``trials = wv.trials.values``). ``exp.stim_label`` is documented as
  1-based (above); confirm whether the xarray ``trials`` coordinate is
  0- or 1-based. Any downstream consumer indexing back into
  ``exp.stim_label`` from ``SortingData.trials`` relies on the two
  using the **same** convention.
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

## Bridge-side contracts

The bridge produces output that downstream tools and human readers
depend on. Renames or removals here break callers as surely as an
upstream rename breaks the bridge.

### `SortingData.metadata` schema from `load_from_visioniceio`

The bridge populates a fixed-shape metadata dict. Keys:

| key                   | source                              | notes                                                                 |
| --------------------- | ----------------------------------- | --------------------------------------------------------------------- |
| `electrode`           | function arg                        | int, selected electrode index                                         |
| `name`                | function arg                        | str, experiment file prefix                                           |
| `data_dir`            | function arg                        | str, absolute path                                                    |
| `experiment_metadata` | `exp.metadata` (upstream)           | dict, verbatim pass-through                                           |
| `provenance`          | bridge-computed                     | dict (schema below)                                                   |
| *caller fields*       | `extra_metadata=` kwarg             | merged in; bridge keys take precedence on collision                   |

`provenance` sub-schema (see
[`pipelines._provenance`](vision_ice_analysis/pipelines.py)):

- `loaded_at` — ISO-8601 UTC timestamp.
- `seed` — RNG master seed (typically ~128-bit OS entropy from
  ``SeedSequence()``, or a caller-supplied int). Pass back to
  ``run_sorting_pipeline`` / ``batch_sort_experiment`` for
  reproducible cluster labels.
- `bit_generator` — string naming the BitGenerator class the seed is
  pinned to. Always ``"PCG64DXSM"`` for now (see *RNG policy* below).
  Logged separately because ``Generator`` does not guarantee
  cross-version algorithm stability — a paper citing "seed=X" without
  the BitGenerator name is not fully reproducible.
- `software_versions` — dict of `vision-ice-analysis`, `neural-cca`,
  `visioniceio`, `numpy`, `python`. Missing packages (e.g. running
  uninstalled from a source checkout) report `None`.

`tests/test_imports.py::test_provenance_helper_shape` covers the
documented keys; a rename surfaces in CI.

### Trial structure: stimulus, baseline, and post-stim epochs

The bridge captures ``stim_window=(onset, end)`` as a tuple of seconds.
By convention:

- **Stimulus epoch**: ``stim_window`` itself. Open/closed semantics
  determined by upstream — see *stim_window interval semantics*
  above.
- **Baseline epoch**: the **implicit** interval ``[0, onset)``. The
  bridge does not currently expose this as a separate field; any
  baseline-corrected metric (firing-rate Δ, signal-to-baseline ratio,
  response-modulation index) must reconstruct it from
  ``stim_window[0]``.
- **Post-stimulus epoch**: none. ``end`` is documented as the
  trial-length boundary, so no spikes are recorded past it.

If a future analysis needs an explicit ``baseline_window`` (e.g. to
exclude a stimulus-onset transient from baseline), add it as a
separate kwarg on ``load_from_visioniceio`` and pass through
``extra_metadata`` rather than overloading ``stim_window``.

### Metadata round-trip through `run_sorting_pipeline`

Downstream tools read `provenance` from the result of sorting to
record a reproducibility audit trail. If `run_sorting_pipeline` ever
strips or rewrites `SortingData.metadata` without preserving the
`provenance` sub-dict, the audit trail breaks silently. Verify after
every upstream bump.

### Recommended FAIR / NWB extras

`extra_metadata=` is the channel for site-specific fields commonly
required by referees and data-sharing repositories
([INCF SBP portfolio](https://www.incf.org/resources/sbps),
[BIDS-iEEG](https://www.nature.com/articles/s41597-019-0105-7),
[NWB ecosystem](https://elifesciences.org/articles/78362)):

- `subject_id` (animal / participant identifier)
- `session_start_time` (ISO-8601, recording wall-clock)
- `brain_area` / `probe_location` (anatomical, ideally with
  coordinate-frame label)
- `probe` (model, channel count, geometry file)
- `reference_scheme` (referencing convention prior to sort)
- `stimulus_protocol_description` (free text + citation)
- `input_sha256` (SHA-256 of the experiment directory contents for
  byte-level provenance integrity)

The bridge does not compute these — the recording rig and the
experimenter do — but stores them verbatim.

---

## RNG policy

This is a bridge-side contract that **upstream sorters must respect**
for reproducibility claims to hold. Filed here so an upstream bump
that breaks any of these points fails review.

### Construction

Use ``PCG64DXSM`` explicitly. ``np.random.default_rng()`` is **not
acceptable** — it returns a ``PCG64``-backed generator with the known
parallel-stream self-correlation bug
([numpy/numpy#16313](https://github.com/numpy/numpy/issues/16313)).
Reconstruct the bridge's RNG state as:

```python
from numpy.random import Generator, PCG64DXSM, SeedSequence

seed = sorting_data.metadata["provenance"]["seed"]
rng  = Generator(PCG64DXSM(SeedSequence(seed)))
```

The ``SeedSequence`` wrapper is mandatory even for a known-large
master seed — it mixes entropy uniformly and is the only stream
support recognised by numpy's spawn API.

### One generator per addressable unit of reproducibility

A "unit" is anything that might be re-run or parallelised in
isolation: a trial, a cross-validation fold, a parallel worker, a
bootstrap resample. Each unit gets its own ``Generator``, derived
from a single master ``SeedSequence`` via ``spawn``:

```python
parent_ss   = SeedSequence(master_seed)
child_seeds = parent_ss.spawn(n_tasks)
rngs        = [Generator(PCG64DXSM(s)) for s in child_seeds]
```

One seed to log, order-independent, parallel-safe, statistically
independent streams. Pass the generator (or for nested spawning, the
``SeedSequence`` itself) as an explicit argument:
``def run_trial(..., rng: np.random.Generator)``. **Never**:

- call ``np.random.*`` module-level functions,
- share one ``Generator`` across trials/workers,
- independently seed each trial from OS entropy (loses the audit trail),
- use ``RandomState`` (legacy; no ``SeedSequence`` scrambling).

### Nested spawning

If a task has sub-streams that must be independently reproducible,
pass the child ``SeedSequence`` (not a ``Generator``) and spawn again
inside. A ``SeedSequence`` is not retained by the ``BitGenerator``
constructor, so once consumed via ``PCG64DXSM(ss)`` it cannot be
re-spawned from.

```python
def run_trial(child_ss: SeedSequence):
    s_init, s_dyn, s_meas = child_ss.spawn(3)
    rng_dyn = Generator(PCG64DXSM(s_dyn))
    ...
```

### `spawn()` advances the parent counter

```text
parent_ss.spawn(1000) + parent_ss.spawn(100)  ≠  fresh_parent_ss.spawn(1100)
```

To extend an existing ensemble, reconstruct the parent from the
master seed and re-spawn the larger batch in one call.

### Seeds and logging

- **Generating a seed.** ``SeedSequence()`` (OS entropy, ~128-bit) or
  ``secrets.randbits(128)``. Never small integers, ``42``, indices,
  PIDs, or timestamps — these defeat the entropy mixing and re-collide
  across unrelated experiments.
- **Logging.** Record the master seed **and** the ``BitGenerator``
  class name. The bridge already does this via
  ``SortingData.metadata['provenance']['seed']`` and
  ``['bit_generator']``. ``Generator`` does not guarantee
  cross-numpy-version algorithm stability, so the BitGenerator name
  + numpy version (also logged) together pin the algorithm.

### Cross-check items

Upstream ``neural_cca`` must:

- Accept the seed kwarg (name TBD — see *Seed forwarding* above) and
  honour it for **every** stochastic step (k-means initialisation,
  silhouette sampling, train/test splits, bootstrap CIs).
- Construct its own generators via
  ``Generator(PCG64DXSM(SeedSequence(seed)))``, not
  ``default_rng()`` and not ``RandomState``.
- Spawn per-electrode / per-cluster sub-streams via
  ``parent_ss.spawn(...)`` rather than re-seeding from a derived int —
  spawn-derived streams are statistically independent, derived-int
  streams are not.
- Propagate the master seed and BitGenerator name into the result
  dicts (so per-cluster fields can be re-derived without re-running
  ``load_from_visioniceio``).

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
