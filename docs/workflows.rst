Workflows
=========

VisionICeAnalysis provides end-to-end pipelines that combine VisionICeIO
(data loading) with mini_analysis_cidbn (spike sorting, statistics) into
convenient experiment-level workflows.

Loading data
------------

``load_from_visioniceio`` creates a :class:`~mini_analysis_cidbn.io_util.SortingData`
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

Batch sorting
-------------

``batch_sort_experiment`` runs the full spike sorting pipeline across all
electrodes of an experiment::

    from vision_ice_analysis import batch_sort_experiment

    results = batch_sort_experiment("/path/to/data", "c5607a07")

This loads the experiment once, iterates over electrodes, performs
sorting + orientation selectivity analysis + spike train statistics, and
returns a dict mapping electrode indices to ``SortingResult`` objects.

Exporting .ssort
----------------

After sorting, ``export_ssort`` writes the results to a ``.ssort`` binary
file that can be read back by ``visioniceio.read_ssort``::

    from vision_ice_analysis import export_ssort

    path = export_ssort(
        data_dir="/path/to/data",
        name="c5607a07",
        sorting_results=results,
    )
    print(f"Written to {path}")

The export reconstructs the trial-major, channel-minor record order
expected by the ``.ssort`` format. For each record it maps the per-electrode
cluster labels back to the per-trial-channel spike train using the raw
``.spike`` (or ``.spi``) file. See the VisionICeIO
`data format documentation <https://ice-vision-lab.github.io/VisionICeIO/data_format.html>`_
for the binary layout.
