# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-05-30

### Changed
- Upstream `neural-cca` pin widened from `>=0.1,<0.2` to `>=0.2,<0.3`
  to track `neural_cca` 0.2.0 (which removed `batch_sort_experiment`;
  its logic now lives here). This crosses a 0.x minor, so
  `CROSS_CHECKS.md` was re-verified against the new upstream. The CI
  SHA pins in `.github/workflows/{tests,docs}.yml` must move to the
  `neural_cca` v0.2.0 tag commit (see `docs/developer.rst` → pin
  policy).
- `batch_sort_experiment` is now implemented entirely in the bridge
  (`vision_ice_analysis/pipelines.py`) instead of delegating to
  `neural_cca.sorting.batch`. This removes the leaf→leaf coupling
  where `neural_cca` imported `visioniceio` directly. The bridge now
  loads the experiment (directory **or** `visioniceio` zarr) and loops
  electrodes itself, reusing the same coupled-mask electrode
  extraction (`_extract_electrode_arrays`) as `load_from_visioniceio`
  — so the single-electrode and batch NaN-filtering contracts can no
  longer drift. `stim_window` and an angle mapping (`tlabel2angle` or
  `n_angle_steps`) are required; the summary-dict and output-zarr
  schemas are unchanged. New `tests/test_batch.py` covers the
  end-to-end path; it newly depends on
  `neural_cca.minimal_spike_train_analysis` (see `CROSS_CHECKS.md`).

### Added
- `SortingData.metadata['provenance']` extended with a richer audit
  trail beyond seed + library versions:
  - ``software_versions`` now also reports ``scipy``, ``scikit-learn``,
    ``xarray``, ``zarr``, and ``numcodecs`` — every library whose
    release notes plausibly perturb numerical output via random,
    linalg, or KMeans/PCA determinism contracts.
  - ``input_sha256`` — SHA-256 of the input ``data_source``. For a
    directory: hash of sorted ``(relpath, file_sha256)`` pairs over
    every file in the tree, with files >100 MB folded in as
    ``(path, size, mtime_ns)`` only so multi-GB zarr chunks don't
    force a re-read on every load. For a single file: streamed hash.
    ``None`` when the source is an in-memory ``xarray.Dataset``.
  - ``git_commit`` — SHA of the installed bridge code, detected by
    walking up from ``__file__`` to find a ``.git`` directory and
    resolving HEAD (loose ref → packed-refs fallback → detached SHA).
    ``None`` when installed from a wheel rather than an editable
    git checkout.
  - ``platform`` — ``{system, release, machine, python_compiler}``
    from ``platform.*``, for cross-OS reproducibility audits.
  - ``threading`` — ``OMP_NUM_THREADS`` / ``MKL_NUM_THREADS`` /
    ``OPENBLAS_NUM_THREADS`` from the environment (or ``"unset"``).
    These silently perturb numerical output on some LAPACK paths;
    logging them lets a downstream consumer reproduce results
    bit-for-bit.

  Implemented as the new ``_compute_input_sha256`` and
  ``_detect_installed_git_sha`` helpers in ``pipelines.py``; the
  ``_provenance`` helper now takes an optional ``data_source``
  argument. ``tests/test_imports.py::test_provenance_helper_shape``
  asserts every new key is present and well-typed.
