Developer Guide
===============

Setting up a Development Environment
-------------------------------------

VisionICeAnalysis depends on both ``visioniceio`` and ``neural-cca``.
For development, install all three packages in editable mode::

    # Clone all three repos
    git clone https://github.com/VisionICeNatal/VisionICeIO.git
    git clone https://github.com/goecidbn/neural_cca.git
    git clone https://github.com/VisionICeNatal/VisionICeAnalysis.git

    # Create a shared venv
    python -m venv .venv
    source .venv/bin/activate

    # Install dependencies in editable mode
    pip install -e ./VisionICeIO
    pip install -e "./neural_cca[all]"
    pip install -e "./VisionICeAnalysis[test,docs,dev]"

This ensures that changes to the I/O or analysis packages are immediately
reflected when running VisionICeAnalysis code.

Running the Test Suite
----------------------

Run all tests::

    cd VisionICeAnalysis
    pytest

Run with coverage::

    pytest --cov=vision_ice_analysis --cov-report=term-missing

Integration tests require real recording data in the DLTG format.
Unit tests should use synthetic data generated via ``neural-cca``
helper functions (see its developer guide).

Linting and Formatting
----------------------

The project uses `ruff <https://docs.astral.sh/ruff/>`_::

    ruff check .
    ruff check --fix .
    ruff format .
    ruff format --check .

Building the Documentation
--------------------------

Build locally::

    cd docs
    make html

The Sphinx configuration includes ``intersphinx`` mappings to both
``visioniceio`` and ``neural_cca`` docs, so cross-references resolve
automatically when those docs are published.

Adding a New Pipeline
---------------------

Pipeline functions live in ``vision_ice_analysis/pipelines.py``.
Follow this pattern:

1. Import from ``visioniceio`` for data loading and from
   ``neural_cca`` for analysis functions.
2. Wrap the pipeline in a single function with clear input/output types.
3. Both upstream packages are *hard* dependencies, so import them at
   module top-level — do **not** wrap them in ``try/except ImportError``
   (that wrapper is unreachable when the dep is required). Lazy imports
   inside a function body are only justified when the symbol lives in
   an upstream submodule that may not always be importable.
4. Add a corresponding example in ``examples/``.
5. Document the function with NumPy-style docstrings.
6. Record every new symbol the bridge starts depending on in
   ``CROSS_CHECKS.md`` (top-level repo file). That file is the
   authoritative inventory of the upstream contract surface.

Upstream Contract Checks
------------------------

The bridge has no analysis logic of its own — every public symbol is a
wrapper around ``neural_cca`` or ``visioniceio``. The expected upstream
surface is documented in `CROSS_CHECKS.md
<https://github.com/VisionICeNatal/VisionICeAnalysis/blob/main/CROSS_CHECKS.md>`_
at the repository root.

Run ``pytest`` after any upstream bump; that exercises everything
marked **✓** in ``CROSS_CHECKS.md``. The unmarked items are
runtime-only and need one real experiment loaded end-to-end to
verify.

Release Checklist
-----------------

1. Ensure compatible versions of ``visioniceio`` and ``neural-cca``
   are released first.
2. Re-verify ``CROSS_CHECKS.md`` against the upstream versions you are
   pinning against.
3. Update the version in ``pyproject.toml`` (``__init__.py`` reads it
   dynamically via ``importlib.metadata``).
4. Update dependency version pins in ``pyproject.toml`` if needed.
5. Roll ``CHANGELOG.md``: rename ``## [Unreleased]`` to
   ``## [vX.Y.Z] — YYYY-MM-DD`` and open a fresh empty
   ``## [Unreleased]`` section above it.
6. Run ``pytest``.
7. Build: ``python -m build && twine check dist/*``.
8. Tag: ``git tag v0.x.y && git push --tags``.
9. Upload: ``twine upload dist/*``.
