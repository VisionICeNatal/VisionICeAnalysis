# VisionICeAnalysis

End-to-end spike sorting workflows for ICe Vision Lab recordings.
Bridges [VisionICeIO](https://github.com/ice-vision-lab/VisionICeIO)
(data loading) and [mini-analysis-cidbn](https://github.com/ice-vision-lab/mini-analysis-cidbn)
(processing) into convenient pipelines.

## Installation

```bash
pip install vision-ice-analysis
```

This automatically installs `visioniceio` and `mini-analysis-cidbn`.

## Quick Start

```python
from vision_ice_analysis import load_from_visioniceio, batch_sort_experiment

# Load a single electrode
data = load_from_visioniceio(
    data_dir="/path/to/experiment",
    name="c5607a07",
    electrode=0,
)

# Run sorting pipeline on it
from mini_analysis_cidbn import run_sorting_pipeline
result = run_sorting_pipeline(data)

# Or batch-sort all electrodes at once
summary = batch_sort_experiment(
    data_source="/path/to/experiment",
    name="c5607a07",
)
```

## Related Packages

- [VisionICeIO](https://github.com/ice-vision-lab/VisionICeIO) — Pure I/O for LabView data
- [mini-analysis-cidbn](https://github.com/ice-vision-lab/mini-analysis-cidbn) — Core analysis functions

## License

AGPL-3.0-only
