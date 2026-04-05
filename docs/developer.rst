Developer Guide
===============

Setting up a Development Environment
-------------------------------------

VisionICeAnalysis depends on both ``visioniceio`` and ``mini-analysis-cidbn``.
For development, install all three packages in editable mode::

    # Clone all three repos
    git clone https://github.com/ice-vision-lab/VisionICeIO.git
    git clone https://github.com/ice-vision-lab/mini-analysis-cidbn.git
    git clone https://github.com/ice-vision-lab/VisionICeAnalysis.git

    # Create a shared venv
    python -m venv .venv
    source .venv/bin/activate

    # Install dependencies in editable mode
    pip install -e ./VisionICeIO
    pip install -e "./mini-analysis-cidbn[all]"
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
Unit tests should use synthetic data generated via ``mini-analysis-cidbn``
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
``visioniceio`` and ``mini-analysis-cidbn`` docs, so cross-references
resolve automatically when those docs are published.

Adding a New Pipeline
---------------------

Pipeline functions live in ``vision_ice_analysis/pipelines.py``.
Follow this pattern:

1. Import from ``visioniceio`` for data loading and from
   ``mini_analysis_cidbn`` for analysis functions.
2. Wrap the pipeline in a single function with clear input/output types.
3. Use lazy imports (``try/except ImportError``) for any optional dependencies.
4. Add a corresponding example in ``examples/``.
5. Document the function with NumPy-style docstrings.

Release Checklist
-----------------

1. Ensure compatible versions of ``visioniceio`` and ``mini-analysis-cidbn``
   are released first.
2. Update the version in ``vision_ice_analysis/__init__.py``.
3. Update dependency version pins in ``pyproject.toml`` if needed.
4. Run ``pytest``.
5. Build: ``python -m build && twine check dist/*``.
6. Tag: ``git tag v0.x.y && git push --tags``.
7. Upload: ``twine upload dist/*``.
