"""Compatibility alias for :mod:`text2pandas.pipelines.answering.render`."""
from importlib import import_module as _import_module
from sys import modules as _modules

_modules[__name__] = _import_module("text2pandas.pipelines.answering.render")
