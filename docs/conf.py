"""Sphinx configuration for the ICe Natal Standard Analysis docs."""

import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Docs site display title — drives the navbar (upper-left), the
# browser tab <title>, and the page H1 fallback. Distinct from the
# Python package identity (``vision_ice_analysis`` / ``vision-ice-analysis``)
# which stays unchanged everywhere code references it.
project = "ICe Natal Standard Analysis"
copyright = "2025-2026, ICe Vision Lab"
author = "ICe Vision Lab"

try:
    release = pkg_version("vision-ice-analysis")
except PackageNotFoundError:
    # Source-checkout build (uncommon — CI installs the package first).
    # Mirror the runtime fallback in ``vision_ice_analysis/__init__.py``:
    # parse pyproject.toml directly so the rendered docs always show
    # the canonical version.
    import re

    _pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        _m = re.search(
            r'^version\s*=\s*"([^"]+)"',
            _pyproject.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        release = _m.group(1) if _m else "0.0.0"
    except OSError:
        release = "0.0.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_design",
    "numpydoc",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "**.ipynb_checkpoints"]
autosummary_generate = True

# Wrap any autodoc signature longer than this onto one parameter per line.
# 88 matches the Black / Ruff default; deliberately tighter than this
# project's source line-length (100) to wrap aggressively in rendered docs.
# Requires Sphinx >= 7.1.
maximum_signature_line_length = 88

html_theme = "pydata_sphinx_theme"
html_theme_options = {
    "github_url": "https://github.com/VisionICeNatal/VisionICeAnalysis",
    "navbar_align": "left",
    "show_toc_level": 2,
}
html_static_path = ["_static"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "neural_cca": ("https://goecidbn.github.io/neural_cca/", None),
    # Re-enable once visioniceio publishes a Sphinx site that serves
    # objects.inv (last checked: 2026-05, returned HTTP 404):
    # "visioniceio": ("https://VisionICeNatal.github.io/VisionICeIO/", None),
}
