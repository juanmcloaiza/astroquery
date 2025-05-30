# -*- coding: utf-8 -*-
# Licensed under a 3-clause BSD style license - see LICENSE.rst
#
# Astropy documentation build configuration file.
#
# This file is execfile()d with the current directory set to its containing dir.
#
# Note that not all possible configuration values are present in this file.
#
# All configuration values have a default. Some values are defined in
# the global Astropy configuration which is loaded here before anything else.
# See astropy.sphinx.conf for which values are set there.

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
# sys.path.insert(0, os.path.abspath('..'))
# IMPORTANT: the above commented section was generated by sphinx-quickstart, but
# is *NOT* appropriate for astropy or Astropy affiliated packages. It is left
# commented out with this explanation to make it clear why this should not be
# done. If the sys.path entry above is added, when the astropy.sphinx.conf
# import occurs, it will import the *source* version of astropy instead of the
# version installed (if invoked as "make html" or directly with sphinx), or the
# version in the build directory (if "python setup.py build_sphinx" is used).
# Thus, any C-extensions that are needed to build the documentation will *not*
# be accessible, and the documentation will not build correctly.

import datetime
import os
import sys

# Load all of the global Astropy configuration
try:
    from sphinx_astropy.conf.v1 import *  # noqa
except ImportError:
    print('ERROR: the documentation requires the sphinx-astropy package to '
          'be installed')
    sys.exit(1)

from configparser import ConfigParser
conf = ConfigParser()

conf.read([os.path.join(os.path.dirname(__file__), '..', 'setup.cfg')])
setup_cfg = dict(conf.items('metadata'))

# -- General configuration ----------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
# needs_sphinx = '1.2'

# To perform a Sphinx version check that needs to be more specific than
# major.minor, call `check_sphinx_version("x.y.z")` here.
# check_sphinx_version("1.2.1")

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns.append('_templates')
exclude_patterns.append('release_not*')

# This is added to the end of RST files - a good place to put substitutions to
# be used globally.
rst_epilog += """
"""

del intersphinx_mapping['scipy']
del intersphinx_mapping['h5py']

intersphinx_mapping.update({
    'requests': ('https://requests.kennethreitz.org/en/stable', None),
    'regions': ('https://astropy-regions.readthedocs.io/en/stable', None),
    'mocpy': ('https://cds-astro.github.io/mocpy', None),
    'pyvo': ('https://pyvo.readthedocs.io/en/stable', None),
})

# -- Project information ------------------------------------------------------

# This does not *have* to match the package name, but typically does
project = setup_cfg['name']
author = setup_cfg['author']
copyright = '{0}, {1}'.format(
    datetime.datetime.now(datetime.timezone.utc).year, setup_cfg['author'])

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.

__import__(project)
package = sys.modules[project]

# The short X.Y version.
version = package.__version__.split('-', 1)[0]
# The full version, including alpha/beta/rc tags.
release = package.__version__


# -- Options for HTML output ---------------------------------------------------

# A NOTE ON HTML THEMES
# The global astropy configuration uses a custom theme, 'bootstrap-astropy',
# which is installed along with astropy. A different theme can be used or
# the options for this theme can be modified by overriding some of the
# variables set in the global configuration. The variables set in the
# global configuration are listed below, commented out.

html_theme_options = {
    'logotext1': 'astro',  # white,  semi-bold
    'logotext2': 'query',  # orange, light
    'logotext3': ':docs',   # white,  light
}

# Add any paths that contain custom themes here, relative to this directory.
# To use a different custom theme, add the directory containing the theme.
# html_theme_path = []

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes. To override the custom theme, set this to the
# name of a builtin theme or the name of a custom theme in html_theme_path.
# html_theme = None

# Custom sidebar templates, maps document names to template names.
# html_sidebars = {}

# The name of an image file (within the static path) to use as favicon of the
# docs.  This file should be a Windows icon file (.ico) being 16x16 or 32x32
# pixels large.
# html_favicon = ''

# If not '', a 'Last updated on:' timestamp is inserted at every page bottom,
# using the given strftime format.
# html_last_updated_fmt = ''

# The name for this set of Sphinx documents.  If None, it defaults to
# "<project> v<release> documentation".
html_title = '{0} v{1}'.format(project, release)

# Output file base name for HTML help builder.
htmlhelp_basename = project + 'doc'


# -- Options for LaTeX output --------------------------------------------------

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
latex_documents = [('index', project + '.tex', project + u' Documentation',
                    author, 'manual')]


# -- Options for manual page output --------------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [('index', project.lower(), project + u' Documentation',
              [author], 1)]


# Setting this URL is requited by sphinx-astropy
github_issues_url = 'https://github.com/astropy/astroquery/issues/'


# read the docs mocks
class Mock(object):
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return Mock()

    @classmethod
    def __getattr__(cls, name):
        if name in ('__file__', '__path__'):
            return '/dev/null'
        elif name[0] == name[0].upper():
            return type(name, (), {})
        else:
            return Mock()


MOCK_MODULES = ['atpy', 'beautifulsoup4', 'vo', 'lxml', 'keyring', 'bs4']
for mod_name in MOCK_MODULES:
    sys.modules[mod_name] = Mock()

# -- Options for the edit_on_github extension ----------------------------------------
#
if eval(setup_cfg.get('edit_on_github')):
    extensions += ['astropy.sphinx.ext.edit_on_github']

    # Don't import the module as "version" or it will override the
    # "version" configuration parameter
    from astroquery import version as versionmod
    edit_on_github_project = "astropy/astroquery"
    if versionmod.release:
        edit_on_github_branch = "v" + versionmod.version
    else:
        edit_on_github_branch = "main"

    edit_on_github_source_root = ""
    edit_on_github_doc_root = "docs"

nitpicky = True
nitpick_ignore = [('py:class', 'astroquery.mast.core.MastQueryWithLogin'),
                  # astropy interited type annotations
                  ('py:class', 'ConfigItem')]


# -- Linkcheck builder options ----------------------------------------------
#

# These anchors don't resolve with the linkchecker, but work well from the browser
linkcheck_ignore = ['https://mast.stsci.edu/search/ui/#/jwst',
                    'https://mast.stsci.edu/search/ui/#/hst',
                    'https://nxsa.esac.esa.int/nxsa-web/#aio',
                    'https://ssd.jpl.nasa.gov/horizons/manual.html#center',
                    'https://splatalogue.online/#/basic']
