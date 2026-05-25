# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- **`export_ssort`** public function. It had three latent correctness
  bugs and is being replaced by an upstream writer in `visioniceio`
  (`save_ssort` / `write_ssort`). Once that lands, the bridge will
  re-export it; see [`CROSS_CHECKS.md`](CROSS_CHECKS.md) for the
  re-wire checklist. The bugs were:
  - Per-trial cluster-label slices were indexed by **raw** spike
    counts, while `SortingResult.cluster_labels` is produced from the
    NaN-filtered subset — silently misaligned labels whenever any
    spike was NaN-padded.
  - The per-trial `end - start != n_spikes` check compared two values
    derived from the same source and could never trigger.
  - The `.spi` fallback called `read_data(..., "int32", 1)`, which
    returns a flat array instead of the per-record list shape the
    downstream code expects.
- Module-level `try/except ImportError` wrappers around
  `from neural_cca import …` in `vision_ice_analysis/pipelines.py`.
  `neural_cca` is a hard dependency in `pyproject.toml` and is
  imported eagerly by `__init__.py`, so the wrapper was unreachable.
- `read_spike_new`, `write_ssort`, `SortingResult` imports in
  `pipelines.py` (used only by the removed `export_ssort`).
- `tests.test_imports.test_sorting_result_uses_cluster_labels`
  (regression test specific to the removed `export_ssort`).
- `autodoc_mock_imports` in `docs/conf.py` — the docs workflow installs
  the real `numpy`, `visioniceio`, and `neural_cca`, so the mock list
  was silently suppressing genuine autodoc failures.
- Hardcoded personal data path in
  `examples/example_full_pipeline.ipynb`.
- Stray `warnings_sphinx_build.txt` (empty + gitignored).

### Changed
- `load_from_visioniceio` now uses `neural_cca.steps2degree(12)` for
  the default `tlabel2angle` instead of duplicating the formula
  inline. Removes drift risk if the upstream convention ever changes.
- `load_from_visioniceio` docstring for `waveform_fs` names the actual
  accessor (`exp.sample_rate_spike`) rather than the underlying
  metadata key.
- `vision_ice_analysis/__init__.py` module docstring softened — the
  "single import surface" overstatement removed.
- Final code cell in `examples/example_full_pipeline.ipynb` now
  asserts the bridge entry points are callable, so the "loaded
  successfully" banner reflects a real check (and ruff stops flagging
  the cell-1 imports as unused).

### Added
- [`CROSS_CHECKS.md`](CROSS_CHECKS.md) — explicit inventory of every
  `neural_cca` and `visioniceio` contract the bridge depends on, with
  per-item markers for which contracts `tests/test_imports.py` covers
  and a runbook for verifying after upstream upgrades.
- This `CHANGELOG.md`.

### Documentation
- `README.md`: dropped `export_ssort` from the Quick Start; removed the
  long batch-vs-export chainability paragraph; added a one-liner
  pointing at upstream `visioniceio` for `.ssort` export.
- `docs/workflows.rst`: renamed *"Sorting and exporting per electrode"*
  → *"Per-electrode sorting"*; removed the `export_ssort` example and
  the `.ssort` reconstruction prose.
- `docs/developer.rst`: corrected the Release Checklist (version lives
  in `pyproject.toml`, not `__init__.py`); added steps for rolling
  `CHANGELOG.md` and re-running `CROSS_CHECKS.md` after upstream
  bumps; refined the lazy-import guidance for new pipelines.

### Known issues (carried forward)
- `.github/workflows/{tests,docs}.yml` install `visioniceio` and
  `neural-cca` from `@main` rather than a pinned tag/commit. A
  deliberate temporary workaround until both are on PyPI — upstream
  churn can break CI on unrelated PRs.
