Workflows
=========

VisionICeAnalysis provides end-to-end pipelines that combine VisionICeIO
(data loading) with neural_cca (spike sorting, statistics) into
convenient experiment-level workflows.

Loading data
------------

``load_from_visioniceio`` creates a :class:`~neural_cca.SortingData`
object from a VisionICeIO experiment for a single electrode::

    from vision_ice_analysis import load_from_visioniceio

    sorting_data = load_from_visioniceio(
        data_dir="/path/to/data",
        name="c5607a07",
        electrode=0,
    )

The function supports both old-format (DLTG) and new-format (headerless)
experiments transparently — ``Experiment`` resolves the file format
automatically.

Sorting and exporting per electrode
-----------------------------------

To produce per-spike cluster labels (needed for ``.ssort`` export), run
the sorting pipeline once per electrode::

    from vision_ice_analysis import (
        load_from_visioniceio,
        run_sorting_pipeline,
        export_ssort,
    )

    results = {}
    for elec in range(n_electrodes):
        data = load_from_visioniceio("/path/to/data", "c5607a07", electrode=elec)
        results[elec] = run_sorting_pipeline(data, plot=False)

    path = export_ssort("/path/to/data", "c5607a07", results)
    print(f"Written to {path}")

The ``.ssort`` export reconstructs the trial-major, channel-minor record
order expected by the LabView format. For each record it maps the
per-electrode cluster labels back to the per-trial-channel spike train
using the raw ``.spike`` (or ``.spi``) file. See the VisionICeIO
`data format documentation <https://VisionICeNatal.github.io/VisionICeIO/data_format.html>`_
for the binary layout.

Batch summary (zarr)
--------------------

For a zarr-backed summary across all electrodes (firing rates and
per-cluster STA / tuning metrics, *without* per-spike cluster_labels),
use ``batch_sort_experiment``::

    from vision_ice_analysis import batch_sort_experiment

    summary = batch_sort_experiment("/path/to/data", "c5607a07")
    print(summary["result_path"])

This loads the experiment once, iterates over electrodes, runs sorting
+ orientation selectivity + spike train statistics, and writes a
consolidated ``_sorted.zarr`` store. The returned dict contains
``result_path``, ``n_electrodes_processed``, ``n_clusters_total``, and
a per-electrode ``summary`` of quality metrics.

.. note::
    ``batch_sort_experiment``'s output is a *summary* — it does not
    expose per-spike cluster_labels and cannot be chained directly into
    ``export_ssort``. Use the per-electrode ``run_sorting_pipeline``
    loop above when ``.ssort`` output is needed.
