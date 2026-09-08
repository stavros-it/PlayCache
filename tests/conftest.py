"""Shared fixtures for the PlayCache test suite.

Sets ``QT_QPA_PLATFORM=offscreen`` at import time, before any test module
imports Qt, and provides a session-scoped ``qapp`` fixture so new test files
don't need to duplicate the QApplication bootstrap.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app
