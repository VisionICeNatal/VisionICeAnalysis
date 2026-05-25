# VisionICeAnalysis

End-to-end spike sorting workflows for ICe Vision Lab recordings.
Bridges [VisionICeIO](https://github.com/VisionICeNatal/VisionICeIO)
(data loading) and [neural_cca](https://github.com/goecidbn/neural_cca)
(processing) into convenient pipelines.

## Installation

Until the packages are published to PyPI, install all three from git:

```bash
pip install \
  "visioniceio @ git+https://github.com/VisionICeNatal/VisionICeIO.git@main" \
  "neural-cca @ git+https://github.com/goecidbn/neural_cca.git@main" \
  "vision-ice-analysis @ git+https://github.com/VisionICeNatal/VisionICeAnalysis.git@main"
```

Once published, this collapses to:

```bash
pip install vision-ice-analysis  # will pull visioniceio and neural-cca automatically
```

## Quick Start

```python
from vision_ice_analysis import load_from_visioniceio, run_sorting_pipeline

# Load a single electrode
data = load_from_visioniceio(
    data_dir="/path/to/experiment",
    name="c5607a07",
    electrode=0,
)

# Run sorting pipeline on it
result = run_sorting_pipeline(data)
```

For a zarr-backed summary across all electrodes, use `batch_sort_experiment`:

```python
from vision_ice_analysis import batch_sort_experiment

summary = batch_sort_experiment(
    data_source="/path/to/experiment",
    name="c5607a07",
)
```

`batch_sort_experiment` writes a consolidated `_sorted.zarr` store and
returns a dict with `result_path`, `n_electrodes_processed`,
`n_clusters_total`, and per-electrode quality `summary`. It does **not**
include per-spike `cluster_labels`; use the per-electrode
`run_sorting_pipeline` loop above when you need those.

`.ssort` export is being moved into `visioniceio` itself (as
`save_ssort` / `write_ssort`). Until that upstream writer lands, no
`.ssort` round-trip is available through this bridge; see
[`CROSS_CHECKS.md`](CROSS_CHECKS.md) for the re-wire checklist.

## Related Packages

- [VisionICeIO](https://github.com/VisionICeNatal/VisionICeIO) — Pure I/O for LabView data
- [neural-cca](https://github.com/goecidbn/neural_cca) — Core analysis functions
  (spike sorting, STA, tuning)

## License

AGPL-3.0-only