- `seed` kwarg on `load_from_visioniceio` and `batch_sort_experiment`
  for reproducible stochastic clustering. When ``None``, a fresh
  ~128-bit master seed is drawn from OS entropy via
  ``numpy.random.SeedSequence()`` — never ``default_rng()`` (PCG64
  parallel-stream bug, numpy/numpy#16313), never small integers /
  PIDs / timestamps (defeat entropy mixing). The seed is recorded
  into ``SortingData.metadata['provenance']['seed']`` so it survives
  downstream and can be cited in publications. The bridge contract
  pins the BitGenerator to ``PCG64DXSM``; downstream RNG must be
  constructed as
  ``Generator(PCG64DXSM(SeedSequence(seed)))``. See
  ``CROSS_CHECKS.md`` → *RNG policy* for the full contract, including
  spawning recipe for per-electrode / per-fold sub-streams.
- `extra_metadata` kwarg on `load_from_visioniceio` letting callers
  merge custom FAIR / NWB-style metadata (subject ID, brain area,
  probe geometry, input file checksums, …) into
  ``SortingData.metadata``. Bridge-managed keys take precedence on
  collision so callers cannot accidentally overwrite the contract.
- `SortingData.metadata['provenance']` dict populated by
  ``_provenance`` in ``pipelines.py``: ``loaded_at`` (ISO-8601 UTC),
  ``seed`` (master), ``bit_generator`` (``"PCG64DXSM"``), and
  ``software_versions`` for
  ``vision-ice-analysis`` / ``neural-cca`` / ``visioniceio`` /
  ``numpy`` / ``python``. The ``seed`` + ``bit_generator`` pair is
  the canonical reproducibility key — ``Generator`` does not
  guarantee cross-numpy-version algorithm stability, so both must
  be logged. See ``CROSS_CHECKS.md`` → *Bridge-side contracts* for
  the schema.
- `steps2degree` re-exported from
  ``vision_ice_analysis/__init__.py`` (and added to ``__all__``).
  Callers who want a non-default ``tlabel2angle`` mapping can now
  ``from vision_ice_analysis import steps2degree`` without
  reaching into ``neural_cca`` directly — restoring the
  "single import surface" the bridge advertises.
- `tests/test_imports.py::test_provenance_helper_shape` — covers the
  documented provenance keys (``loaded_at``, ``seed``,
  ``bit_generator``, ``software_versions``) so a rename surfaces in
  CI.
- `warnings.warn` in ``load_from_visioniceio``:
  - When ``waveform_fs < 10 kHz`` (likely metadata misread; typical
    extracellular spike-sorting rigs run 20-30 kHz).
  - When ``trials per direction < 5`` (below the Mazurek et al. 2014
    *Front. Neural Circuits* recommendation for stable OSI/DSI
    estimates).

### Changed
- `pyproject.toml`: ``xarray>=2022.6`` and ``zarr>=2.16`` are now
  declared explicitly as bridge dependencies (bounds chosen to match
  ``visioniceio``'s own declaration). Both were used directly in
  ``pipelines.py`` (``.sel``/``.stack``/``.notnull``/``.isel`` on
  DataArrays; zarr stores produced by ``batch_sort_experiment``) but
  were pulled in only transitively via ``visioniceio`` — one
  upstream-policy change away from a broken install. Also added a
  ``[project.urls] Changelog`` entry pointing at this file on GitHub
  so PyPI / pip-show surface it.
- `.github/workflows/{tests,docs}.yml` now pin `visioniceio` and
  `neural-cca` to specific commit SHAs instead of `@main`. Upstream
  churn on unrelated PRs can no longer flap CI; bumping a SHA is now
  a deliberate act tied to re-running `CROSS_CHECKS.md` against the
  new upstream (see `docs/developer.rst` → *Upstream version-pin
  policy*). The pinned SHAs always correspond to a tagged release of
  each upstream that satisfies the `>=0.1,<0.2` `pyproject.toml`
  bound; the workflow file is the authoritative source for the
  *current* pinned SHA / version (this changelog only records the
  policy change, not each individual bump). The user-facing install
  recipes in `README.md` and `CROSS_CHECKS.md` deliberately stay on
  `@main` — those exist to track latest, not for CI determinism.
- Bridge `batch_sort_experiment` now translates its bridge-side
  ``seed=`` kwarg to the upstream's ``rng=`` kwarg
  (``neural_cca.sorting.batch.batch_sort_experiment`` accepts
  ``int | Generator | None``) and forwards any other ``**kwargs``
  verbatim. Previous behaviour passed ``seed=`` through directly,
  which raised ``TypeError`` because upstream has no ``seed=`` arg.
  Bridge-side translation keeps the friendlier ``seed=`` name aligned
  with the rest of the bridge surface and avoids leaking upstream
  kwarg renames into callers.
- ``vision_ice_analysis/__init__.py`` and ``docs/conf.py``: when the
  package isn't pip-installed (source-checkout import / docs build),
  ``__version__`` and the rendered docs version are now read from
  ``pyproject.toml`` directly via a small regex parse, rather than a
  hardcoded fallback. ``pyproject.toml`` is now the single source of
  truth for the version; the Release Checklist no longer needs a
  fallback-bump step.
- Documentation site display title renamed from ``"VisionICeAnalysis"``
  to ``"ICe Natal Standard Analysis"`` (Sphinx ``project`` in
  ``docs/conf.py``, ``index.rst`` H1, ``conf.py`` module docstring).
  The Python package identity stays unchanged
  (``vision_ice_analysis`` import, ``vision-ice-analysis`` on PyPI,
  README/prose mentions of the code package).

### Documentation
- ``CROSS_CHECKS.md``: added a batch of cross-check items, two new
  sections (**Bridge-side contracts**, **RNG policy**), and a
  ``steps2degree`` re-export note.
  - **visioniceio**: ``exp.spike_times`` unit (seconds vs sample-frames);
    trial-index origin (0- vs 1-based); narrowed the NaN-padding entry
    to clarify rectangular-storage necessity and call out partial-snippet
    handling.
  - **neural_cca**: ``stim_window`` open/closed interval semantics
    (bridge currently documents ``(onset, end]`` — inverse of common
    ``[onset, end)`` convention); OSI/DSI formula choice (peak-orthogonal
    vs Mazurek 2014's 1−Circular Variance); RNG-seed kwarg name and
    propagation; ``tlabel2angle`` deprecation watch (upstream may
    remove or rename the concept; bridge has to adapt).
  - **Bridge-side contracts**: documented ``SortingData.metadata``
    schema (electrode/name/data_dir/experiment_metadata/provenance plus
    caller extras); the ``provenance`` sub-schema now includes
    ``bit_generator``; new *Trial structure* sub-section documents
    the implicit ``[0, onset)`` baseline epoch and absence of a
    post-stim epoch; round-trip expectation through
    ``run_sorting_pipeline``; recommended FAIR / NWB extras
    (subject_id, brain_area, probe, reference_scheme, input_sha256, …).
  - **RNG policy** (new section): pins ``PCG64DXSM`` as the bridge's
    BitGenerator contract; mandates
    ``Generator(PCG64DXSM(SeedSequence(seed)))`` construction (not
    ``default_rng()``, not ``RandomState``); documents the
    spawn-from-parent-SeedSequence pattern for per-trial /
    per-electrode / per-fold sub-streams; lists cross-check items
    upstream sorters must respect (seed honoured by every stochastic
    step, spawn vs derived ints, seed propagation into result dicts).
  - ``stim_frequency`` row in the ``SortingData`` kwarg table now
    names Hz; ``spike_times`` / ``trials`` / ``angles`` rows annotated
    with their expected units and pending unknowns.
- ``vision_ice_analysis/pipelines.py``: docstring for
  ``load_from_visioniceio`` now names ``stim_window`` units (seconds),
  flags the open/closed-interval ambiguity, mentions the Mazurek 2014
  trial-count guideline, documents the new ``seed`` / ``extra_metadata``
  kwargs, and pins the recommended numpy RNG construction pattern.
  ``batch_sort_experiment`` docstring documents ``seed`` forwarding
  and the upstream kwarg-name uncertainty.

### Fixed
- CI hardening across `.github/workflows/{tests,lint,docs}.yml`:
  - Top-level ``concurrency: { group: <workflow>-<ref>,
    cancel-in-progress: true }`` so a fast follow-up push or PR
    update cancels the now-stale in-flight run instead of queueing
    behind it. Saves Actions minutes on push-heavy days.
  - ``actions/setup-python@v5`` now opts into pip caching
    (``cache: 'pip'``, ``cache-dependency-path: pyproject.toml``).
    Re-runs that don't change ``pyproject.toml`` skip the wheel
    download for sphinx + pytest + their transitive deps.
  - Fork-PR token guard at the job level
    (``if: github.event_name != 'pull_request' ||
    github.event.pull_request.head.repo.full_name ==
    github.repository``). Push events and same-repo PRs run
    normally; PRs from forks show "skipped" because they would
    otherwise expose the ``UPSTREAM_REPO_TOKEN`` PAT (read access to
    the private ``visioniceio`` repo) to attacker-controlled
    workflow code. Maintainer reviews fork PRs locally.

### Known issues (carried forward)
- `visioniceio` does not yet publish a Sphinx site; intersphinx
  mapping for it is staged in `docs/conf.py` but commented out, and
  cross-references to it render as plain literals.
- `actions/deploy-pages@v4` returns HTTP 404 because GitHub Pages is
  not enabled on the (private) repo — Pages on a private repo
  requires a paid GitHub plan and the source set to
  *GitHub Actions*. The docs *build* succeeds; only the deploy step
  fails. Acceptable until Pages is enabled or the repo goes public.
- `tests/test_batch.py` runs `batch_sort_experiment` end-to-end over a
  synthetic `visioniceio`-shaped zarr (load → coupled-mask extraction
  → `run_sorting_pipeline` → consolidated zarr), so the shared
  extraction + sort path is now covered. A dedicated single-electrode
  `load_from_visioniceio` test against a raw LabView directory is
  still absent; semantic drift on the *directory* path (upstream dim
  names, NaN-padding sentinel) goes undetected until the first
  real-data run.

### Roadmap

- Add `CITATION.cff` (co-author Schmidt UFRN, Wolf CIDBN, Schwarz;
  acknowledge PROBRAL funding) so the bridge is citable.
- Add `vision_ice_analysis.to_nwb(experiment, sorting_result,
  extra_metadata) -> NWBFile` exporter that consumes
  `Experiment + SortingResult + extra_metadata` via `pynwb`. The bridge
  is the architecturally correct home for NWB knowledge: `visioniceio`
  stays I/O-only, `neural_cca` stays analysis-only, the bridge owns
  lab/standard conventions. Depends on the acquisition-side metadata
  enrichment landing in `visioniceio` first.
- Re-export `read_ssort` / `write_ssort` from `visioniceio` and add a
  `to_ssort_from_sorting_result(data, result, path, n_fields=16)`
  helper that groups spikes by `(cluster, trial)` from
  `SortingResult.cluster_labels` and writes via `save_ssort`.
- Synthetic end-to-end integration test:
  `tests/test_integration_synthetic.py` exercises
  `load_from_visioniceio → run_sorting_pipeline` against a two-cluster,
  12-direction synthetic Dataset (catches CROSS_CHECKS contract drift
  cheaply; recommended primary).
- Upstream pin bumps when `neural_cca v0.2.0` lands: the bridge's
  `batch_sort_experiment` will become the sole owner of
  directory→Dataset loading (Top-10 #1 in the senior-director review).
- Move the four-commits-past-v0.1.0 `visioniceio` pin to a tagged
  release (cut `visioniceio v0.1.1` covering the ~28 entries in its
  `[Unreleased]` backlog, then bump the SHA pin to the tag commit).
- Author `paper.md` once the JOSS submission path for `neural_cca` is
  agreed (bridge co-paper or sub-section of the upstream paper).

## [v0.1.1] — 2026-05-25

### Removed
- **`export_ssort`** public function (and its dependent imports
  `read_spike_new`, `write_ssort`, `SortingResult` in
  `vision_ice_analysis/pipelines.py`). It had three latent correctness
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
- `tests.test_imports.test_sorting_result_uses_cluster_labels`
  (regression test specific to the removed `export_ssort`).
- `autodoc_mock_imports` in `docs/conf.py` — the docs workflow
  installs the real `numpy`, `visioniceio`, and `neural_cca`, so the
  mock list was silently suppressing genuine autodoc failures.
- `--cov-report=xml` from `.github/workflows/tests.yml` — no upload
  step (codecov action or otherwise) consumed the artifact; switched
  to `term-missing` for actionable output in the CI log.
- Redundant legacy `License ::` PyPI classifier in `pyproject.toml`
  (the PEP 639 `license = "AGPL-3.0-only"` field is canonical and
  modern packaging tools warn on the duplication).
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
- `pyproject.toml`: pinned upstream upper bounds at `<0.2` for both
  `neural-cca` and `visioniceio` to bound 0.x-era breakage. Policy
  documented in `docs/developer.rst` ("Upstream version-pin policy").
- `.github/workflows/lint.yml`: pinned `ruff==0.15.14` so a new ruff
  release with stricter rules doesn't flap CI on unrelated PRs.
- `tests/test_imports.py`::`test_sorting_data_signature` now
  constructs `SortingData` with the **full** kwarg set
  `load_from_visioniceio` passes in production (`waveform_fs`,
  `n_trials`, `metadata` added). An upstream rename or required-arg
  change to any of those nine kwargs now fails at test time.
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
- `README.md`: dropped `export_ssort` from the Quick Start; removed
  the long batch-vs-export chainability paragraph; added a one-liner
  pointing at upstream `visioniceio` for `.ssort` export. Install
  instructions rewritten to show the git-install dance currently
  needed (none of the three packages are on PyPI yet), with the
  collapsed PyPI form shown as the post-publish target.
- `docs/workflows.rst`: renamed *"Sorting and exporting per electrode"*
  → *"Per-electrode sorting"*; removed the `export_ssort` example and
  the `.ssort` reconstruction prose; stripped `:mod:\`visioniceio\``
  to plain literal since intersphinx for that package is still
  disabled.
- `vision_ice_analysis/__init__.py`: same `:mod:\`visioniceio\`` →
  literal strip in the package docstring.
- `docs/conf.py`: re-enabled intersphinx for `neural_cca` (its docs
  site is published and serves `objects.inv`); `visioniceio` mapping
  stays staged-but-commented until its site goes live. Copyright
  bumped to `2025-2026`. Added `maximum_signature_line_length = 88`
  so autodoc renders multi-parameter signatures one-per-line instead
  of as one unreadable wall (e.g. `load_from_visioniceio` and
  `batch_sort_experiment` both have enough kwargs to trigger). Bumped
  the `[docs]` extra to `sphinx>=7.1` since that option needs it.
- `docs/developer.rst`: corrected the Release Checklist (version
  lives in `pyproject.toml`, not `__init__.py`); added steps for
  rolling `CHANGELOG.md` and re-running `CROSS_CHECKS.md` after
  upstream bumps; refined the lazy-import guidance for new pipelines;
  added an "Upstream version-pin policy" section explaining the
  `<0.2` bound; added a Building-the-Documentation reminder that
  hard deps must be installed before `make html`; trimmed the
  aspirational "synthetic data via `neural-cca` helpers" line in
  favour of advice the suite actually backs up.
- [`CROSS_CHECKS.md`](CROSS_CHECKS.md): corrected the
  `SortingData.stimulus_duration` invariant
  (`stim_window[1] - stim_window[0]`, not `stim_window[1]`); the
  `SortingData` kwarg table now reflects that the expanded
  `test_sorting_data_signature` exercises all nine kwargs.
- `examples/example_full_pipeline.ipynb`: retitled to *"Quickstart
  Sanity Check"* — the cells assert imports load; the pipeline
  examples are commented templates, not executable demos.
- Consistency pass across `README.md`, `docs/workflows.rst`, and
  `CROSS_CHECKS.md`: aligned the `.ssort` "pending upstream" wording
  (it had drifted into "see upstream docs" — but neither the docs
  site nor the writer API exists yet); fixed a broken
  `Round-trip invariants` xref in `CROSS_CHECKS.md` (now points at
  `File-format invariants`); rewrote the post-upstream-bump install
  recipe to use git installs (matching `README.md` + workflows);
  tightened the `*.yml install from git` claim to name only the two
  workflows that actually do. Corrected the `maximum_signature_line_length`
  comment in `docs/conf.py` (88 is Black/Ruff, not PEP 8).

### Fixed
- **CI was failing on every push** because
  ``.github/workflows/{tests,docs}.yml`` tried to clone the **private**
  ``VisionICeNatal/VisionICeIO`` repo over anonymous
  ``git+https://`` (``fatal: could not read Username for
  'https://github.com'`` → exit 128 → cancel-on-fail aborts the whole
  matrix). Both workflows now run a
  ``git config --global url."https://x-access-token:$TOKEN@github.com/".insteadOf "https://github.com/"``
  step before any `pip install`, using a new repo secret
  ``UPSTREAM_REPO_TOKEN``. Setup is documented in
  `docs/developer.rst` → *Continuous Integration*; the secret needs
  to be created once per fork before CI turns green.
- `.gitignore` now matches `*_failed.txt` so dumps from the
  CI-failure fetch tooling stop showing up as untracked files.

### Known issues (carried forward)
- `.github/workflows/{tests,docs}.yml` install `visioniceio` and
  `neural-cca` from `@main` rather than a pinned tag/commit. A
  deliberate temporary workaround until both are on PyPI — upstream
  churn can break CI on unrelated PRs.
- `visioniceio` does not yet publish a Sphinx site; intersphinx
  mapping for it is staged in `docs/conf.py` but commented out, and
  cross-references to it render as plain literals.
- No integration test runs `load_from_visioniceio` →
  `run_sorting_pipeline` against a real or synthetic experiment.
  Smoke tests catch import-shape regressions only; semantic drift in
  upstream xarray dim names or NaN-padding sentinel goes undetected
  until the first real-data run.
