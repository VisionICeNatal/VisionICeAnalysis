"""Sphinx configuration for VisionICeAnalysis."""

import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

project = "VisionICeAnalysis"
copyright = "2025-2026, ICe Vision Lab"
author = "ICe Vision Lab"

try:
    release = pkg_version("vision-ice-analysis")
except PackageNotFoundError:
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
# Matches PEP 8 hard-wrap. Requires Sphinx >= 7.1.
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
